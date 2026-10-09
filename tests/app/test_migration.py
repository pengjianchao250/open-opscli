"""源码复制迁移流程测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.migration import MigrationService


class FakeAppManager:
    def __init__(self, *, fail_init_once: bool = False) -> None:
        self.create_calls: list[dict] = []
        self.init_calls: list[Path] = []
        self.fail_init_once = fail_init_once

    def create_app(
        self,
        app_name: str,
        *,
        path: Path,
        include_default_database: bool = True,
    ) -> dict:
        self.create_calls.append(
            {
                "app_name": app_name,
                "path": path,
                "include_default_database": include_default_database,
            }
        )
        binding = path / ".opscli" / "app.json"
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text("{}", encoding="utf-8")
        return {"app_id": "Ab123", "app_name": app_name, "path": str(path)}

    def init_git(self, path: Path) -> dict:
        self.init_calls.append(path)
        if self.fail_init_once:
            self.fail_init_once = False
            raise AppProjectError("GIT-TEST", "模拟 Git 初始化中断")
        (path / ".git").mkdir()
        return {"git_created": True}

    def close(self) -> None:
        return None


def _source(root: Path, *, runnable: bool = True) -> Path:
    source = root / "source"
    (source / ".git").mkdir(parents=True)
    (source / ".opscli").mkdir()
    (source / "node_modules" / "pkg").mkdir(parents=True)
    (source / ".venv").mkdir()
    (source / "build").mkdir()
    (source / "build" / "sites-vite-plugin.ts").write_text(
        "export const sites = () => ({ name: 'sites' });\n",
        encoding="utf-8",
    )
    (source / "dist").mkdir()
    (source / "dist" / "bundle.js").write_text("generated", encoding="utf-8")
    (source / "data").mkdir()
    (source / "data" / "seed.db").write_text("seed", encoding="utf-8")
    (source / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (source / "README.md").write_text("project", encoding="utf-8")
    (source / ".opscli" / "app.json").write_text("old", encoding="utf-8")
    if runnable:
        (source / "backend").mkdir()
        (source / "backend" / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        (source / "frontend").mkdir()
        (source / "frontend" / "package.json").write_text(
            json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8"
        )
        (source / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
        (source / "nixpacks.toml").write_text("[start]\n", encoding="utf-8")
    return source


def test_start_copies_source_and_runs_create_and_init(tmp_path: Path) -> None:
    source = _source(tmp_path)
    before = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source,
        tmp_path / "dest",
        app_name="项目十部-v31",
        migration_id="migration-demo",
    )

    target = tmp_path / "dest"
    after = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))
    assert before == after
    assert (target / "README.md").read_text(encoding="utf-8") == "project"
    assert (target / ".env").is_file()
    assert (target / "data" / "seed.db").is_file()
    assert not (target / ".git" / "config").exists()
    assert not (target / "node_modules").exists()
    assert not (target / ".venv").exists()
    assert not (target / ".opscli" / "app.json").read_text(encoding="utf-8") == "old"
    assert manager.create_calls[0]["include_default_database"] is False
    assert manager.init_calls == [target]
    assert result["phase"] == "push_ready"
    assert result["startup_status"] == "ready"
    assert result["adaptation_status"] == "ready"
    assert result["delivery_ready"] is True
    gitignore = (target / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/data/" in gitignore
    assert "data/" not in gitignore
    project = json.loads((target / ".opscli" / "project.json").read_text(encoding="utf-8"))
    assert project["origin_type"] == "migration_copy"
    assert project["migration_id"] == "migration-demo"
    assert (target / ".opscli" / "migration" / "migration-demo" / "adaptation-manifest.json").is_file()
    assert "app_id: \"Ab123\"" in (target / "app.yaml").read_text(encoding="utf-8")


def test_non_empty_requested_target_uses_timestamp_child(tmp_path: Path) -> None:
    source = _source(tmp_path, runnable=False)
    requested = tmp_path / "existing"
    requested.mkdir()
    (requested / "keep.txt").write_text("keep", encoding="utf-8")

    result = MigrationService(app_manager=FakeAppManager()).start(source, requested)

    target = Path(result["target_root"])
    assert target.parent == requested
    assert target.name.startswith("app-hub-source-")
    assert "指定迁移目标目录非空" in result["target_notice"]
    assert (requested / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert result["startup_status"] == "startup_manual_required"
    assert result["adaptation_status"] == "adaptation_manual_required"
    assert result["delivery_ready"] is False


def test_existing_empty_target_is_used_directly(tmp_path: Path) -> None:
    source = _source(tmp_path)
    target = tmp_path / "empty-target"
    target.mkdir()

    result = MigrationService(app_manager=FakeAppManager()).start(source, target)

    assert Path(result["target_root"]) == target
    assert (target / "README.md").is_file()
    assert result["target_reason"] == "user_requested"


def test_existing_empty_target_can_be_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "empty-target"
    target.mkdir()
    monkeypatch.chdir(target)

    result = MigrationService(app_manager=FakeAppManager()).start(
        source,
        target,
        migration_id="migration-cwd",
    )

    assert Path.cwd() == target
    assert Path(result["target_root"]) == target
    assert (target / "README.md").is_file()
    assert not (target / ".opscli-migration-finalize.json").exists()


def test_existing_empty_target_rolls_back_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "empty-target"
    target.mkdir()
    original_replace = Path.replace

    def fail_dockerfile_commit(path: Path, destination: Path) -> Path:
        if path.name == "Dockerfile" and path.parent.name.endswith(
            ".migration-migration-rollback.tmp"
        ):
            raise PermissionError(32, "file is in use", str(path))
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_dockerfile_commit)

    with pytest.raises(AppProjectError) as caught:
        MigrationService(app_manager=FakeAppManager()).start(
            source,
            target,
            migration_id="migration-rollback",
        )

    assert caught.value.code == "APP-MIGRATION-FINALIZE"
    assert caught.value.detail["rollback_completed"] is True
    assert not any(target.iterdir())


def test_start_recovers_commit_interrupted_before_exception_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "empty-target"
    target.mkdir()
    original_replace = Path.replace

    def interrupt_dockerfile_commit(path: Path, destination: Path) -> Path:
        if path.name == "Dockerfile" and path.parent.name.endswith(
            ".migration-migration-interrupted.tmp"
        ):
            raise KeyboardInterrupt()
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", interrupt_dockerfile_commit)
    with pytest.raises(KeyboardInterrupt):
        MigrationService(app_manager=FakeAppManager()).start(
            source,
            target,
            migration_id="migration-interrupted",
        )

    assert (target / ".opscli-migration-finalize.json").is_file()
    monkeypatch.setattr(Path, "replace", original_replace)

    result = MigrationService(app_manager=FakeAppManager()).start(
        source,
        target,
        migration_id="migration-recovered",
    )

    assert result["delivery_ready"] is True
    assert (target / "README.md").is_file()
    assert not (target / ".opscli-migration-finalize.json").exists()


def test_copy_prunes_excluded_directories_before_reading_children(tmp_path: Path) -> None:
    source = _source(tmp_path)
    protected = source / "node_modules" / "pkg" / "unreadable.js"
    protected.write_text("ignored", encoding="utf-8")
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source,
        tmp_path / "target",
        migration_id="migration-pruned",
    )

    manifest = json.loads(Path(result["copy_manifest"]).read_text(encoding="utf-8"))
    target = Path(result["target_root"])
    excluded_paths = {item["path"] for item in manifest["excluded_files"]}
    assert (target / "build" / "sites-vite-plugin.ts").is_file()
    assert "build/sites-vite-plugin.ts" in manifest["included_files"]
    assert "build" not in excluded_paths
    assert not (target / "node_modules").exists()
    assert not (target / "dist").exists()
    assert excluded_paths >= {
        ".git",
        ".opscli",
        ".venv",
        "dist",
        "node_modules",
    }
    assert all(not item["path"].startswith("node_modules/") for item in manifest["excluded_files"])


def test_default_target_is_created_under_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path, runnable=False)
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    result = MigrationService(app_manager=FakeAppManager()).start(source)

    target = Path(result["target_root"])
    assert target.parent == workdir
    assert target.name.startswith("app-hub-source-")
    assert result["delivery_ready"] is False


@pytest.mark.parametrize("relation", ["same", "target-parent"])
def test_start_rejects_same_or_nested_paths(tmp_path: Path, relation: str) -> None:
    source = _source(tmp_path, runnable=False)
    if relation == "same":
        target = source
    else:
        target = source / "target"

    with pytest.raises(AppProjectError) as caught:
        MigrationService(app_manager=FakeAppManager()).start(source, target)

    assert caught.value.code == "APP-MIGRATION-PATH"


def test_verify_reports_source_and_target_contract(tmp_path: Path) -> None:
    source = _source(tmp_path)
    manager = FakeAppManager()
    service = MigrationService(app_manager=manager)
    result = service.start(source, tmp_path / "target", migration_id="migration-demo")

    verified = service.verify(result["target_root"], migration_id="migration-demo")

    assert verified["passed"] is True
    assert verified["checks"]["source_unchanged"] is True
    assert verified["checks"]["app_binding"] is True
    assert verified["checks"]["copy_verified"] is True


def test_verify_allows_target_maintenance_after_copy_baseline_passes(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    service = MigrationService(app_manager=FakeAppManager())
    result = service.start(source, tmp_path / "target", migration_id="migration-maintenance")
    target = Path(result["target_root"])

    (target / "README.md").write_text("maintained project", encoding="utf-8")
    verified = service.verify(target, migration_id="migration-maintenance")

    assert verified["passed"] is True
    assert verified["checks"]["copy_verified"] is True
    assert verified["checks"]["source_unchanged"] is True


def test_resume_rejects_copy_drift_before_copy_baseline_passes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    manager = FakeAppManager(fail_init_once=True)
    service = MigrationService(app_manager=manager)

    with pytest.raises(AppProjectError):
        service.start(
            source,
            tmp_path / "target",
            migration_id="migration-pre-delivery-drift",
        )

    target = tmp_path / "target"
    (target / "README.md").write_text("unexpected drift", encoding="utf-8")
    resumed = service.resume(target, migration_id="migration-pre-delivery-drift")

    assert resumed["delivery_ready"] is False
    assert resumed["checks"]["copy_verified"] is False


def test_resume_after_init_failure_does_not_recopy_or_recreate(tmp_path: Path) -> None:
    source = _source(tmp_path)
    manager = FakeAppManager(fail_init_once=True)
    service = MigrationService(app_manager=manager)

    with pytest.raises(AppProjectError):
        service.start(source, tmp_path / "target", migration_id="migration-resume")

    target = tmp_path / "target"
    copy_manifest = target / ".opscli" / "migration" / "migration-resume" / "copy-manifest.json"
    before = copy_manifest.read_bytes()
    resumed = service.resume(target, migration_id="migration-resume")

    assert resumed["delivery_ready"] is True
    assert copy_manifest.read_bytes() == before
    assert len(manager.create_calls) == 1
    assert manager.init_calls == [target, target]


def test_manual_runtime_can_be_completed_then_resumed(tmp_path: Path) -> None:
    source = _source(tmp_path, runnable=False)
    manager = FakeAppManager()
    service = MigrationService(app_manager=manager)
    started = service.start(source, tmp_path / "target", migration_id="migration-manual")

    target = Path(started["target_root"])
    assert manager.create_calls == []
    assert manager.init_calls == []
    (target / "backend").mkdir()
    (target / "backend" / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (target / "frontend").mkdir()
    (target / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build", "dev": "vite"}}),
        encoding="utf-8",
    )
    (target / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (target / "nixpacks.toml").write_text("[start]\n", encoding="utf-8")

    resumed = service.resume(target, migration_id="migration-manual")

    assert resumed["delivery_ready"] is True
    assert len(manager.create_calls) == 1
    assert manager.init_calls == [target]


def test_missing_production_assets_requires_manual_adaptation(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "Dockerfile").unlink()
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source, tmp_path / "target", migration_id="migration-adapter"
    )

    assert result["startup_status"] == "ready"
    assert result["adaptation_status"] == "adaptation_manual_required"
    assert result["delivery_ready"] is False
    assert manager.create_calls == []
    assert manager.init_calls == []


def test_root_relative_browser_urls_require_manual_adaptation(tmp_path: Path) -> None:
    source = _source(tmp_path)
    web = source / "web"
    web.mkdir()
    (web / "index.html").write_text(
        '<link rel="stylesheet" href="/styles.css"><script src="/app.js"></script>',
        encoding="utf-8",
    )
    (web / "app.js").write_text('fetch("/api/report")', encoding="utf-8")
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source, tmp_path / "target", migration_id="migration-public-path"
    )
    adaptation = json.loads(
        (
            tmp_path
            / "target"
            / ".opscli"
            / "migration"
            / "migration-public-path"
            / "adaptation-manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert result["adaptation_status"] == "adaptation_manual_required"
    assert result["delivery_ready"] is False
    assert adaptation["checks"]["public_path_contract"] is False
    assert adaptation["public_paths"]["reason"] == "root_relative_public_url"
    assert {item["file"] for item in adaptation["public_paths"]["detail"]["violations"]} == {
        "web/app.js",
        "web/index.html",
    }
    assert manager.create_calls == []
    assert manager.init_calls == []


def test_relative_browser_urls_pass_migration_public_path_contract(tmp_path: Path) -> None:
    source = _source(tmp_path)
    web = source / "web"
    web.mkdir()
    (web / "index.html").write_text(
        '<link rel="stylesheet" href="./styles.css"><script src="./app.js"></script>',
        encoding="utf-8",
    )
    (web / "app.js").write_text('fetch("./api/report")', encoding="utf-8")

    result = MigrationService(app_manager=FakeAppManager()).start(
        source, tmp_path / "target", migration_id="migration-relative-path"
    )

    assert result["delivery_ready"] is True
    assert result["checks"]["public_path_contract"] is True
    assert result["public_paths"]["reason"] == "ready"


def test_runtime_snapshot_missing_from_final_image_requires_manual_adaptation(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    snapshot = source / "public" / "dashboard" / "data"
    snapshot.mkdir(parents=True)
    (snapshot / "report.json").write_text('{"status":"ready"}', encoding="utf-8")
    scripts = source / "scripts"
    scripts.mkdir()
    (scripts / "server.py").write_text(
        'STATIC_DATA_ROOT = PROJECT_ROOT / "public" / "dashboard" / "data"\n',
        encoding="utf-8",
    )
    (source / ".dockerignore").write_text("/data/\n", encoding="utf-8")
    (source / "Dockerfile").write_text(
        "FROM node:22-alpine AS frontend-build\n"
        "COPY public ./public\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY scripts ./scripts\n",
        encoding="utf-8",
    )
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source, tmp_path / "target", migration_id="migration-runtime-snapshot"
    )
    adaptation = json.loads(
        (
            tmp_path
            / "target"
            / ".opscli"
            / "migration"
            / "migration-runtime-snapshot"
            / "adaptation-manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert result["adaptation_status"] == "adaptation_manual_required"
    assert result["delivery_ready"] is False
    assert adaptation["checks"]["runtime_asset_contract"] is False
    assert adaptation["runtime_assets"]["reason"] == "runtime_snapshot_not_packaged"
    assert adaptation["runtime_assets"]["detail"]["violations"] == [
        {
            "file": "Dockerfile",
            "kind": "runtime_public_not_copied",
            "value": "public",
        }
    ]
    assert manager.create_calls == []
    assert manager.init_calls == []


def test_runtime_snapshot_is_tracked_and_copied_to_final_image(tmp_path: Path) -> None:
    source = _source(tmp_path)
    snapshot = source / "public" / "dashboard" / "data"
    snapshot.mkdir(parents=True)
    (snapshot / "report.json").write_text('{"status":"ready"}', encoding="utf-8")
    scripts = source / "scripts"
    scripts.mkdir()
    (scripts / "server.py").write_text(
        'STATIC_DATA_ROOT = PROJECT_ROOT / "public" / "dashboard" / "data"\n',
        encoding="utf-8",
    )
    (source / ".gitignore").write_text("data/\n", encoding="utf-8")
    (source / ".dockerignore").write_text("/data/\n", encoding="utf-8")
    (source / "Dockerfile").write_text(
        "FROM node:22-alpine AS frontend-build\n"
        "COPY public ./public\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY public ./public\n"
        "COPY scripts ./scripts\n",
        encoding="utf-8",
    )

    result = MigrationService(app_manager=FakeAppManager()).start(
        source, tmp_path / "target", migration_id="migration-runtime-ready"
    )
    target = tmp_path / "target"
    gitignore = (target / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert result["delivery_ready"] is True
    assert result["checks"]["runtime_asset_contract"] is True
    assert result["runtime_assets"]["reason"] == "ready"
    assert "!public/dashboard/data/" in gitignore
    assert "!public/dashboard/data/**" in gitignore


def test_corepack_parent_directory_mismatch_requires_manual_adaptation(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    (source / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "pnpm@10.15.0",
                "scripts": {"build": "node src/build.mjs", "dev": "vite"},
            }
        ),
        encoding="utf-8",
    )
    (source / "Dockerfile").write_text(
        "FROM node:22-alpine AS frontend-build\n"
        "WORKDIR /app\n"
        "RUN corepack enable\n"
        "COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/\n"
        "RUN pnpm --dir frontend install --frozen-lockfile && pnpm --dir frontend build\n",
        encoding="utf-8",
    )
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source, tmp_path / "target", migration_id="migration-corepack-mismatch"
    )
    adaptation = json.loads(
        (
            tmp_path
            / "target"
            / ".opscli"
            / "migration"
            / "migration-corepack-mismatch"
            / "adaptation-manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert result["adaptation_status"] == "adaptation_manual_required"
    assert result["delivery_ready"] is False
    assert adaptation["checks"]["frontend_build_contract"] is False
    assert adaptation["frontend_build"]["reason"] == "corepack_context_mismatch"
    assert manager.create_calls == []
    assert manager.init_calls == []


def test_corepack_runs_from_frontend_manifest_directory(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "pnpm@10.15.0",
                "scripts": {"build": "node src/build.mjs", "dev": "vite"},
            }
        ),
        encoding="utf-8",
    )
    (source / "Dockerfile").write_text(
        "FROM node:22-alpine AS frontend-build\n"
        "WORKDIR /app/frontend\n"
        "RUN corepack enable\n"
        "COPY frontend/package.json frontend/pnpm-lock.yaml ./\n"
        "RUN pnpm install --frozen-lockfile && pnpm build\n",
        encoding="utf-8",
    )
    manager = FakeAppManager()

    result = MigrationService(app_manager=manager).start(
        source, tmp_path / "target", migration_id="migration-corepack-ready"
    )
    adaptation = json.loads(
        (
            tmp_path
            / "target"
            / ".opscli"
            / "migration"
            / "migration-corepack-ready"
            / "adaptation-manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert result["adaptation_status"] == "ready"
    assert result["delivery_ready"] is True
    assert adaptation["checks"]["frontend_build_contract"] is True
    assert adaptation["frontend_build"]["reason"] == "ready"
    assert len(manager.create_calls) == 1
    assert manager.init_calls == [tmp_path / "target"]


def test_verify_rechecks_corepack_context_after_migration_is_ready(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "pnpm@10.15.0",
                "scripts": {"build": "node src/build.mjs", "dev": "vite"},
            }
        ),
        encoding="utf-8",
    )
    (source / "Dockerfile").write_text(
        "FROM node:22-alpine AS frontend-build\n"
        "WORKDIR /app/frontend\n"
        "RUN corepack enable\n"
        "COPY frontend/package.json frontend/pnpm-lock.yaml ./\n"
        "RUN pnpm install --frozen-lockfile && pnpm build\n",
        encoding="utf-8",
    )
    service = MigrationService(app_manager=FakeAppManager())
    service.start(source, tmp_path / "target", migration_id="migration-corepack-verify")
    target = tmp_path / "target"
    (target / "Dockerfile").write_text(
        "FROM node:22-alpine AS frontend-build\n"
        "WORKDIR /app\n"
        "RUN corepack enable\n"
        "COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/\n"
        "RUN pnpm --dir frontend install && pnpm --dir frontend build\n",
        encoding="utf-8",
    )

    result = service.verify(target, migration_id="migration-corepack-verify")

    assert result["passed"] is False
    assert result["delivery_ready"] is False
    assert result["checks"]["frontend_build_contract"] is False
    assert result["frontend_build"]["reason"] == "corepack_context_mismatch"


def test_convert_legacy_moves_old_state_to_backup(tmp_path: Path) -> None:
    target = tmp_path / "target"
    legacy = target / ".opscli" / "migration" / "legacy-demo"
    legacy.mkdir(parents=True)
    (legacy / "migration.json").write_text(
        json.dumps({"migration_id": "legacy-demo", "phase": "audit"}), encoding="utf-8"
    )
    (legacy / "coverage-matrix.json").write_text("{}", encoding="utf-8")
    current = legacy.parent / "current.json"
    current.write_text(json.dumps({"migration_id": "legacy-demo"}), encoding="utf-8")

    result = MigrationService().convert_legacy(target)

    assert result["status"] == "legacy_converted"
    assert not legacy.exists()
    assert Path(result["legacy_backup"]).is_dir()
