"""Google Trends 正式/调试 CLI 分轨测试。"""

import importlib
import json

from typer.testing import CliRunner

from opscli.google_trends import cli as google_trends_cli
from opscli.google_trends_debug import cli as google_trends_debug_cli


runner = CliRunner()


def test_public_google_trends_help_keeps_remote_commands():
    """正式 CLI 帮助中应只展示远端公共命令。"""
    result = runner.invoke(google_trends_cli.app, ["--help"])

    assert result.exit_code == 0
    assert "Google Trends 远端 MCP 正式命令面。" in result.stdout
    assert "scenarios" in result.stdout
    assert "job-status" in result.stdout
    assert "export" in result.stdout


def test_public_google_trends_run_help_hides_output_dir():
    """正式 run 帮助不应暴露本地输出目录参数。"""
    result = runner.invoke(google_trends_cli.app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--output-dir" not in result.stdout


def test_debug_google_trends_help_keeps_local_commands():
    """调试 CLI 帮助中应展示本地直连命令。"""
    result = runner.invoke(google_trends_debug_cli.app, ["--help"])

    assert result.exit_code == 0
    assert "Google Trends 本地调试命令；保留本地直连执行链路。" in result.stdout
    assert "scenarios" in result.stdout
    assert "job-status" in result.stdout
    assert "export" in result.stdout


def test_debug_google_trends_run_keeps_local_execution_path(monkeypatch):
    """google-trends-debug run 应继续走本地执行链路。"""
    captured = {}

    class FakeResult:
        """模拟本地执行结果。"""

        def to_dict(self):
            return {"job_id": "debug-job", "mode": "local"}

    class FakeManager:
        """模拟本地 Google Trends 管理器。"""

        def scenarios(self):
            return [{"id": "interest-over-time"}]

        async def run(self, request):
            captured["request"] = request
            return FakeResult()

        def job_status(self, job_id):
            return {"job_id": job_id, "export": {"filename": "debug.xlsx"}}

    monkeypatch.setattr(google_trends_debug_cli, "GoogleTrendsApiManager", lambda: FakeManager())

    result = runner.invoke(
        google_trends_debug_cli.app,
        [
            "run",
            "interest-over-time",
            "--params",
            json.dumps({"keyword": "flashlight"}),
            "--hl",
            "en-US",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].scenario == "interest-over-time"
    assert captured["request"].params == {"keyword": "flashlight"}
    assert captured["request"].hl == "en-US"
    assert '"job_id": "debug-job"' in result.stdout


def test_debug_google_trends_export_fails_when_export_payload_missing(monkeypatch):
    """debug export 缺失导出信息时应明确失败。"""

    class FakeManager:
        """模拟缺失导出信息的本地管理器。"""

        def job_status(self, job_id):
            return {"job_id": job_id, "export": None}

    monkeypatch.setattr(google_trends_debug_cli, "GoogleTrendsApiManager", lambda: FakeManager())

    result = runner.invoke(google_trends_debug_cli.app, ["export", "job-no-export"])

    assert result.exit_code == 1
    assert "任务未生成导出文件：job-no-export" in result.output


def test_root_cli_import_registers_google_trends_debug_without_callback_side_effects():
    """根 CLI 应注册 google-trends 与 google-trends-debug。"""
    root_cli = importlib.import_module("opscli.cli")

    registered_names = [group.name for group in root_cli.app.registered_groups]

    assert "google-trends" in registered_names
    assert "google-trends-debug" in registered_names
