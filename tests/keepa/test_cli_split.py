"""Keepa 正式 CLI 合同测试。"""

from typer.testing import CliRunner

from opscli.keepa import cli as keepa_cli


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


def test_public_keepa_token_status_is_not_available():
    result = runner.invoke(keepa_cli.app, ["token-status"])

    assert result.exit_code == 2
    assert "No such command" in result.output
