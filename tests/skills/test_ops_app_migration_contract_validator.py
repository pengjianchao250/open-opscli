"""AppHub 迁移三项标准验证合同测试。"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from opscli.app.services.migration_contract import migration_release_fingerprint

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "opscli"
    / "skills"
    / "templates"
    / "ops-app-build-spec"
    / "scripts"
    / "validate_migration_contract.py"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "apphub_migration_contract_validator",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_project(root: Path) -> None:
    source = root.parent / f"source-{root.name}"
    source.mkdir()
    migration_id = "migration-contract"
    migration_dir = root / ".opscli" / "migration" / migration_id
    migration_dir.mkdir(parents=True)
    (root / ".opscli" / "project.json").write_text(
        json.dumps(
            {
                "origin_type": "migration_copy",
                "migration_id": migration_id,
                "source_root": str(source),
            }
        ),
        encoding="utf-8",
    )
    for name, payload in {
        "copy-manifest.json": {"status": "ready"},
        "startup-manifest.json": {"status": "ready"},
        "adaptation-manifest.json": {"status": "ready"},
        "migration.json": {
            "app_id": "Ab123",
            "phase": "push_ready",
            "delivery_ready": True,
        },
    }.items():
        (migration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    (root / "server.js").write_text(
        'const port = Number(process.env.PORT || "8000");\n'
        'const healthPath = "/__apphub_healthz";\n',
        encoding="utf-8",
    )
    (root / "app.yaml").write_text(
        'apiVersion: apps.aukeys/v1\napp_id: "Ab123"\ntitle: "迁移应用"\n',
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        "FROM node:22-alpine\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "EXPOSE 8000\n"
        'CMD ["node", "server.js"]\n',
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(".opscli/\n/data/\n.env\n", encoding="utf-8")
    (root / ".dockerignore").write_text(".git\n.opscli\n/data/\n.env\n", encoding="utf-8")


def _command(exit_code: int = 0) -> list[str]:
    return [sys.executable, "-c", f"raise SystemExit({exit_code})"]


@pytest.fixture
def project_root() -> Iterator[Path]:
    """使用仓库内短路径，规避 Windows 临时目录初始化的环境级延迟。"""
    root = ROOT / ".test-tmp" / uuid.uuid4().hex
    source = root.parent / f"source-{root.name}"
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(source, ignore_errors=True)


def test_three_contracts_pass_and_write_validation_manifest(project_root: Path) -> None:
    validator = _load_validator()
    _write_project(project_root)

    result = validator.validate_migration(
        project_root,
        local_check=_command(),
        apphub_check=_command(),
    )

    assert result["release_ready"] is True
    assert all(item["passed"] for item in result["contracts"].values())
    assert not (project_root / "backend" / "app.py").exists()
    assert not (project_root / "nixpacks.toml").exists()
    assert result["commands"]["parity"]["status"] == "not_required"
    assert (
        result["contracts"]["dual_runtime"]["mode"]
        == "lightweight_runtime_compatibility"
    )
    manifest = Path(result["validation_manifest"])
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["release_ready"] is True


@pytest.mark.parametrize("failed_check", ["local", "apphub"])
def test_any_dual_runtime_failure_blocks_release(
    project_root: Path,
    failed_check: str,
) -> None:
    validator = _load_validator()
    _write_project(project_root)
    commands = {
        name: _command(1 if name == failed_check else 0)
        for name in ("local", "apphub")
    }

    result = validator.validate_migration(
        project_root,
        local_check=commands["local"],
        apphub_check=commands["apphub"],
    )

    assert result["release_ready"] is False
    assert result["contracts"]["dual_runtime"]["passed"] is False


def test_required_parity_failure_blocks_release(project_root: Path) -> None:
    validator = _load_validator()
    _write_project(project_root)

    result = validator.validate_migration(
        project_root,
        local_check=_command(),
        apphub_check=_command(),
        parity_check=_command(1),
        require_parity=True,
    )

    assert result["release_ready"] is False
    assert result["commands"]["parity"]["status"] == "failed"


def test_required_parity_without_command_blocks_release(project_root: Path) -> None:
    validator = _load_validator()
    _write_project(project_root)

    result = validator.validate_migration(
        project_root,
        local_check=_command(),
        apphub_check=_command(),
        require_parity=True,
    )

    assert result["release_ready"] is False
    assert result["commands"]["parity"]["status"] == "missing_required_command"


def test_duplicate_checks_reuse_one_command_result(
    project_root: Path,
    monkeypatch,
) -> None:
    validator = _load_validator()
    _write_project(project_root)
    calls: list[list[str]] = []

    def fake_run_command(root: Path, command: list[str], timeout: int) -> dict:
        calls.append(command)
        return {
            "passed": True,
            "status": "passed",
            "command": command,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(validator, "_run_command", fake_run_command)
    command = _command()

    result = validator.validate_migration(
        project_root,
        local_check=command,
        apphub_check=command,
    )

    assert calls == [command]
    assert result["commands"]["apphub"]["status"] == "reused"
    assert result["commands"]["apphub"]["reused_from"] == "local"


def test_missing_release_asset_blocks_release(project_root: Path) -> None:
    validator = _load_validator()
    _write_project(project_root)
    (project_root / "app.yaml").unlink()

    result = validator.validate_migration(
        project_root,
        local_check=_command(),
        apphub_check=_command(),
    )

    assert result["release_ready"] is False
    release_gate = result["contracts"]["release_gate"]
    assert release_gate["passed"] is False
    assert "app.yaml" in release_gate["checks"]["detail"]["missing"]


def test_release_fingerprint_changes_after_source_edit(project_root: Path) -> None:
    _write_project(project_root)
    before = migration_release_fingerprint(project_root)

    (project_root / "server.js").write_text(
        'const port = Number(process.env.PORT || "8000");\n'
        'const healthPath = "/__apphub_healthz";\n'
        "const value = 2;\n",
        encoding="utf-8",
    )

    assert migration_release_fingerprint(project_root)["sha256"] != before["sha256"]
