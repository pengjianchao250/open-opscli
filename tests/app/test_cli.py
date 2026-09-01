"""opscli app 命令树注册测试。"""

from typer.main import get_command

from opscli.cli import app


def test_app_command_is_registered() -> None:
    root_command = get_command(app)
    app_command = root_command.commands["app"]

    expected = {
        "init", "run", "validate", "publish", "pull", "versions", "rollback", "logs",
        "git", "env", "secret", "members", "db",
    }
    assert expected <= set(app_command.commands)
    assert {"status", "bind", "revoke"} <= set(app_command.commands["git"].commands)
    assert {"get", "set", "unset"} <= set(app_command.commands["env"].commands)
    assert {"list", "set", "unset"} <= set(app_command.commands["secret"].commands)
    assert {"list", "add", "remove"} <= set(app_command.commands["members"].commands)
    assert {"info", "backups", "restore"} <= set(app_command.commands["db"].commands)
