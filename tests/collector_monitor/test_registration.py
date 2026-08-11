"""Collector Monitor 顶级命令与发布入口回归测试。"""

from pathlib import Path

from typer.testing import CliRunner

from opscli.cli import app
from opscli.collector_monitor.cli import app as collector_monitor_app
from opscli.collector_monitor.server import run


runner = CliRunner()


def test_top_level_cli_registers_collector_monitor() -> None:
    """顶级 CLI 应公开独立监控命令组。"""
    result = runner.invoke(app, ["collector-monitor", "--help"])

    assert result.exit_code == 0
    assert "serve" in result.stdout
    assert "status" in result.stdout
    assert "tasks" in result.stdout
    assert "show" in result.stdout
    assert "incidents" in result.stdout


def test_project_declares_collector_monitor_service_entrypoint() -> None:
    """生产包应提供独立监控服务入口。"""
    pyproject = (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")

    assert collector_monitor_app is not None
    assert callable(run)
    assert 'opscli-collector-monitor = "opscli.collector_monitor.server:run"' in pyproject
