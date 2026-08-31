"""opscli app 命令树注册测试。"""

from typer.main import get_command

from opscli.cli import app


def test_app_command_is_registered() -> None:
    root_command = get_command(app)
    app_command = root_command.commands["app"]

    assert "publish" in app_command.commands
    assert "git" in app_command.commands
