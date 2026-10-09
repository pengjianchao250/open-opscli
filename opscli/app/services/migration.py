"""AppHub 项目的源码复制迁移服务。"""

from __future__ import annotations

import hashlib
import json
import os
import re
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
    inspect_migration_runtime_assets,
)

MIGRATION_SCHEMA_VERSION = 2
MIGRATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MIGRATION_ORIGIN_TYPE = "migration_copy"
FINALIZE_JOURNAL_NAME = ".opscli-migration-finalize.json"
EXCLUDED_PARTS = {
    ".git",
    ".opscli",
    ".venv",
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
        backend = self._detect_backend(root)
        frontend = self._detect_frontend(root)
        status = "ready" if backend and frontend else "startup_manual_required"
        manifest = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_id,
            "status": status,
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

    def _scan_and_write_adaptation(
        self,
        root: Path,
        state: dict[str, Any],
        startup: dict[str, Any],
    ) -> dict[str, Any]:
        app_id = state.get("app_id")
        frontend_build = inspect_migration_frontend_build(root)
        public_paths = inspect_migration_public_paths(root)
        runtime_assets = inspect_migration_runtime_assets(root)
        checks = {
            "startup_ready": startup.get("status") == "ready",
            "gitignore_present": (root / ".gitignore").is_file(),
            "start_wrapper_present": (root / "scripts" / "start_app.py").is_file(),
            "backend_entry_present": (root / "backend" / "app.py").is_file(),
            "frontend_manifest_present": (root / "frontend" / "package.json").is_file(),
            "dockerfile_present": (root / "Dockerfile").is_file(),
            "nixpacks_present": (root / "nixpacks.toml").is_file(),
            "frontend_build_contract": frontend_build["ready"],
            "public_path_contract": public_paths["ready"],
            "runtime_asset_contract": runtime_assets["ready"],
            "app_manifest_identity": self._manifest_matches(root, app_id),
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
            "frontend_build": frontend_build,
            "public_paths": public_paths,
            "runtime_assets": runtime_assets,
            "managed_files": sorted(set(state.get("generated_files") or [])),
            "generated_or_modified_files": sorted(set(state.get("generated_files") or [])),
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
                    "command": ["python", "-m", "uvicorn", f"{module}:app"],
                    "cwd": ".",
                    "evidence": str(candidate.relative_to(root)),
                }
        return None

    def _detect_frontend(self, root: Path) -> dict[str, Any] | None:
        package_path = root / "frontend" / "package.json"
        if not package_path.is_file():
            package_path = root / "package.json"
        if not package_path.is_file():
            return None
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if not isinstance(scripts, dict):
            return None
        script = next(
            (
                name
                for name in ("start", "preview", "dev")
                if isinstance(scripts.get(name), str) and scripts[name].strip()
            ),
            None,
        )
        if script is None:
            return None
        frontend_root = package_path.parent
        if (frontend_root / "pnpm-lock.yaml").exists():
            manager = "pnpm"
        elif (frontend_root / "yarn.lock").exists():
            manager = "yarn"
        else:
            manager = "npm"
        command = [manager, "run", script] if manager != "yarn" else [manager, script]
        return {
            "command": command,
            "cwd": str(frontend_root.relative_to(root)),
            "script": script,
            "script_command": scripts[script],
            "evidence": str(package_path.relative_to(root)),
        }

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
    commands = [item for item in (manifest.get("backend"), manifest.get("frontend")) if item]
    serialized = json.dumps(commands, ensure_ascii=False, indent=2)
    return f'''"""Generated by opscli app migrate; calls the migrated project's detected commands."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
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
            PROCESSES.append(subprocess.Popen(item["command"], cwd=cwd, env=os.environ.copy()))
        return next((process.wait() for process in PROCESSES), 0)
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
