"""opscli app 命令树注册测试。"""

from typer.main import get_command
from typer.testing import CliRunner

from opscli.cli import app


def test_app_only_exposes_three_commands() -> None:
    root_command = get_command(app)
    app_command = root_command.commands["app"]

    assert set(app_command.commands) == {"create", "init", "push"}


def test_init_forwards_explicit_id_without_reinterpreting_app(monkeypatch) -> None:
    """新 ID 参数与旧 slug 核对参数分别传到业务层。"""
    captured = {}
    class FakeManager:
        def init_git(self, path, **kwargs):
            captured.update(kwargs)
            return {}
        def close(self):
            pass
    monkeypatch.setattr("opscli.app.commands.cli.AppManager", FakeManager)
    result = CliRunner().invoke(app, ["app", "init", ".", "--app-id", "Ab123", "--app", "sales", "--json"])
    assert result.exit_code == 0
    assert captured == {
        "app_id": "Ab123",
        "app_slug": "sales",
        "rotate_git_credential": False,
    }


def test_init_forwards_explicit_credential_rotation(monkeypatch) -> None:
    captured = {}

    class FakeManager:
        def init_git(self, path, **kwargs):
            captured.update(kwargs)
            return {}

        def close(self):
            pass

    monkeypatch.setattr("opscli.app.commands.cli.AppManager", FakeManager)
    result = CliRunner().invoke(
        app,
        ["app", "init", ".", "--app-id", "Ab123", "--rotate-git-credential", "--json"],
    )

    assert result.exit_code == 0
    assert captured["rotate_git_credential"] is True
