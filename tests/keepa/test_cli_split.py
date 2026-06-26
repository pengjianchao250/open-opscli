"""Keepa 正式/调试 CLI 分轨测试。"""

import importlib
import json

from typer.testing import CliRunner

from opscli.keepa import cli as keepa_cli
from opscli.keepa_debug import cli as keepa_debug_cli


runner = CliRunner()


def test_public_keepa_help_hides_token_status_and_keeps_remote_commands():
    result = runner.invoke(keepa_cli.app, ["--help"])

    assert result.exit_code == 0
    assert "scenarios" in result.stdout
    assert "job-status" in result.stdout
    assert "export" in result.stdout
    assert "token-status" not in result.stdout


def test_public_keepa_run_help_hides_output_dir():
    result = runner.invoke(keepa_cli.app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--output-dir" not in result.stdout


def test_debug_keepa_help_keeps_local_debug_commands():
    result = runner.invoke(keepa_debug_cli.app, ["--help"])

    assert result.exit_code == 0
    assert "token-status" in result.stdout
    assert "job-status" in result.stdout
    assert "export" in result.stdout


def test_public_keepa_token_status_is_not_available():
    result = runner.invoke(keepa_cli.app, ["token-status"])

    assert result.exit_code == 2
    assert "No such command" in result.output


def test_debug_keepa_run_keeps_local_execution_path(monkeypatch):
    captured = {}

    class FakeResult:
        """模拟本地执行结果。"""

        def to_dict(self):
            return {"job_id": "debug-job", "mode": "local"}

    class FakeManager:
        """模拟本地 Keepa 管理器。"""

        def scenarios(self):
            return [{"id": "product"}]

        async def token_status(self):
            return {"quota": {"tokensLeft": 10}}

        async def run(self, request):
            captured["request"] = request
            return FakeResult()

        def job_status(self, job_id):
            return {"job_id": job_id, "export": {"filename": "debug.xlsx"}}

    monkeypatch.setattr(keepa_debug_cli, "KeepaApiManager", lambda: FakeManager())

    result = runner.invoke(
        keepa_debug_cli.app,
        [
            "run",
            "product",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--wait",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].scenario == "product"
    assert captured["request"].params == {"asin": "B07YRMT36L"}
    assert captured["request"].wait is True
    assert '"job_id": "debug-job"' in result.stdout


def test_debug_keepa_token_status_and_export_use_local_manager(monkeypatch):
    class FakeManager:
        """模拟本地 Keepa 管理器。"""

        def scenarios(self):
            return [{"id": "product"}]

        async def token_status(self):
            return {"quota": {"tokensLeft": 10}}

        async def run(self, request):
            raise AssertionError("run should not be called")

        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "export": {
                    "filename": "keepa-debug.xlsx",
                    "path": "D:/tmp/keepa-debug.xlsx",
                },
            }

    monkeypatch.setattr(keepa_debug_cli, "KeepaApiManager", lambda: FakeManager())

    token_result = runner.invoke(keepa_debug_cli.app, ["token-status"])
    export_result = runner.invoke(keepa_debug_cli.app, ["export", "job-1"])

    assert token_result.exit_code == 0
    assert '"tokensLeft": 10' in token_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "keepa-debug.xlsx"' in export_result.stdout


def test_debug_keepa_export_fails_when_export_payload_missing(monkeypatch):
    class FakeManager:
        """模拟缺失导出信息的本地 Keepa 管理器。"""

        def job_status(self, job_id):
            return {"job_id": job_id, "export": None}

    monkeypatch.setattr(keepa_debug_cli, "KeepaApiManager", lambda: FakeManager())

    result = runner.invoke(keepa_debug_cli.app, ["export", "job-no-export"])

    assert result.exit_code == 1
    assert "任务未生成导出文件：job-no-export" in result.output


def test_root_cli_import_registers_keepa_debug_without_network_side_effects():
    root_cli = importlib.import_module("opscli.cli")

    registered_names = [group.name for group in root_cli.app.registered_groups]

    assert "keepa" in registered_names
    assert "keepa-debug" in registered_names
