"""Canopy 正式/调试 CLI 分轨测试。"""

import importlib
import json

from typer.testing import CliRunner

from opscli.canopy import cli as canopy_cli
from opscli.canopy_debug import cli as canopy_debug_cli


runner = CliRunner()


def test_public_canopy_help_keeps_remote_commands():
    result = runner.invoke(canopy_cli.app, ["run", "--help"])

    assert result.exit_code == 0
    assert "Canopy" in result.stdout
    assert "job-id" in result.stdout
    assert "api-key" not in result.stdout
    assert "output-dir" not in result.stdout


def test_debug_canopy_help_keeps_local_commands():
    result = runner.invoke(canopy_debug_cli.app, ["job-status", "--help"])

    assert result.exit_code == 0
    assert "Canopy" in result.stdout
    assert "job-id" not in result.stdout
    assert "output-dir" in result.stdout


def test_debug_canopy_run_keeps_local_execution_path(monkeypatch):
    captured = {}

    class FakeResult:
        """模拟本地执行结果。"""

        def to_dict(self):
            return {"job_id": "debug-job", "mode": "local"}

    class FakeManager:
        """模拟本地 Canopy 管理器。"""

        def scenarios(self):
            return [{"scenario_id": "product"}]

        async def run(self, request):
            captured["request"] = request
            return FakeResult()

        def job_status(self, job_id):
            return {"job_id": job_id, "export": {"filename": "debug.xlsx"}}

    monkeypatch.setattr(canopy_debug_cli, "CanopyApiManager", lambda: FakeManager())
    monkeypatch.setattr(canopy_debug_cli, "load_local_api_key", lambda: "local-file-key")

    result = runner.invoke(
        canopy_debug_cli.app,
        [
            "run",
            "product",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--api-key",
            "manual-key",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].scenario == "product"
    assert captured["request"].params == {"asin": "B07YRMT36L"}
    assert captured["request"].api_key == "manual-key"
    assert captured["request"].api_key_placeholder_used is False
    assert '"job_id": "debug-job"' in result.stdout


def test_debug_canopy_export_fails_when_export_payload_missing(monkeypatch):
    class FakeManager:
        """模拟缺失导出信息的本地管理器。"""

        def job_status(self, job_id):
            return {"job_id": job_id, "export": None}

    monkeypatch.setattr(canopy_debug_cli, "CanopyApiManager", lambda: FakeManager())

    result = runner.invoke(canopy_debug_cli.app, ["export", "job-no-export"])

    assert result.exit_code == 1
    assert "任务未生成导出文件：job-no-export" in result.output


def test_debug_canopy_status_and_export_use_custom_output_dir(monkeypatch):
    captured = {}

    class FakeManager:
        """模拟按自定义 output_dir 构造的本地管理器。"""

        def __init__(self, *args, **kwargs):
            captured["settings"] = kwargs.get("settings")

        def job_status(self, job_id):
            captured["job_id"] = job_id
            return {
                "job_id": job_id,
                "export": {"filename": "debug.xlsx", "path": "D:/custom/debug.xlsx"},
            }

    monkeypatch.setattr(canopy_debug_cli, "CanopyApiManager", FakeManager)

    status_result = runner.invoke(
        canopy_debug_cli.app,
        ["job-status", "job-1", "--output-dir", "D:/custom"],
    )
    export_result = runner.invoke(
        canopy_debug_cli.app,
        ["export", "job-1", "--output-dir", "D:/custom"],
    )

    assert status_result.exit_code == 0
    assert export_result.exit_code == 0
    assert captured["settings"].output_dir.name == "custom"
    assert captured["job_id"] == "job-1"
    assert '"filename": "debug.xlsx"' in status_result.stdout
    assert '"filename": "debug.xlsx"' in export_result.stdout


def test_root_cli_import_registers_canopy_and_debug_without_callback_side_effects():
    root_cli = importlib.import_module("opscli.cli")

    registered_names = [group.name for group in root_cli.app.registered_groups]

    assert "canopy" in registered_names
    assert "canopy-debug" in registered_names
