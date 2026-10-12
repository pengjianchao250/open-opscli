"""AppHub 项目的源码复制迁移服务。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.manager import AppManager
from opscli.app.services.migration_contract import (
    inspect_migration_frontend_build,
    inspect_migration_public_paths,
    inspect_migration_release_assets,
    inspect_migration_runtime_assets,
)
from opscli.app.services.migration_runtime_adaptation import (
    apply_migration_runtime_adaptations,
)

MIGRATION_SCHEMA_VERSION = 2
MIGRATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MIGRATION_ORIGIN_TYPE = "migration_copy"
FINALIZE_JOURNAL_NAME = ".opscli-migration-finalize.json"
EXCLUDED_PARTS = {
    ".git",
    ".sites-checkout",
    ".sites-runtime",
    ".opscli",
    ".venv",
    ".vinext",
    ".wrangler",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "coverage",
    "dist",
    ".next",
    ".nuxt",
    ".cache",
    "tmp",
    "temp",
    "logs",
}
SENSITIVE_GIT_PATTERNS = (".env", ".env.*", "*.db", "*.sqlite", "*.sqlite3", "/data")
LEGACY_STATE_FILES = {
    "audit-snapshot.json",
    "coverage-matrix.json",
    "ui-blueprint.json",
}
STARTUP_DOCUMENT_NAMES = ("README.md", "DEPLOY.md", "DEPLOYMENT.md")
DOCUMENTED_NODE_COMMAND_RE = re.compile(
    r"\b(?:pnpm(?:\s+run)?|npm\s+run|yarn(?:\s+run)?|bun(?:\s+run)?)"
    r"\s+(?P<script>[A-Za-z0-9][A-Za-z0-9:._-]*)"
)
SCRIPT_PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.(?:py|mjs|cjs|js|ts))"
)
ORCHESTRATOR_SOURCE_RE = re.compile(
    r"\b(?:subprocess\.Popen|asyncio\.create_subprocess_exec|"
    r"child_process\.(?:spawn|fork)|spawn\s*\(|fork\s*\()"
)
SERVER_COMMAND_RE = re.compile(
    r"\b(?:vinext|vite|next\s+start|nuxt|serve|uvicorn|gunicorn|hypercorn|flask)\b|"
    r"(?:^|[\\/])(?:server|run_local)\.(?:py|mjs|cjs|js|ts)\b",
    re.IGNORECASE,
)
PORT_ARGUMENT_RE = re.compile(r"(?<![A-Za-z0-9_-])--port(?:\s+|=)(?P<port>\d+)\b")
PORT_ENV_RE = re.compile(
    r"(?:configured_port|os\.environ\.get|os\.getenv)\(\s*['\"]"
    r"(?P<python>[A-Z][A-Z0-9_]*PORT)['\"]|"
    r"process\.env\.(?P<node>[A-Z][A-Z0-9_]*PORT)"
)
RUNTIME_SCRIPT_NAMES = {
    "start",
    "start:prod",
    "start:production",
    "serve",
    "preview",
    "dev",
    "dev:lan",
    "dev:local",
    "dashboard",
    "web",
    "app",
}


class MigrationService:
    """执行源码复制、启动扫描、AppHub 登记和 Git 初始化。"""

    def __init__(self, *, app_manager: AppManager | None = None) -> None:
        self.app_manager = app_manager
        self._owns_manager = app_manager is None

    def close(self) -> None:
        if self._owns_manager and self.app_manager is not None:
            self.app_manager.close()
            self.app_manager = None

    def start(
        self,
        source: str | Path,
        target_root: str | Path | None = None,
        *,
        app_name: str | None = None,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        source_path = self._resolve_existing_directory(source, "源项目")
        migration_key = self._migration_id(migration_id)
        if target_root is not None:
            self._recover_interrupted_commit(Path(target_root).expanduser())
        target_path, target_reason = self._resolve_target(source_path, target_root)
        self._validate_roots(source_path, target_path)
        target_existed = target_path.exists()

        staging = target_path.parent / f".{target_path.name}.migration-{migration_key}.tmp"
        if staging.exists():
            raise AppProjectError(
                "APP-MIGRATION-EXISTS",
                f"迁移临时目录已存在：{staging}",
                fix_hint="清理上次中断留下的临时目录后重试。",
            )

        state: dict[str, Any] = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "origin_type": MIGRATION_ORIGIN_TYPE,
            "source_root": str(source_path),
            "target_root": str(target_path),
            "target_reason": target_reason,
            "app_name": app_name.strip() if app_name and app_name.strip() else source_path.name,
            "phase": "target_resolved",
            "status": "running",
            "delivery_ready": False,
            "generated_files": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        try:
            copy_manifest = self._copy_source(source_path, staging, migration_key)
            state.update(phase="copied", updated_at=_now())
            migration_dir = staging / ".opscli" / "migration" / migration_key
            self._write_json(migration_dir / "copy-manifest.json", copy_manifest)
            self._write_json(migration_dir / "migration.json", state)
            self._write_json(
                staging / ".opscli" / "migration" / "current.json",
                {
                    "schema_version": MIGRATION_SCHEMA_VERSION,
                    "migration_id": migration_key,
                },
            )
            self._write_json(
                staging / ".opscli" / "project.json",
                {
                    "schema_version": MIGRATION_SCHEMA_VERSION,
                    "project_type": "apphub",
                    "origin_type": MIGRATION_ORIGIN_TYPE,
                    "migration_id": migration_key,
                    "source_root": str(source_path),
                    "target_root": str(target_path),
                    "source_readonly": True,
                    "template_cloned": False,
                    "business_source_rewritten": False,
                },
            )
            if self._ensure_gitignore(staging):
                state["generated_files"].append(".gitignore")
            if self._ensure_dockerignore(staging):
                state["generated_files"].append(".dockerignore")
            startup = self._scan_and_write_startup(staging, migration_key)
            if startup.get("wrapper_generated"):
                state["generated_files"].append("scripts/start_app.py")
            state.update(
                phase=(
                    "startup_ready"
                    if startup["status"] == "ready"
                    else "startup_manual_required"
                ),
                startup_status=startup["status"],
                updated_at=_now(),
            )
            self._scan_and_write_adaptation(staging, state, startup)
            self._write_json(migration_dir / "migration.json", state)
            if target_existed:
                self._commit_to_existing_target(staging, target_path, migration_key)
            else:
                staging.rename(target_path)
            self._assert_source_unchanged(source_path, copy_manifest["source_fingerprint"])
            return self._continue_migration(target_path, state)
        except Exception as exc:
            state.update(
                status="failed",
                failed_phase=state.get("phase"),
                error=_error_payload(exc),
                delivery_ready=False,
                updated_at=_now(),
            )
            rollback_incomplete = (
                isinstance(exc, AppProjectError)
                and exc.code == "APP-MIGRATION-FINALIZE"
                and exc.detail.get("rollback_completed") is False
            )
            if staging.exists() and not rollback_incomplete:
                shutil.rmtree(staging, ignore_errors=True)
            elif not staging.exists() and target_path.exists():
                self._write_state(target_path, migration_key, state)
            raise

    def resume(
        self,
        target: str | Path = ".",
        *,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        """从已持久化阶段继续，不重复复制源文件或重复登记应用。"""
        root, state, _ = self._load_context(target, migration_id)
        state.pop("error", None)
        state.pop("failed_phase", None)
        state.update(status="running", delivery_ready=False, updated_at=_now())
        self._write_state(root, state["migration_id"], state)
        try:
            return self._continue_migration(root, state)
        except Exception as exc:
            state.update(
                status="failed",
                failed_phase=state.get("phase"),
                error=_error_payload(exc),
                delivery_ready=False,
            )
            self._write_state(root, state["migration_id"], state)
            raise

    def _continue_migration(self, root: Path, state: dict[str, Any]) -> dict[str, Any]:
        migration_key = state["migration_id"]
        startup = self._scan_and_write_startup(root, migration_key)
        if startup.get("wrapper_generated"):
            self._record_generated_file(state, "scripts/start_app.py")
        state.update(startup_status=startup["status"], delivery_ready=False)
        adaptation = self._scan_and_write_adaptation(root, state, startup)
        if startup["status"] != "ready":
            state.update(
                phase="startup_manual_required",
                status="manual_required",
                adaptation_status="adaptation_manual_required",
            )
            self._write_state(root, migration_key, state)
            return self._migration_result(
                root,
                state,
                message="源码副本已建立；启动方式无法可靠识别，需要人工补充后执行 migrate resume。",
            )
        if adaptation["status"] == "adaptation_manual_required":
            state.update(
                phase="adaptation_manual_required",
                status="manual_required",
                adaptation_status="adaptation_manual_required",
            )
            self._write_state(root, migration_key, state)
            return self._migration_result(
                root,
                state,
                message="源码副本已建立；缺少可验证的 AppHub 生产适配资产，需要人工补齐后执行 migrate resume。",
            )

        manager = self._get_manager()
        create_result: dict[str, Any] | None = None
        init_result: dict[str, Any] | None = None
        if not state.get("app_id"):
            create_result = manager.create_app(
                str(state.get("app_name") or root.name),
                path=root,
                include_default_database=False,
            )
            app_id = create_result.get("app_id")
            if not isinstance(app_id, str) or not app_id:
                raise AppProjectError("APPHUB-PROTOCOL", "AppHub 创建响应缺少 app_id。")
            state.update(phase="registered", app_id=app_id, status="running")
            self._write_state(root, migration_key, state)

        self._ensure_app_manifest(
            root,
            app_id=str(state["app_id"]),
            title=str(state.get("app_name") or root.name),
        )
        self._record_generated_file(state, "app.yaml")
        adaptation = self._scan_and_write_adaptation(root, state, startup)
        state["adaptation_status"] = adaptation["status"]
        if adaptation["status"] != "ready":
            state.update(phase="adaptation_manual_required", status="manual_required")
            self._write_state(root, migration_key, state)
            return self._migration_result(
                root,
                state,
                create=create_result,
                message="AppHub 应用已登记，但最小适配层仍需人工处理；完成后执行 migrate resume。",
            )

        if state.get("phase") not in {"initialized", "push_ready"}:
            init_result = manager.init_git(root)
        state.update(phase="initialized", status="running", adaptation_status="ready")
        self._write_state(root, migration_key, state)
        verified = self.verify(root, migration_id=migration_key)
        return {
            **verified,
            "target_reason": state.get("target_reason"),
            "target_notice": self._target_notice(root, state),
            "create": create_result,
            "init": init_result,
            "message": "源码复制、最小适配、AppHub 登记和 Git 初始化已完成。",
        }

    def status(
        self,
        target: str | Path = ".",
        *,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        root, state, project = self._load_context(target, migration_id)
        migration_key = state["migration_id"]
        migration_dir = self._migration_dir(root, migration_key)
        startup = self._read_json(migration_dir / "startup-manifest.json", required=False) or {}
        adaptation = (
            self._read_json(migration_dir / "adaptation-manifest.json", required=False)
            or {}
        )
        copy_manifest = (
            self._read_json(migration_dir / "copy-manifest.json", required=False) or {}
        )
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "origin_type": project.get("origin_type"),
            "source_root": state.get("source_root"),
            "target_root": str(root),
            "phase": state.get("phase"),
            "status": state.get("status"),
            "startup_status": startup.get("status") or state.get("startup_status"),
            "adaptation_status": adaptation.get("status") or state.get("adaptation_status"),
            "delivery_ready": bool(state.get("delivery_ready")),
            "app_id": state.get("app_id"),
            "copy_manifest": str(migration_dir / "copy-manifest.json"),
            "startup_manifest": str(migration_dir / "startup-manifest.json"),
            "adaptation_manifest": str(migration_dir / "adaptation-manifest.json"),
            "copied_file_count": copy_manifest.get("included_file_count", 0),
            "excluded_file_count": copy_manifest.get("excluded_file_count", 0),
            "state_path": str(migration_dir / "migration.json"),
        }

    def scan_startup(
        self,
        target: str | Path = ".",
        *,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        root, state, _ = self._load_context(target, migration_id)
        startup = self._scan_and_write_startup(root, state["migration_id"])
        if startup.get("wrapper_generated"):
            self._record_generated_file(state, "scripts/start_app.py")
        adaptation = self._scan_and_write_adaptation(root, state, startup)
        state.update(
            phase="startup_ready" if startup["status"] == "ready" else "startup_manual_required",
            startup_status=startup["status"],
            adaptation_status=adaptation["status"],
            status="running" if startup["status"] == "ready" else "manual_required",
            delivery_ready=False,
            updated_at=_now(),
        )
        self._write_state(root, state["migration_id"], state)
        return {
            **self.status(root, migration_id=state["migration_id"]),
            "startup": startup,
            "adaptation": adaptation,
        }

    def verify(
        self,
        target: str | Path = ".",
        *,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        root, state, project = self._load_context(target, migration_id)
        migration_key = state["migration_id"]
        migration_dir = self._migration_dir(root, migration_key)
        copy_manifest = (
            self._read_json(migration_dir / "copy-manifest.json", required=True) or {}
        )
        startup_manifest = (
            self._read_json(migration_dir / "startup-manifest.json", required=True) or {}
        )
        adaptation_manifest = (
            self._read_json(migration_dir / "adaptation-manifest.json", required=True)
            or {}
        )
        source = Path(str(project.get("source_root") or "")).expanduser().resolve()
        managed_files = adaptation_manifest.get("managed_files")
        frontend_build = inspect_migration_frontend_build(root)
        public_paths = inspect_migration_public_paths(root)
        runtime_assets = inspect_migration_runtime_assets(root)
        copy_baseline_verified = state.get("phase") == "push_ready"
        checks = {
            "source_exists": source.is_dir(),
            "source_unchanged": source.is_dir() and self._fingerprint_files(
                source, copy_manifest.get("included_files")
            ) == copy_manifest.get("source_fingerprint"),
            "target_independent": (
                source != root
                and source not in root.parents
                and root not in source.parents
            ),
            "migration_marker": project.get("origin_type") == MIGRATION_ORIGIN_TYPE,
            # The copy hash is a pre-delivery migration gate. Once that gate has
            # passed, normal maintenance must be allowed to change business files.
            "copy_verified": copy_baseline_verified
            or self._copied_files_match(root, copy_manifest, managed_files),
            "startup_ready": startup_manifest.get("status") == "ready",
            "adaptation_ready": adaptation_manifest.get("status") == "ready",
            "frontend_build_contract": frontend_build["ready"],
            "public_path_contract": public_paths["ready"],
            "runtime_asset_contract": runtime_assets["ready"],
            "app_manifest_identity": self._manifest_matches(root, state.get("app_id")),
            "git_initialized": (root / ".git").exists(),
            "app_binding": (root / ".opscli" / "app.json").is_file(),
        }
        passed = all(checks.values())
        state.update(
            phase="push_ready" if passed else state.get("phase"),
            status="ready" if passed else "blocked",
            adaptation_status=adaptation_manifest.get("status"),
            delivery_ready=passed,
            updated_at=_now(),
        )
        self._write_state(root, migration_key, state)
        return {
            **self.status(root, migration_id=migration_key),
            "passed": passed,
            "checks": checks,
            "frontend_build": frontend_build,
            "public_paths": public_paths,
            "runtime_assets": runtime_assets,
        }

    def convert_legacy(
        self,
        target: str | Path = ".",
        *,
        migration_id: str | None = None,
    ) -> dict[str, Any]:
        root = self._resolve_existing_directory(target, "迁移目标")
        current_path = root / ".opscli" / "migration" / "current.json"
        current = self._read_json(current_path, required=True) or {}
        migration_key = self._migration_id(migration_id or str(current.get("migration_id") or ""))
        legacy_dir = self._migration_dir(root, migration_key)
        if not legacy_dir.exists():
            raise AppProjectError("APP-MIGRATION-NOT-FOUND", f"迁移状态目录不存在：{legacy_dir}")
        has_legacy = any((legacy_dir / name).exists() for name in LEGACY_STATE_FILES)
        if not has_legacy:
            raise AppProjectError("APP-MIGRATION-STATE", "当前迁移目录没有可转换的旧重构状态。")
        backup = (
            root
            / ".opscli"
            / "migration-legacy"
            / f"{migration_key}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_dir), str(backup))
        self._write_json(current_path, {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "status": "legacy_converted",
            "legacy_backup": str(backup),
        })
        return {
            "migration_id": migration_key,
            "status": "legacy_converted",
            "legacy_backup": str(backup),
        }

    def _get_manager(self) -> AppManager:
        if self.app_manager is None:
            self.app_manager = AppManager()
        return self.app_manager

    def _resolve_target(self, source: Path, requested: str | Path | None) -> tuple[Path, str]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base_name = f"app-hub-source-{timestamp}"
        if requested is None:
            parent = Path.cwd().resolve()
            candidate = self._unique_path(parent / base_name)
            return candidate, "conversation_directory_default"
        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.exists() and not candidate.is_dir():
            raise AppProjectError("APP-MIGRATION-TARGET", f"迁移目标不是目录：{candidate}")
        if candidate.exists() and any(candidate.iterdir()):
            return self._unique_path(candidate / base_name), "user_non_empty_fallback"
        return candidate, "user_requested"

    def _unique_path(self, candidate: Path) -> Path:
        if not candidate.exists():
            return candidate
        for index in range(1, 1000):
            alternative = candidate.with_name(f"{candidate.name}-{index:04d}")
            if not alternative.exists():
                return alternative
        raise AppProjectError("APP-MIGRATION-TARGET", f"无法生成唯一迁移目标：{candidate}")

    def _copy_source(self, source: Path, staging: Path, migration_id: str) -> dict[str, Any]:
        included: list[str] = []
        excluded: list[dict[str, str]] = []
        staging.mkdir(parents=True, exist_ok=False)
        directories, files, excluded = self._source_inventory(source)
        for relative in directories:
            (staging / relative).mkdir(parents=True, exist_ok=True)
        for relative in files:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
            included.append(relative.as_posix())
        source_fingerprint = self._fingerprint_files(source, included)
        target_fingerprint = self._fingerprint_files(staging, included)
        if source_fingerprint != target_fingerprint:
            raise AppProjectError("APP-MIGRATION-SOURCE-CHANGED", "复制过程中源项目发生变化，请重试。")
        file_hashes = {
            relative: hashlib.sha256((source / relative).read_bytes()).hexdigest()
            for relative in sorted(included)
        }
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_id,
            "source_root": str(source),
            "included_file_count": len(included),
            "included_files": sorted(included),
            "excluded_file_count": len(excluded),
            "excluded_files": excluded,
            "sensitive_files": [item for item in included if self._is_sensitive(Path(item))],
            "source_fingerprint": source_fingerprint,
            "target_fingerprint": target_fingerprint,
            "file_hashes": file_hashes,
            "created_at": _now(),
        }

    def _source_inventory(
        self,
        source: Path,
    ) -> tuple[list[Path], list[Path], list[dict[str, str]]]:
        """扫描待复制条目，并在进入依赖或运行时目录前完成剪枝。"""
        directories: list[Path] = []
        files: list[Path] = []
        excluded: list[dict[str, str]] = []

        def raise_walk_error(error: OSError) -> None:
            raise error

        for current, directory_names, file_names in os.walk(
            source,
            topdown=True,
            followlinks=False,
            onerror=raise_walk_error,
        ):
            current_path = Path(current)
            retained_directories: list[str] = []
            for name in sorted(directory_names):
                path = current_path / name
                relative = path.relative_to(source)
                reason = self._excluded_reason(relative, path)
                if reason:
                    excluded.append({"path": relative.as_posix(), "reason": reason})
                    continue
                directories.append(relative)
                retained_directories.append(name)
            directory_names[:] = retained_directories

            for name in sorted(file_names):
                path = current_path / name
                relative = path.relative_to(source)
                reason = self._excluded_reason(relative, path)
                if reason:
                    excluded.append({"path": relative.as_posix(), "reason": reason})
                    continue
                if path.is_file():
                    files.append(relative)
        return directories, files, excluded

    def _commit_to_existing_target(
        self,
        staging: Path,
        target: Path,
        migration_id: str,
    ) -> None:
        """将已校验的临时副本提交到既有空目录，失败时回滚已移动条目。"""
        if not target.is_dir() or any(target.iterdir()):
            raise AppProjectError(
                "APP-MIGRATION-TARGET-CHANGED",
                f"迁移目标在复制期间不再为空：{target}",
                fix_hint="清理目标目录中的新增内容后重试。",
            )

        # `.opscli` 最后移动，避免状态目录先进入目标后又参与其余条目的回滚。
        entries = sorted(
            staging.iterdir(),
            key=lambda path: (path.name == ".opscli", path.name),
        )
        journal = target / FINALIZE_JOURNAL_NAME
        moved: list[str] = []
        self._write_json(
            journal,
            {
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "migration_id": migration_id,
                "status": "committing",
                "target_root": str(target),
                "staging_root": str(staging),
                "moved_entries": moved,
                "pending_entry": None,
                "updated_at": _now(),
            },
        )
        try:
            for entry in entries:
                self._write_json(
                    journal,
                    {
                        "schema_version": MIGRATION_SCHEMA_VERSION,
                        "migration_id": migration_id,
                        "status": "committing",
                        "target_root": str(target),
                        "staging_root": str(staging),
                        "moved_entries": moved,
                        "pending_entry": entry.name,
                        "updated_at": _now(),
                    },
                )
                entry.replace(target / entry.name)
                moved.append(entry.name)
                self._write_json(
                    journal,
                    {
                        "schema_version": MIGRATION_SCHEMA_VERSION,
                        "migration_id": migration_id,
                        "status": "committing",
                        "target_root": str(target),
                        "staging_root": str(staging),
                        "moved_entries": moved,
                        "pending_entry": None,
                        "updated_at": _now(),
                    },
                )
            staging.rmdir()
            journal.unlink()
        except Exception as exc:
            rollback_errors: list[str] = []
            for name in reversed(moved):
                committed = target / name
                try:
                    if committed.exists():
                        committed.replace(staging / name)
                except OSError as rollback_error:
                    rollback_errors.append(f"{name}: {rollback_error}")
            if not rollback_errors and journal.exists():
                journal.unlink()
            raise AppProjectError(
                "APP-MIGRATION-FINALIZE",
                f"迁移副本无法提交到目标目录：{target}",
                fix_hint="确认目标目录未被其他程序占用且当前账号具有写入权限后重试。",
                detail={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "filename": str(getattr(exc, "filename", "") or "") or None,
                    "errno": getattr(exc, "errno", None),
                    "winerror": getattr(exc, "winerror", None),
                    "rollback_completed": not rollback_errors,
                    "rollback_errors": rollback_errors,
                },
            ) from exc

    def _recover_interrupted_commit(self, requested_target: Path) -> None:
        """发现上次被强制中断的目标提交时，回滚临时条目供本次重新复制。"""
        target = (
            (Path.cwd() / requested_target).resolve()
            if not requested_target.is_absolute()
            else requested_target.resolve()
        )
        journal = target / FINALIZE_JOURNAL_NAME
        if not target.is_dir() or not journal.is_file():
            return
        payload = self._read_json(journal, required=True) or {}
        staging_value = payload.get("staging_root")
        moved_value = payload.get("moved_entries")
        pending_value = payload.get("pending_entry")
        if not isinstance(staging_value, str) or not isinstance(moved_value, list):
            raise AppProjectError(
                "APP-MIGRATION-RECOVERY",
                f"迁移提交日志格式错误：{journal}",
                fix_hint="保留现场并提交反馈，不要手工覆盖目标目录。",
            )
        staging = Path(staging_value).resolve()
        expected_prefix = f".{target.name}.migration-"
        if staging.parent != target.parent or not staging.name.startswith(expected_prefix):
            raise AppProjectError(
                "APP-MIGRATION-RECOVERY",
                f"迁移提交日志包含非法临时目录：{staging}",
                fix_hint="保留现场并提交反馈，不要手工移动日志中指向的目录。",
            )
        names = [name for name in moved_value if isinstance(name, str)]
        if isinstance(pending_value, str) and pending_value not in names:
            names.append(pending_value)
        if any(Path(name).name != name or name in {"", ".", ".."} for name in names):
            raise AppProjectError(
                "APP-MIGRATION-RECOVERY",
                f"迁移提交日志包含非法条目：{journal}",
                fix_hint="保留现场并提交反馈，不要手工覆盖目标目录。",
            )
        staging.mkdir(parents=False, exist_ok=True)
        rollback_errors: list[str] = []
        for name in reversed(names):
            committed = target / name
            try:
                if committed.exists():
                    committed.replace(staging / name)
            except OSError as exc:
                rollback_errors.append(f"{name}: {exc}")
        if rollback_errors:
            raise AppProjectError(
                "APP-MIGRATION-RECOVERY",
                f"上次中断的迁移提交无法自动回滚：{target}",
                fix_hint="关闭占用目标文件的程序后，使用相同命令重试。",
                detail={"rollback_errors": rollback_errors},
            )
        shutil.rmtree(staging)
        journal.unlink()

    def _scan_and_write_startup(self, root: Path, migration_id: str) -> dict[str, Any]:
        manifest_path = self._migration_dir(root, migration_id) / "startup-manifest.json"
        previous = self._read_json(manifest_path, required=False) or {}
        docker = self._detect_docker_runtime(root)
        backend = self._detect_backend(root)
        frontend = self._detect_frontend(root)
        runtime, launch_mode, selection_reason = self._select_runtime(
            docker=docker,
            backend=backend,
            frontend=frontend,
        )
        status = "ready" if runtime else "startup_manual_required"
        manifest = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_id,
            "status": status,
            "runtime": runtime,
            "runtime_candidates": self._runtime_candidates_for_manifest(
                docker=docker,
                backend=backend,
                frontend=frontend,
            ),
            "launch_mode": launch_mode,
            "selection_reason": selection_reason,
            "docker": docker,
            "backend": backend,
            "frontend": frontend,
            "wrapper": str(root / "scripts" / "start_app.py"),
            "generated_at": _now(),
        }
        wrapper = root / "scripts" / "start_app.py"
        if not wrapper.exists() or previous.get("wrapper_generated") is True:
            self._write_text(wrapper, _startup_wrapper(manifest))
            manifest["wrapper_generated"] = True
        else:
            manifest["wrapper_generated"] = False
        self._write_json(manifest_path, manifest)
        return manifest

    def _select_runtime(
        self,
        *,
        docker: dict[str, Any] | None,
        backend: dict[str, Any] | None,
        frontend: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        if docker is not None:
            return docker, "single", "docker_entry"
        if frontend is not None and frontend.get("orchestrator") is True:
            return frontend, "orchestrator", str(
                frontend.get("selection_reason") or "orchestrator"
            )
        if backend is not None and frontend is not None:
            return backend, "dual", "backend_frontend_pair"
        if backend is not None:
            return backend, "single", "single_backend"
        if frontend is not None:
            return frontend, "single", str(
                frontend.get("selection_reason") or "single_frontend"
            )
        return None, None, None

    def _runtime_candidates_for_manifest(
        self,
        *,
        docker: dict[str, Any] | None,
        backend: dict[str, Any] | None,
        frontend: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        candidates = [item for item in (docker, backend) if isinstance(item, dict)]
        if isinstance(frontend, dict):
            node_candidates = frontend.get("candidate_scripts")
            if isinstance(node_candidates, list):
                candidates.extend(item for item in node_candidates if isinstance(item, dict))
            else:
                candidates.append(frontend)
        return candidates

    def _scan_and_write_adaptation(
        self,
        root: Path,
        state: dict[str, Any],
        startup: dict[str, Any],
    ) -> dict[str, Any]:
        app_id = state.get("app_id")
        runtime_adaptation = apply_migration_runtime_adaptations(root, startup)
        for relative in runtime_adaptation["managed_files"]:
            self._record_generated_file(state, relative)
        frontend_build = inspect_migration_frontend_build(root)
        public_paths = inspect_migration_public_paths(root)
        runtime_assets = inspect_migration_runtime_assets(root)
        release_contract = (
            inspect_migration_release_assets(root, expected_app_id=str(app_id))
            if isinstance(app_id, str) and app_id
            else None
        )
        managed_files = self._managed_adaptation_files(
            root,
            state,
            startup=startup,
            public_paths=public_paths,
        )
        checks = {
            "startup_ready": startup.get("status") == "ready",
            "gitignore_present": (root / ".gitignore").is_file(),
            "start_wrapper_present": (root / "scripts" / "start_app.py").is_file(),
            "dockerfile_present": (root / "Dockerfile").is_file(),
            "runtime_adaptation_contract": (
                runtime_adaptation["status"] != "adaptation_manual_required"
            ),
            "frontend_build_contract": frontend_build["ready"],
            "public_path_contract": public_paths["ready"],
            "runtime_asset_contract": runtime_assets["ready"],
            "app_manifest_identity": self._manifest_matches(root, app_id),
            "release_contract": release_contract is None or release_contract["ready"],
        }
        pre_registration_checks = {
            key: value for key, value in checks.items() if key != "app_manifest_identity"
        }
        if not all(pre_registration_checks.values()):
            status = "adaptation_manual_required"
        elif not app_id:
            status = "registration_required"
        elif all(checks.values()):
            status = "ready"
        else:
            status = "adaptation_manual_required"
        manifest = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": state["migration_id"],
            "status": status,
            "checks": checks,
            "runtime_adaptation": runtime_adaptation,
            "frontend_build": frontend_build,
            "public_paths": public_paths,
            "runtime_assets": runtime_assets,
            "release_contract": release_contract,
            "managed_files": managed_files,
            "generated_or_modified_files": managed_files,
            "local_only_files": [
                ".opscli/project.json",
                f".opscli/migration/{state['migration_id']}/migration.json",
                f".opscli/migration/{state['migration_id']}/copy-manifest.json",
                f".opscli/migration/{state['migration_id']}/startup-manifest.json",
                f".opscli/migration/{state['migration_id']}/adaptation-manifest.json",
            ],
            "updated_at": _now(),
        }
        self._write_json(
            self._migration_dir(root, state["migration_id"]) / "adaptation-manifest.json",
            manifest,
        )
        return manifest

    def _managed_adaptation_files(
        self,
        root: Path,
        state: dict[str, Any],
        *,
        startup: dict[str, Any],
        public_paths: dict[str, Any],
    ) -> list[str]:
        """记录已验证薄适配允许修改的复制文件，继续阻止无关业务漂移。"""
        managed = {
            item
            for item in state.get("generated_files") or []
            if isinstance(item, str) and item
        }
        migration_id = state.get("migration_id")
        if not isinstance(migration_id, str) or not migration_id:
            return sorted(managed)
        copy_manifest = self._read_json(
            self._migration_dir(root, migration_id) / "copy-manifest.json",
            required=False,
        ) or {}
        included = {
            item
            for item in copy_manifest.get("included_files") or []
            if isinstance(item, str) and item
        }
        hashes = copy_manifest.get("file_hashes")
        if not included or not isinstance(hashes, dict):
            return sorted(managed)

        candidates: set[str] = set()
        candidates.update(
            relative
            for relative in (
                "app.yaml",
                "Dockerfile",
                ".dockerignore",
                ".gitignore",
                "scripts/start_app.py",
            )
            if (root / relative).is_file()
        )
        candidates.update(
            relative for relative in included if self._is_sensitive(Path(relative))
        )
        detail = public_paths.get("detail")
        scanned_roots = detail.get("scanned_roots") if isinstance(detail, dict) else []
        for scanned_root in scanned_roots or []:
            if not isinstance(scanned_root, str) or not scanned_root:
                continue
            prefix = scanned_root.rstrip("/") + "/"
            candidates.update(
                relative
                for relative in included
                if relative == scanned_root or relative.startswith(prefix)
            )
            scan_root = root / scanned_root
            if scan_root.is_dir():
                candidates.update(
                    path.relative_to(root).as_posix()
                    for path in scan_root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )

        for runtime in (
            startup.get("runtime"),
            startup.get("docker"),
            startup.get("backend"),
            startup.get("frontend"),
        ):
            if not isinstance(runtime, dict):
                continue
            evidence = runtime.get("evidence")
            if isinstance(evidence, str):
                evidence_path = Path(evidence).as_posix()
                if (root / evidence_path).is_file():
                    candidates.add(evidence_path)
            cwd = runtime.get("cwd") if isinstance(runtime.get("cwd"), str) else "."
            for token in runtime.get("command") or []:
                if not isinstance(token, str) or not token:
                    continue
                direct = (Path(cwd) / token).as_posix().lstrip("./")
                if (root / direct).is_file():
                    candidates.add(direct)
                module = token.split(":", 1)[0]
                module_path = (Path(cwd) / (module.replace(".", "/") + ".py")).as_posix()
                module_path = module_path.lstrip("./")
                if (root / module_path).is_file():
                    candidates.add(module_path)

        for relative in candidates:
            path = root / relative
            expected_hash = hashes.get(relative)
            if path.is_file() and not path.is_symlink() and relative not in included:
                managed.add(relative)
            elif (
                isinstance(expected_hash, str)
                and path.is_file()
                and not path.is_symlink()
                and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
            ):
                managed.add(relative)
        return sorted(managed)

    def _detect_docker_runtime(self, root: Path) -> dict[str, Any] | None:
        """优先使用 Dockerfile 已声明的生产启动命令作为运行证据。"""
        dockerfile = root / "Dockerfile"
        if not dockerfile.is_file():
            return None
        try:
            content = dockerfile.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        matches = list(
            re.finditer(r"(?im)^\s*(?P<kind>CMD|ENTRYPOINT)\s+(?P<value>.+)$", content)
        )
        if not matches:
            return None
        match = next(
            (item for item in reversed(matches) if item.group("kind").upper() == "CMD"),
            matches[-1],
        )
        raw_command = match.group("value").strip()
        try:
            parsed = json.loads(raw_command) if raw_command.startswith("[") else None
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and parsed and all(
            isinstance(item, str) and item for item in parsed
        ):
            command = parsed
        else:
            try:
                command = shlex.split(raw_command, posix=True)
            except ValueError:
                return None
        if not command:
            return None
        return {
            "kind": "dockerfile_native",
            "command": command,
            "cwd": ".",
            "evidence": "Dockerfile",
        }

    def _detect_backend(self, root: Path) -> dict[str, Any] | None:
        candidates = (
            root / "backend" / "app.py",
            root / "backend" / "main.py",
            root / "app.py",
            root / "main.py",
        )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root).with_suffix("")
            module = ".".join(relative.parts)
            content = candidate.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\bapp\s*=\s*(?:FastAPI|Starlette)\s*\(", content):
                return {
                    "kind": "python_web",
                    "command": ["python", "-m", "uvicorn", f"{module}:app"],
                    "cwd": ".",
                    "evidence": candidate.relative_to(root).as_posix(),
                }
        return None

    def _detect_frontend(self, root: Path) -> dict[str, Any] | None:
        package_paths = self._frontend_package_candidates(root)
        detected = [
            runtime
            for package_path in package_paths
            if (runtime := self._node_runtime_from_package(root, package_path)) is not None
        ]
        if not detected:
            return None
        if len(detected) == 1:
            return detected[0]

        dockerfile = root / "Dockerfile"
        docker_content = (
            dockerfile.read_text(encoding="utf-8", errors="replace")
            if dockerfile.is_file()
            else ""
        )
        referenced = [
            runtime
            for runtime in detected
            if runtime["cwd"] != "." and runtime["cwd"] in docker_content.replace("\\", "/")
        ]
        if len(referenced) == 1:
            return referenced[0]

        package_priority = {"frontend/package.json": 2, "package.json": 1}
        return max(
            detected,
            key=lambda runtime: (
                int(runtime.get("selection_score") or 0),
                package_priority.get(str(runtime.get("evidence")), 0),
                -len(Path(str(runtime.get("evidence"))).parts),
                str(runtime.get("evidence")),
            ),
        )

    def _frontend_package_candidates(self, root: Path) -> list[Path]:
        """扫描可运行的 package.json，兼容单仓库与任意深度的前端目录。"""
        candidates: list[Path] = []
        for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
            directory_names[:] = sorted(
                name for name in directory_names if name not in EXCLUDED_PARTS
            )
            if "package.json" in file_names:
                candidates.append(Path(current) / "package.json")
        priority = {"frontend/package.json": 0, "package.json": 1}
        return sorted(
            candidates,
            key=lambda path: (
                priority.get(path.relative_to(root).as_posix(), 2),
                len(path.relative_to(root).parts),
                path.relative_to(root).as_posix(),
            ),
        )

    def _node_runtime_from_package(
        self,
        root: Path,
        package_path: Path,
    ) -> dict[str, Any] | None:
        """从单个包清单提取有业务入口证据的 Node 启动命令。"""
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if not isinstance(scripts, dict):
            return None
        frontend_root = package_path.parent
        lock_roots = [frontend_root, *frontend_root.parents]
        lock_roots = [path for path in lock_roots if path == root or root in path.parents]
        if any((path / "pnpm-lock.yaml").exists() for path in lock_roots):
            manager = "pnpm"
        elif any((path / "yarn.lock").exists() for path in lock_roots):
            manager = "yarn"
        else:
            manager = "npm"
        nonempty_scripts = [
            command
            for command in scripts.values()
            if isinstance(command, str) and command.strip()
        ]
        documented_scripts = (
            self._documented_node_scripts(root, frontend_root)
            if len(nonempty_scripts) > 1
            else {}
        )
        candidates: list[dict[str, Any]] = []
        for script, raw_command in scripts.items():
            if not isinstance(script, str) or not isinstance(raw_command, str):
                continue
            script_command = raw_command.strip()
            if not script_command:
                continue
            documented_order = documented_scripts.get(script)
            referenced_paths = self._referenced_script_paths(
                root,
                frontend_root,
                script_command,
            )
            orchestrator = self._script_uses_process_orchestrator(referenced_paths)
            if not self._is_runtime_node_script(
                script,
                script_command,
                documented=documented_order is not None,
                orchestrator=orchestrator,
            ):
                continue
            command = [manager, "run", script] if manager != "yarn" else [manager, script]
            port_match = PORT_ARGUMENT_RE.search(script_command)
            port_adaptation: dict[str, Any] | None = None
            if port_match is not None and port_match.group("port") != "8000":
                command.extend(
                    ["--port", "8000"]
                    if manager == "yarn"
                    else ["--", "--port", "8000"]
                )
                port_adaptation = {
                    "kind": "cli_override",
                    "source_port": int(port_match.group("port")),
                    "target_port": 8000,
                }
            environment = self._runtime_environment_overrides(referenced_paths)
            selection_reason = self._node_selection_reason(
                documented=documented_order is not None,
                orchestrator=orchestrator,
            )
            candidate: dict[str, Any] = {
                "kind": "node_web",
                "command": command,
                "cwd": frontend_root.relative_to(root).as_posix(),
                "script": script,
                "script_command": script_command,
                "evidence": package_path.relative_to(root).as_posix(),
                "documented": documented_order is not None,
                "orchestrator": orchestrator,
                "selection_reason": selection_reason,
                "selection_score": self._node_script_score(
                    script,
                    script_command,
                    documented_order=documented_order,
                    orchestrator=orchestrator,
                ),
            }
            if environment:
                candidate["env"] = environment
            if port_adaptation is not None:
                candidate["port_adaptation"] = port_adaptation
            candidates.append(candidate)
        if not candidates:
            return None
        candidates.sort(
            key=lambda candidate: (
                -int(candidate["selection_score"]),
                int(documented_scripts.get(str(candidate["script"]), 1_000_000)),
                str(candidate["script"]),
            )
        )
        selected = dict(candidates[0])
        selected["candidate_scripts"] = [dict(candidate) for candidate in candidates]
        return selected

    def _documented_node_scripts(self, root: Path, package_root: Path) -> dict[str, int]:
        documented: dict[str, int] = {}
        paths: list[Path] = []
        for directory in dict.fromkeys((root, package_root)):
            for name in STARTUP_DOCUMENT_NAMES:
                path = directory / name
                if path.is_file() and path not in paths:
                    paths.append(path)
        order = 0
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in DOCUMENTED_NODE_COMMAND_RE.finditer(content):
                script = match.group("script")
                if script not in documented:
                    documented[script] = order
                    order += 1
        return documented

    def _referenced_script_paths(
        self,
        root: Path,
        package_root: Path,
        command: str,
    ) -> list[Path]:
        paths: list[Path] = []
        for match in SCRIPT_PATH_RE.finditer(command):
            candidate = (package_root / match.group("path")).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file() and candidate not in paths:
                paths.append(candidate)
        return paths

    def _script_uses_process_orchestrator(self, paths: list[Path]) -> bool:
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if ORCHESTRATOR_SOURCE_RE.search(content):
                return True
        return False

    def _runtime_environment_overrides(self, paths: list[Path]) -> dict[str, str]:
        port_variables: set[str] = set()
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in PORT_ENV_RE.finditer(content):
                variable = match.group("python") or match.group("node")
                if variable:
                    port_variables.add(variable)
        if not port_variables:
            return {}
        internal_qualifiers = (
            "ADMIN",
            "COLLECTOR",
            "DASHBOARD",
            "INTERNAL",
            "WORKER",
            "WECOM",
        )
        public_port = min(
            port_variables,
            key=lambda variable: (
                0 if variable == "PORT" else 1,
                1 if any(qualifier in variable for qualifier in internal_qualifiers) else 0,
                len(variable),
                variable,
            ),
        )
        return {public_port: "8000"}

    def _is_runtime_node_script(
        self,
        script: str,
        command: str,
        *,
        documented: bool,
        orchestrator: bool,
    ) -> bool:
        return (
            script in RUNTIME_SCRIPT_NAMES
            or script.startswith("start:")
            or (
                orchestrator
                and (documented or SERVER_COMMAND_RE.search(command) is not None)
            )
            or (documented and SERVER_COMMAND_RE.search(command) is not None)
        )

    def _node_script_score(
        self,
        script: str,
        command: str,
        *,
        documented_order: int | None,
        orchestrator: bool,
    ) -> int:
        score = 0
        if documented_order is not None:
            score += 100 - min(documented_order, 20)
        if orchestrator:
            score += 80
        preferred_scripts = {
            "dashboard",
            "dev:lan",
            "dev:local",
            "serve",
            "start:prod",
            "start:production",
        }
        if script in preferred_scripts:
            score += 30
        elif script == "start":
            score += 25
        elif script == "preview":
            score += 15
        elif script == "dev":
            score += 10
        if SERVER_COMMAND_RE.search(command) is not None:
            score += 20
        return score

    def _node_selection_reason(self, *, documented: bool, orchestrator: bool) -> str:
        if documented and orchestrator:
            return "documented_orchestrator"
        if documented:
            return "documented_command"
        if orchestrator:
            return "orchestrator"
        return "standard_script"

    def _load_context(
        self,
        target: str | Path,
        migration_id: str | None,
    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        root = self._resolve_existing_directory(target, "迁移目标")
        project = self._read_json(root / ".opscli" / "project.json", required=True) or {}
        if project.get("origin_type") != MIGRATION_ORIGIN_TYPE:
            raise AppProjectError("APP-MIGRATION-MARKER", "当前目录不是源码复制迁移项目。")
        migration_key = self._migration_id(migration_id or str(project.get("migration_id") or ""))
        migration_dir = self._migration_dir(root, migration_key)
        if any((migration_dir / name).exists() for name in LEGACY_STATE_FILES):
            raise AppProjectError(
                "APP-MIGRATION-LEGACY",
                "当前目录包含旧迁移重构状态，不能直接继续。",
                fix_hint="执行 opscli app migrate convert-legacy 后重新检查。",
            )
        state = self._read_json(migration_dir / "migration.json", required=True) or {}
        if state.get("migration_id") != migration_key:
            raise AppProjectError("APP-MIGRATION-STATE", "迁移状态中的 migration_id 不一致。")
        return root, state, project

    def _validate_roots(self, source: Path, target: Path) -> None:
        if source == target or source in target.parents or target in source.parents:
            raise AppProjectError("APP-MIGRATION-PATH", "源目录和目标目录不能相同或互相包含。")

    def _resolve_existing_directory(self, value: str | Path, label: str) -> Path:
        root = Path(value).expanduser().resolve()
        if not root.is_dir():
            raise AppProjectError("APP-MIGRATION-PATH", f"{label}不存在或不是目录：{root}")
        return root

    def _migration_id(self, value: str | None) -> str:
        migration_id = value or datetime.now().strftime("migration-%Y%m%d-%H%M%S")
        if not MIGRATION_ID_RE.fullmatch(migration_id):
            raise AppProjectError("APP-MIGRATION-STATE", "migration_id 格式错误。")
        return migration_id

    def _migration_dir(self, root: Path, migration_id: str) -> Path:
        return root / ".opscli" / "migration" / migration_id

    def _migration_result(
        self,
        root: Path,
        state: dict[str, Any],
        *,
        create: dict[str, Any] | None = None,
        init: dict[str, Any] | None = None,
        message: str,
    ) -> dict[str, Any]:
        return {
            **self.status(root, migration_id=state["migration_id"]),
            "target_reason": state.get("target_reason"),
            "target_notice": self._target_notice(root, state),
            "create": create,
            "init": init,
            "message": message,
        }

    def _target_notice(self, root: Path, state: dict[str, Any]) -> str | None:
        if state.get("target_reason") == "user_non_empty_fallback":
            return f"指定迁移目标目录非空，已在其下创建独立目标目录：{root}"
        return None

    def _record_generated_file(self, state: dict[str, Any], relative: str) -> None:
        generated = state.setdefault("generated_files", [])
        if relative not in generated:
            generated.append(relative)

    def _write_state(self, root: Path, migration_id: str, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        self._write_json(self._migration_dir(root, migration_id) / "migration.json", state)

    def _read_json(self, path: Path, *, required: bool) -> dict[str, Any] | None:
        if not path.is_file():
            if required:
                raise AppProjectError("APP-MIGRATION-NOT-FOUND", f"迁移状态文件不存在：{path}")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppProjectError("APP-MIGRATION-STATE", f"迁移状态文件无法读取：{path}") from exc
        if not isinstance(payload, dict):
            raise AppProjectError("APP-MIGRATION-STATE", f"迁移状态文件必须是 JSON 对象：{path}")
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)

    def _ensure_gitignore(self, root: Path) -> bool:
        target = root / ".gitignore"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        additions = [
            "",
            "# opscli migration local-only files",
            ".opscli/",
            ".openai/",
            ".codex-feedback-guard-state.json",
            ".env",
            ".env.*",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "/data/",
            "logs/",
        ]
        public_root = root / "public"
        if public_root.is_dir():
            for candidate in sorted(public_root.rglob("data")):
                if candidate.is_dir() and any(path.is_file() for path in candidate.rglob("*")):
                    relative = candidate.relative_to(root).as_posix()
                    additions.extend((f"!{relative}/", f"!{relative}/**"))
        missing = [line for line in additions[1:] if line not in existing.splitlines()]
        if missing:
            content = existing.rstrip() + "\n" + "\n".join(additions[:1] + missing) + "\n"
            self._write_text(target, content)
            return True
        return False

    def _ensure_dockerignore(self, root: Path) -> bool:
        """补齐迁移镜像上下文中的本地状态和依赖排除规则。"""
        target = root / ".dockerignore"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        additions = [
            "",
            "# opscli migration local-only files",
            ".git",
            ".opscli",
            ".env",
            ".env.*",
            ".venv",
            ".next",
            ".nuxt",
            ".sites-checkout",
            ".sites-runtime",
            ".vinext",
            ".wrangler",
            "dist",
            "node_modules",
            "__pycache__",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "/data/",
            "logs/",
        ]
        missing = [line for line in additions[1:] if line not in existing.splitlines()]
        if missing:
            content = existing.rstrip() + "\n" + "\n".join(additions[:1] + missing) + "\n"
            self._write_text(target, content)
            return True
        return False

    def _excluded_reason(self, relative: Path, source_path: Path) -> str | None:
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            return "runtime_or_dependency"
        if source_path.is_symlink():
            return "symlink_skipped"
        return None

    def _fingerprint_files(self, root: Path, relative_files: Any) -> str:
        if not isinstance(relative_files, list) or not all(
            isinstance(item, str) for item in relative_files
        ):
            return ""
        entries: list[str] = []
        for relative in sorted(Path(item) for item in relative_files):
            path = root / relative
            if not path.is_file() or path.is_symlink():
                return ""
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append(f"{relative.as_posix()}|{digest}")
        return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()

    def _copied_files_match(
        self,
        root: Path,
        copy_manifest: dict[str, Any],
        managed_files: Any,
    ) -> bool:
        hashes = copy_manifest.get("file_hashes")
        included = copy_manifest.get("included_files")
        if not isinstance(hashes, dict) or not isinstance(included, list):
            return False
        managed = set(managed_files) if isinstance(managed_files, list) else set()
        for relative in included:
            if not isinstance(relative, str) or relative in managed:
                continue
            path = root / relative
            if not path.is_file() or path.is_symlink():
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashes.get(relative):
                return False
        return True

    def _assert_source_unchanged(self, source: Path, fingerprint: str) -> None:
        if not source.is_dir():
            raise AppProjectError("APP-MIGRATION-SOURCE-CHANGED", "复制完成后源项目不存在，请重试。")
        _, files, _ = self._source_inventory(source)
        included = [path.as_posix() for path in files]
        if self._fingerprint_files(source, included) != fingerprint:
            raise AppProjectError("APP-MIGRATION-SOURCE-CHANGED", "复制完成后源项目发生变化，请重试。")

    def _ensure_app_manifest(self, root: Path, *, app_id: str, title: str) -> bool:
        target = root / "app.yaml"
        if target.exists():
            return False
        self._write_text(
            target,
            "apiVersion: apps.aukeys/v1\n"
            f"app_id: {json.dumps(app_id, ensure_ascii=False)}\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n",
        )
        return True

    def _manifest_matches(self, root: Path, app_id: Any) -> bool:
        if not isinstance(app_id, str) or not app_id:
            return False
        target = root / "app.yaml"
        if not target.is_file():
            return False
        try:
            payload = yaml.safe_load(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("apiVersion") == "apps.aukeys/v1"
            and payload.get("app_id") == app_id
            and "name" not in payload
        )

    def _is_sensitive(self, path: Path) -> bool:
        return (
            path.name == ".env"
            or path.name.startswith(".env.")
            or path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
            or "data" in path.parts
        )


def _startup_wrapper(manifest: dict[str, Any]) -> str:
    runtime = manifest.get("runtime")
    launch_mode = manifest.get("launch_mode")
    if launch_mode == "dual":
        commands = [
            item for item in (manifest.get("backend"), manifest.get("frontend")) if item
        ]
    elif isinstance(runtime, dict):
        commands = [runtime]
    else:
        commands = [
            item for item in (manifest.get("backend"), manifest.get("frontend")) if item
        ]
    serialized = json.dumps(commands, ensure_ascii=False, indent=2)
    return f'''"""Generated by opscli app migrate; calls the migrated project's detected commands."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {serialized}
