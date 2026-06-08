import json

from typer.testing import CliRunner

from opscli.skills.exceptions import SkillsError
from opscli.skills.cli import app


runner = CliRunner()


def test_list_outputs_doc_aligned_json(monkeypatch):
    class DummyManager:
        def status(self, skills_dir=None):
            return {
                "skills": [
                    {
                        "name": "ops-dataset-query",
                        "local_version": "v0.1.0",
                        "remote_version": "v0.1.2",
                        "has_update": True,
                        "installed_paths": [
                            {
                                "tool": "claude-code",
                                "path": "/tmp/.claude/skills/ops-dataset-query",
                            }
                        ],
                    }
                ]
            }

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "skills list"
    assert payload["data"]["skills"][0]["has_update"] is True
    assert payload["data"]["skills"][0]["installed_paths"][0]["tool"] == "claude-code"


def test_install_outputs_doc_aligned_json(monkeypatch):
    class DummyInstallResult:
        def to_dict(self):
            return {
                "name": "ops-dataset-query",
                "version": "v0.0.0",
                "installed_paths": [
                    {
                        "tool": "claude-code",
                        "path": "/tmp/.claude/skills/ops-dataset-query",
                    }
                ],
            }

    class DummyManager:
        def install(self, *args, **kwargs):
            return DummyInstallResult()

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["install", "ops-dataset-query"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "skills install"
    assert payload["data"]["version"] == "v0.0.0"
    assert payload["data"]["installed_paths"][0]["tool"] == "claude-code"
    assert "requires_amazon_login" not in payload["data"]


def test_install_ops_amazon_rufus_outputs_login_guidance(monkeypatch):
    class DummyInstallResult:
        def to_dict(self):
            return {
                "name": "ops-amazon-rufus",
                "version": "v0.0.0",
                "installed_paths": [
                    {
                        "tool": "codex",
                        "path": "/tmp/.agents/skills/ops-amazon-rufus",
                    }
                ],
            }

    class DummyManager:
        def install(self, *args, **kwargs):
            return DummyInstallResult()

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["install", "ops-amazon-rufus"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["requires_amazon_login"] is True
    assert any("opscli amazon-rufus watch-login <asin> <country>" in step for step in payload["data"]["next_steps"])
    assert any("amazon_rufus_get" in step for step in payload["data"]["next_steps"])
    assert not any("--new-chrome" in step for step in payload["data"]["next_steps"])
    assert not any("mock" in step.lower() for step in payload["data"]["next_steps"])
    assert not any("curl save" in step.lower() for step in payload["data"]["next_steps"])
    assert not any("cookie save" in step.lower() for step in payload["data"]["next_steps"])


def test_interactive_install_ops_amazon_rufus_outputs_login_guidance(monkeypatch):
    class DummyInstallResult:
        installs = []

        def to_dict(self):
            return {
                "name": "ops-amazon-rufus",
                "version": "v0.0.0",
                "installed_paths": [
                    {
                        "tool": "codex",
                        "path": "/tmp/.agents/skills/ops-amazon-rufus",
                    }
                ],
            }

    class DummyManager:
        detector = None

        def install(self, *args, **kwargs):
            return DummyInstallResult()

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())
    monkeypatch.setattr("opscli.skills.commands.cli._tui_select_skills", lambda manager, yes=False: ["ops-amazon-rufus"])
    monkeypatch.setattr("opscli.skills.commands.cli._tui_select_targets", lambda manager, yes=False: None)

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout.splitlines()[-1])
    installed = payload["data"]["results"][0]
    assert installed["requires_amazon_login"] is True
    assert any("opscli amazon-rufus watch-login <asin> <country>" in step for step in installed["next_steps"])
    assert any("amazon_rufus_get" in step for step in installed["next_steps"])
    assert not any("--new-chrome" in step for step in installed["next_steps"])
    assert not any("mock" in step.lower() for step in installed["next_steps"])
    assert not any("curl save" in step.lower() for step in installed["next_steps"])
    assert not any("cookie save" in step.lower() for step in installed["next_steps"])


