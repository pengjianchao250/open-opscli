"""opscli app 命令树注册测试。"""

import json

from typer.main import get_command
from typer.testing import CliRunner

from opscli.cli import app


def test_app_exposes_expected_commands() -> None:
    root_command = get_command(app)
    app_command = root_command.commands["app"]

    assert set(app_command.commands) == {
        "create",
        "ensure-git",
        "clone-template",
        "init",
        "dev",
        "dev-status",
        "push",
        "migrate",
    }
    assert set(app_command.commands["migrate"].commands) == {
        "init",
        "audit",
        "plan",
        "status",
        "check",
        "verify-ui",
        "verify-data",
        "verify-release",
        "export",
    }


def test_migrate_init_forwards_paths_and_id(monkeypatch) -> None:
    captured = {}

    class FakeMigrationService:
        def initialize(self, source, target, *, migration_id=None):
            captured.update(source=source, target=target, migration_id=migration_id)
            return {"migration_id": migration_id, "phase": "audit"}

    monkeypatch.setattr("opscli.app.commands.cli.MigrationService", FakeMigrationService)
    result = CliRunner().invoke(
        app,
        [
            "app",
            "migrate",
            "init",
            "--source",
            "legacy",
            "--target",
            "target",
            "--migration-id",
            "migration-demo",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert str(captured["source"]) == "legacy"
    assert str(captured["target"]) == "target"
    assert captured["migration_id"] == "migration-demo"
    assert json.loads(result.output)["command"] == "app migrate init"


def test_migrate_check_returns_stable_error_envelope(monkeypatch) -> None:
    class FakeMigrationService:
        def check(self, target, *, gate, migration_id=None):
            from opscli.app.domain.exceptions import AppProjectError

            raise AppProjectError(
                "APP-MIGRATION-GATE",
                "迁移门禁未通过：ui",
                detail={"gate": gate, "problems": ["coverage empty"]},
            )

    monkeypatch.setattr("opscli.app.commands.cli.MigrationService", FakeMigrationService)
    result = CliRunner().invoke(
        app,
        ["app", "migrate", "check", "--gate", "ui", "--target", ".", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "APP-MIGRATION-GATE"
    assert payload["error"]["detail"]["gate"] == "ui"


def test_ensure_git_check_is_read_only(monkeypatch) -> None:
    captured = {}

    class FakeGitEnvironmentService:
        def ensure(self, *, install=False):
            captured["install"] = install
            return {
                "ready": False,
                "status": "missing",
                "platform": "windows",
                "architecture": "x64",
                "translated": False,
                "git_path": None,
                "git_version": None,
                "minimum_version": "2.30.0",
                "install_method": None,
                "message": "未检测到可用 Git。",
            }

    monkeypatch.setattr(
        "opscli.app.commands.cli.GitEnvironmentService",
        FakeGitEnvironmentService,
    )
    result = CliRunner().invoke(app, ["app", "ensure-git", "--check", "--json"])

    assert result.exit_code == 0
    assert captured["install"] is False
    assert '"status": "missing"' in result.output


def test_ensure_git_install_requests_installation(monkeypatch) -> None:
    captured = {}

    class FakeGitEnvironmentService:
        def ensure(self, *, install=False):
            captured["install"] = install
            return {"ready": True, "status": "ready", "message": "Git 环境已就绪。"}

    monkeypatch.setattr(
        "opscli.app.commands.cli.GitEnvironmentService",
        FakeGitEnvironmentService,
    )
    result = CliRunner().invoke(app, ["app", "ensure-git", "--install", "--json"])

    assert result.exit_code == 0
    assert captured["install"] is True


def test_dev_forwards_project_and_ports(monkeypatch) -> None:
    captured = {}

    class FakeDevService:
        def run(self, path, **kwargs):
            captured["path"] = path
            captured.update(kwargs)

    monkeypatch.setattr("opscli.app.commands.cli.DevService", FakeDevService)
    result = CliRunner().invoke(
        app,
        ["app", "dev", ".", "--backend-port", "8036", "--frontend-port", "5174"],
    )

    assert result.exit_code == 0
    assert str(captured["path"]) in {"", "."}
    assert captured["backend_port"] == 8036
    assert captured["frontend_port"] == 5174


def test_dev_omits_ports_for_automatic_selection(monkeypatch) -> None:
    captured = {}

    class FakeDevService:
        def run(self, path, **kwargs):
            captured["path"] = path
            captured.update(kwargs)

    monkeypatch.setattr("opscli.app.commands.cli.DevService", FakeDevService)
    result = CliRunner().invoke(app, ["app", "dev", "."])

    assert result.exit_code == 0
    assert captured["backend_port"] is None
    assert captured["frontend_port"] is None


def test_dev_status_emits_project_identity_as_json(monkeypatch) -> None:
    class FakeDevService:
        def status(self, path):
            return {
                "project_root": str(path),
                "status": "running",
                "running": True,
                "identity_verified": True,
                "frontend_url": "http://127.0.0.1:5174",
                "backend_url": "http://127.0.0.1:8036",
                "message": "项目身份已验证。",
            }

    monkeypatch.setattr("opscli.app.commands.cli.DevService", FakeDevService)
    result = CliRunner().invoke(app, ["app", "dev-status", "project", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "app dev-status"
    assert payload["data"]["running"] is True
    assert payload["data"]["identity_verified"] is True
    assert payload["data"]["frontend_url"] == "http://127.0.0.1:5174"


def test_clone_template_forwards_options_and_emits_json(monkeypatch) -> None:
    captured = {}

    class FakeTemplateService:
        def clone(self, path, **kwargs):
            captured["path"] = path
            captured.update(kwargs)
            return {"path": str(path), "message": "模板已准备完成。"}

    monkeypatch.setattr("opscli.app.commands.cli.TemplateService", FakeTemplateService)
    result = CliRunner().invoke(
        app,
        [
            "app",
            "clone-template",
            "project",
            "--repo-url",
            "https://example.test/template.git",
            "--branch",
            "main",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert str(captured["path"]) == "project"
    assert captured["repo_url"] == "https://example.test/template.git"
    assert captured["branch"] == "main"
    assert json.loads(result.output)["command"] == "app clone-template"


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
    }


def test_init_no_longer_exposes_manual_credential_rotation() -> None:
    result = CliRunner().invoke(app, ["app", "init", "--help"])

    assert result.exit_code == 0
    assert "--rotate-git-credential" not in result.output


def test_init_reports_automatic_credential_refresh(monkeypatch) -> None:
    class FakeManager:
        def init_git(self, path, **kwargs):
            return {"credential_refreshed": True}

        def close(self):
            pass

    monkeypatch.setattr("opscli.app.commands.cli.AppManager", FakeManager)
    result = CliRunner().invoke(app, ["app", "init", "."])

    assert result.exit_code == 0
    assert "Git 认证已自动刷新。" in result.output


def test_push_reports_unified_success_message(monkeypatch) -> None:
    expected_message = (
        "推送成功；运营系统将自动部署并发布当前站点，"
        "您可以前往运营系统查看发布状态、或进行站点权限设置。"
    )

    class FakeManager:
        def push(self, path, *, message):
            return {"message": expected_message, "pushed": True}

        def close(self):
            pass

    monkeypatch.setattr("opscli.app.commands.cli.AppManager", FakeManager)

    result = CliRunner().invoke(app, ["app", "push", ".", "-m", "优化首页"])

    assert result.exit_code == 0
    assert expected_message in result.output


def test_push_json_keeps_unified_success_message(monkeypatch) -> None:
    expected_message = (
        "推送成功；运营系统将自动部署并发布当前站点，"
        "您可以前往运营系统查看发布状态、或进行站点权限设置。"
    )

    class FakeManager:
        def push(self, path, *, message):
            return {"message": expected_message, "pushed": True}

        def close(self):
            pass

    monkeypatch.setattr("opscli.app.commands.cli.AppManager", FakeManager)

    result = CliRunner().invoke(
        app,
        ["app", "push", ".", "-m", "优化首页", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["message"] == expected_message