PROCESSES: list[subprocess.Popen] = []


def stop_processes(*_args: object) -> None:
    for process in PROCESSES:
        if process.poll() is None:
            process.terminate()
    for process in PROCESSES:
        if process.poll() is None:
            process.wait(timeout=10)


def main() -> int:
    if not COMMANDS:
        print("无法确认前后端启动命令，请查看 .opscli/migration/startup-manifest.json。", file=sys.stderr)
        return 2
    signal.signal(signal.SIGINT, stop_processes)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_processes)
    try:
        for item in COMMANDS:
            cwd = ROOT / item.get("cwd", ".")
            environment = os.environ.copy()
            environment.update(
                {{str(key): str(value) for key, value in item.get("env", {{}}).items()}}
            )
            PROCESSES.append(subprocess.Popen(item["command"], cwd=cwd, env=environment))
        while PROCESSES:
            for process in PROCESSES:
                exit_code = process.poll()
                if exit_code is not None:
                    return exit_code
            time.sleep(0.25)
        return 0
    finally:
        stop_processes()


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _error_payload(error: Exception) -> dict[str, Any]:
    if hasattr(error, "to_dict"):
        return error.to_dict()  # type: ignore[no-any-return]
    return {"code": "UNKNOWN", "message": str(error), "type": type(error).__name__}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
