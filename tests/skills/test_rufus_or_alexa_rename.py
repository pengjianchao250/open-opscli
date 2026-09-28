"""验证 Rufus/Alexa Skill 改名后的安装、升级和题库读取链路。"""

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from opscli.amazon_rufus.services.question_bank import QuestionBankService
from opscli.skills.cli import app
from opscli.skills.manager import SkillsManager


def test_renamed_skill_install_upgrade_and_question_bank(tmp_path, monkeypatch):
    """真实复制新模板并读取升级后的题库，隔离网络和用户配置。"""
    skill_name = "ops-amazon-rufus-or-alexa"
    template_root = Path(__file__).resolve().parents[2] / "opscli/skills/templates"
    skills_dir = tmp_path / ".agents/skills"
    manager = SkillsManager(
        registry_path=tmp_path / "registry.json",
        central_skills_dir=tmp_path / "central",
    )
    manager.templates_dir = template_root
    monkeypatch.setattr("opscli.skills.commands.cli.SkillsManager", lambda: manager)
    monkeypatch.setattr("opscli.skills.hooks.settings_injector.ensure_skill_usage_hook", lambda: None)

    result = CliRunner().invoke(app, ["install", skill_name, "--skills-dir", str(skills_dir)])

    assert result.exit_code == 0, result.output
    installed = json.loads(result.stdout)["data"]
    assert installed["name"] == skill_name
    assert installed["requires_amazon_login"] is True
    assert any("amazon_rufus_get" in step for step in installed["next_steps"])
    metadata = skills_dir / skill_name / "data/VERSION.json"
    assert json.loads(metadata.read_text(encoding="utf-8"))["name"] == skill_name
    manifest = json.loads((template_root / "manifest.json").read_text(encoding="utf-8"))
    assert skill_name in manifest["skills"]
    assert skill_name.removesuffix("-or-alexa") not in manifest["skills"]

    # 只替代远端题库响应，其余升级分派、发现和文件写入沿用真实代码。
    monkeypatch.setattr(
        manager.updater,
        "_get_rufus_default_question_templates",
        lambda: httpx.Response(
            200,
            request=httpx.Request("GET", "https://example.test/question-templates"),
            json={"data": {"items": [{
                "id": 56,
                "questions": [{"id": 1, "text": "改名后测试题", "position": 1}],
            }]}},
        ),
    )
    upgraded = manager.upgrade(name=skill_name, skills_dir=str(skills_dir)).to_dict()
    assert upgraded["updated"][0]["name"] == skill_name
    assert json.loads(metadata.read_text(encoding="utf-8"))["name"] == skill_name

    # 默认项目目录和显式 skills_dir 都必须读取改名后的目录。
    monkeypatch.chdir(tmp_path)
    for bank in (QuestionBankService(), QuestionBankService(skills_dir=str(skills_dir))):
        assert bank.load_templates()[0].questions[0].text == "改名后测试题"
