"""opscli app 命令树注册测试。"""

from typer.main import get_command

from opscli.cli import app


def test_app_only_exposes_four_commands() -> None:
    root_command = get_command(app)
    app_command = root_command.commands["app"]

    assert set(app_command.commands) == {"create", "init", "push", "release"}
