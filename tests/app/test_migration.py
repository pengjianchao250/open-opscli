"""源码复制迁移流程测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.migration import MigrationService


class FakeAppManager:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.init_calls: list[Path] = []

    def create_app(self, app_name: str, *, path: Path, origin_type: str, migration_id: str) -> dict:
        self.create_calls.append(
            {
                "app_name": app_name,
                "path": path,
                "origin_type": origin_type,
                "migration_id": migration_id,
            }
        )
        binding = path / ".opscli" / "app.json"
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text("{}", encoding="utf-8")
        return {"app_id": "Ab123", "app_name": app_name, "path": str(path)}

    def init_git(self, path: Path) -> dict:
        self.init_calls.append(path)
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
    assert manager.create_calls[0]["origin_type"] == "migration_copy"
    assert manager.create_calls[0]["migration_id"] == "migration-demo"
    assert manager.init_calls == [target]
    assert result["phase"] == "initialized"
    assert result["startup_status"] == "ready"


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


def test_default_target_is_created_under_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path, runnable=False)
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    result = MigrationService(app_manager=FakeAppManager()).start(source)

    target = Path(result["target_root"])
    assert target.parent == workdir
    assert target.name.startswith("app-hub-source-")


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