def test_install_prompts_and_defaults_to_all_detected_targets(monkeypatch):
    class DummyInstallResult:
        def to_dict(self):
            return {
                "name": "ops-dataset-query",
                "version": "v0.0.0",
                "installed_paths": [
                    {"tool": "claude-code", "path": "/tmp/.claude/skills/ops-dataset-query"},
                    {"tool": "openclaw", "path": "/tmp/.openclaw/skills/ops-dataset-query"},
                ],
            }

    class DummyDetector:
        def detect_available_install_targets(self, cwd=None):
            return [
                ("claude", "/tmp/.claude/skills"),
                ("openclaw", "/tmp/.openclaw/skills"),
            ]

    class DummyManager:
        def __init__(self):
            self.detector = DummyDetector()
            self.install_runtime = None

        def install(self, *args, **kwargs):
            self.install_runtime = kwargs["runtime"]
            return DummyInstallResult()

    manager = DummyManager()
    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: manager)

    result = runner.invoke(app, ["install", "ops-dataset-query"], input="\n")

    assert result.exit_code == 0
    assert "检测到的安装目标" in result.stdout
    assert manager.install_runtime == ["claude", "openclaw"]


def test_install_prompts_and_supports_multi_select(monkeypatch):
    class DummyInstallResult:
        def to_dict(self):
            return {
                "name": "ops-dataset-query",
                "version": "v0.0.0",
                "installed_paths": [
                    {"tool": "openclaw", "path": "/tmp/.openclaw/skills/ops-dataset-query"},
                ],
            }

    class DummyDetector:
        def detect_available_install_targets(self, cwd=None):
            return [
                ("claude", "/tmp/.claude/skills"),
                ("openclaw", "/tmp/.openclaw/skills"),
            ]

    class DummyManager:
        def __init__(self):
            self.detector = DummyDetector()
            self.install_runtime = None

        def install(self, *args, **kwargs):
            self.install_runtime = kwargs["runtime"]
            return DummyInstallResult()

    manager = DummyManager()
    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: manager)

    result = runner.invoke(app, ["install", "ops-dataset-query"], input="2\n")

    assert result.exit_code == 0
    assert manager.install_runtime == ["openclaw"]


def test_upgrade_outputs_doc_aligned_json(monkeypatch):
    class DummyUpgradeResult:
        def to_dict(self):
            return {
                "updated": [
                    {
                        "name": "ops-dataset-query",
                        "from_version": "v0.1.0",
                        "to_version": "v0.1.2",
                        "field_count": 1247,
                        "tools": ["claude-code", "openclaw"],
                    }
                ],
                "already_latest": [],
                "failed": [],
            }

    class DummyManager:
        def upgrade(self, **kwargs):
            return DummyUpgradeResult()

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["upgrade", "ops-dataset-query"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "skills upgrade"
    assert payload["data"]["updated"][0]["field_count"] == 1247
    assert payload["data"]["updated"][0]["tools"] == ["claude-code", "openclaw"]


def test_upgrade_force_passes_flag_to_manager(monkeypatch):
    class DummyUpgradeResult:
        def to_dict(self):
            return {"updated": [], "already_latest": [], "failed": []}

    class DummyManager:
        def __init__(self):
            self.called_with = None

        def upgrade(self, **kwargs):
            self.called_with = kwargs
            return DummyUpgradeResult()

    manager = DummyManager()
    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: manager)

    result = runner.invoke(app, ["upgrade", "ops-dataset-query", "--force"])

    assert result.exit_code == 0
    called = manager.called_with
    assert called is not None
    assert called["name"] == "ops-dataset-query"
    assert called["skills_dir"] is None
    assert called["force"] is True
    assert callable(called["on_step"])


def test_status_outputs_json(monkeypatch):
    class DummyManager:
        def status(self, skills_dir=None):
            return {
                "skills": [],
                "installed": [],
                "remote_manifest": {"version": "v1.0.0"},
                "remote_summary": {"ops_url": "https://ops.example.com/api"},
                "remote_error": None,
            }

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "skills status"
    assert payload["data"]["remote_manifest"]["version"] == "v1.0.0"


def test_status_outputs_structured_error(monkeypatch):
    class DummyManager:
        def status(self, skills_dir=None):
            raise SkillsError("状态查询失败")

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == {
        "type": "SkillsError",
        "message": "状态查询失败",
    }


def test_install_outputs_structured_error(monkeypatch):
    class DummyManager:
        def install(self, *args, **kwargs):
            raise SkillsError("安装失败")

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["install", "ops-dataset-query"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == {
        "type": "SkillsError",
        "message": "安装失败",
    }


def test_upgrade_outputs_structured_error(monkeypatch):
    class DummyManager:
        def upgrade(self, **kwargs):
            raise SkillsError("升级失败")

    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: DummyManager())

    result = runner.invoke(app, ["upgrade", "ops-dataset-query"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == {
        "type": "SkillsError",
        "message": "升级失败",
    }
