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

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.manager import AppManager

MIGRATION_SCHEMA_VERSION = 1
MIGRATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MIGRATION_ORIGIN_TYPE = "migration_copy"
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
    "build",
    ".next",
    ".nuxt",
    ".cache",
    "tmp",
    "temp",
    "logs",
}
SENSITIVE_GIT_PATTERNS = (".env", ".env.*", "*.db", "*.sqlite", "*.sqlite3", "data")
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
        target_path, target_reason = self._resolve_target(source_path, target_root)
        self._validate_roots(source_path, target_path)
        if target_path.exists():
            raise AppProjectError("APP-MIGRATION-TARGET", f"迁移目标已存在：{target_path}")

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
            "phase": "target_resolved",
            "status": "running",
            "created_at": _now(),
            "updated_at": _now(),
        }
        try:
            copy_manifest = self._copy_source(source_path, staging, migration_key)
            self._write_json(staging / ".opscli" / "migration" / migration_key / "copy-manifest.json", copy_manifest)
            self._write_json(staging / ".opscli" / "migration" / migration_key / "migration.json", state)
            self._write_json(staging / ".opscli" / "migration" / "current.json", {
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "migration_id": migration_key,
            })
            self._write_json(staging / ".opscli" / "project.json", {
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "project_type": "apphub",
                "origin_type": MIGRATION_ORIGIN_TYPE,
                "migration_id": migration_key,
                "source_root": str(source_path),
                "target_root": str(target_path),
                "source_readonly": True,
                "template_cloned": False,
                "business_source_rewritten": False,
            })
            self._ensure_gitignore(staging)
            startup = self._scan_and_write_startup(staging, migration_key)
            state.update(
                phase="startup_ready" if startup["status"] == "ready" else "startup_manual_required",
                startup_status=startup["status"],
                updated_at=_now(),
            )
            self._write_json(staging / ".opscli" / "migration" / migration_key / "migration.json", state)
            staging.rename(target_path)
            self._assert_source_unchanged(source_path, copy_manifest["source_fingerprint"])

            manager = self._get_manager()
            resolved_name = app_name.strip() if app_name and app_name.strip() else source_path.name
            create_result = manager.create_app(
                resolved_name,
                path=target_path,
                origin_type=MIGRATION_ORIGIN_TYPE,
                migration_id=migration_key,
            )
            state.update(phase="registered", app_id=create_result.get("app_id"), updated_at=_now())
            self._write_state(target_path, migration_key, state)
            init_result = manager.init_git(target_path)
            state.update(phase="initialized", status="ready", updated_at=_now())
            self._write_state(target_path, migration_key, state)
            target_notice = None
            if target_reason == "user_non_empty_fallback":
                target_notice = (
                    f"指定迁移目标目录非空，已在其下创建独立目标目录：{target_path}"
                )
            return {
                **self.status(target_path, migration_id=migration_key),
                "target_reason": target_reason,
                "target_notice": target_notice,
                "copy_manifest": str(self._migration_dir(target_path, migration_key) / "copy-manifest.json"),
                "startup_manifest": str(self._migration_dir(target_path, migration_key) / "startup-manifest.json"),
                "create": create_result,
                "init": init_result,
                "message": "源码迁移、AppHub 创建和 Git 初始化已完成。",
            }
        except Exception as exc:
            state.update(status="failed", phase="failed", error=_error_payload(exc), updated_at=_now())
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            elif target_path.exists():
                self._write_state(target_path, migration_key, state)
            raise

    def status(self, target: str | Path = ".", *, migration_id: str | None = None) -> dict[str, Any]:
        root, state, project = self._load_context(target, migration_id)
        migration_key = state["migration_id"]
        migration_dir = self._migration_dir(root, migration_key)
        startup = self._read_json(migration_dir / "startup-manifest.json", required=False) or {}
        copy_manifest = self._read_json(migration_dir / "copy-manifest.json", required=False) or {}
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "origin_type": project.get("origin_type"),
            "source_root": state.get("source_root"),
            "target_root": str(root),
            "phase": state.get("phase"),
            "status": state.get("status"),
            "startup_status": startup.get("status") or state.get("startup_status"),
            "app_id": state.get("app_id"),
            "copy_manifest": str(migration_dir / "copy-manifest.json"),
            "startup_manifest": str(migration_dir / "startup-manifest.json"),
            "copied_file_count": copy_manifest.get("included_file_count", 0),
            "excluded_file_count": copy_manifest.get("excluded_file_count", 0),
            "state_path": str(migration_dir / "migration.json"),
        }

    def scan_startup(self, target: str | Path = ".", *, migration_id: str | None = None) -> dict[str, Any]:
        root, state, _ = self._load_context(target, migration_id)
        startup = self._scan_and_write_startup(root, state["migration_id"])
        state.update(
            phase="startup_ready" if startup["status"] == "ready" else "startup_manual_required",
            startup_status=startup["status"],
            updated_at=_now(),
        )
        self._write_state(root, state["migration_id"], state)
        return {**self.status(root, migration_id=state["migration_id"]), "startup": startup}

    def verify(self, target: str | Path = ".", *, migration_id: str | None = None) -> dict[str, Any]:
        root, state, project = self._load_context(target, migration_id)
        migration_key = state["migration_id"]
        migration_dir = self._migration_dir(root, migration_key)
        copy_manifest = self._read_json(migration_dir / "copy-manifest.json", required=True) or {}
        startup_manifest = self._read_json(migration_dir / "startup-manifest.json", required=True) or {}
        source = Path(str(project.get("source_root") or "")).expanduser().resolve()
        checks = {
            "source_exists": source.is_dir(),
            "source_unchanged": source.is_dir() and self._fingerprint(source) == copy_manifest.get("source_fingerprint"),
            "target_independent": source != root and source not in root.parents and root not in source.parents,
            "migration_marker": project.get("origin_type") == MIGRATION_ORIGIN_TYPE,
            "copy_verified": self._fingerprint_files(
                root,
                copy_manifest.get("included_files"),
            ) == copy_manifest.get("target_fingerprint"),
            "startup_manifest": bool(startup_manifest),
            "git_initialized": (root / ".git").exists(),
            "app_binding": (root / ".opscli" / "app.json").is_file(),
        }
        passed = all(checks.values())
        state.update(phase="push_ready" if passed else state.get("phase"), status="ready" if passed else "blocked", updated_at=_now())
        self._write_state(root, migration_key, state)
        return {**self.status(root, migration_id=migration_key), "passed": passed, "checks": checks}

    def convert_legacy(self, target: str | Path = ".", *, migration_id: str | None = None) -> dict[str, Any]:
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
        backup = root / ".opscli" / "migration-legacy" / f"{migration_key}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_dir), str(backup))
        self._write_json(current_path, {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_key,
            "status": "legacy_converted",
            "legacy_backup": str(backup),
        })
        return {"migration_id": migration_key, "status": "legacy_converted", "legacy_backup": str(backup)}

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
        before = self._fingerprint(source)
        included: list[str] = []
        excluded: list[dict[str, str]] = []
        staging.mkdir(parents=True, exist_ok=False)
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            reason = self._excluded_reason(relative, path)
            if reason:
                excluded.append({"path": relative.as_posix(), "reason": reason})
                continue
            destination = staging / relative
            if path.is_symlink():
                excluded.append({"path": relative.as_posix(), "reason": "symlink_skipped"})
                continue
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                included.append(relative.as_posix())
        after = self._fingerprint(source)
        if before != after:
            raise AppProjectError("APP-MIGRATION-SOURCE-CHANGED", "复制过程中源项目发生变化，请重试。")
        target_fingerprint = self._fingerprint(staging)
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "migration_id": migration_id,
            "source_root": str(source),
            "included_file_count": len(included),
            "included_files": sorted(included),
            "excluded_file_count": len(excluded),
            "excluded_files": excluded,
            "sensitive_files": [item for item in included if self._is_sensitive(Path(item))],
            "source_fingerprint": before,
            "target_fingerprint": target_fingerprint,
            "created_at": _now(),
        }

    def _scan_and_write_startup(self, root: Path, migration_id: str) -> dict[str, Any]:
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
        self._write_json(self._migration_dir(root, migration_id) / "startup-manifest.json", manifest)
        wrapper = root / "scripts" / "start_app.py"
        if not wrapper.exists():
            self._write_text(wrapper, _startup_wrapper(manifest))
            manifest["wrapper_generated"] = True
        else:
            manifest["wrapper_generated"] = False
        self._write_json(self._migration_dir(root, migration_id) / "startup-manifest.json", manifest)
        return manifest

    def _detect_backend(self, root: Path) -> dict[str, Any] | None:
        candidates = (root / "backend" / "app.py", root / "backend" / "main.py", root / "app.py", root / "main.py")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root).with_suffix("")
            module = ".".join(relative.parts)
            content = candidate.read_text(encoding="utf-8", errors="replace")
            if "FastAPI" in content or "uvicorn" in content or "Starlette" in content:
                return {"command": ["python", "-m", "uvicorn", f"{module}:app"], "cwd": ".", "evidence": str(candidate.relative_to(root))}
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
        script = next((name for name in ("start", "dev", "preview") if name in scripts), None)
        if script is None:
            return None
        frontend_root = package_path.parent
        manager = "pnpm" if (frontend_root / "pnpm-lock.yaml").exists() else "yarn" if (frontend_root / "yarn.lock").exists() else "npm"
        command = [manager, "run", script] if manager != "yarn" else [manager, script]
        return {"command": command, "cwd": str(frontend_root.relative_to(root)), "script": script, "evidence": str(package_path.relative_to(root))}

    def _load_context(self, target: str | Path, migration_id: str | None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
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

    def _ensure_gitignore(self, root: Path) -> None:
        target = root / ".gitignore"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        additions = ["", "# opscli migration local-only files", ".env", ".env.*", "*.db", "*.sqlite", "*.sqlite3", "data/", "logs/"]
        missing = [line for line in additions[1:] if line not in existing.splitlines()]
        if missing:
            self._write_text(target, existing.rstrip() + "\n" + "\n".join(additions[:1] + missing) + "\n")

    def _excluded_reason(self, relative: Path, source_path: Path) -> str | None:
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            return "runtime_or_dependency"
        if source_path.is_symlink():
            return "symlink_skipped"
        return None

    def _fingerprint(self, root: Path) -> str:
        entries: list[str] = []
        if not root.exists():
            return ""
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if self._excluded_reason(relative, path):
                continue
            if path.is_file() and not path.is_symlink():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append(f"{relative.as_posix()}|{digest}")
        return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()

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

    def _assert_source_unchanged(self, source: Path, fingerprint: str) -> None:
        if self._fingerprint(source) != fingerprint:
            raise AppProjectError("APP-MIGRATION-SOURCE-CHANGED", "复制完成后源项目发生变化，请重试。")

    def _is_sensitive(self, path: Path) -> bool:
        return path.name == ".env" or path.name.startswith(".env.") or path.suffix.lower() in {".db", ".sqlite", ".sqlite3"} or "data" in path.parts


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
