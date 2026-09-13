import json
from pathlib import Path

from opscli.skills.services.manager import SkillsManager


SKILL_DIR = Path("opscli/skills/templates/ops-xiyou")
SKILL_PATH = SKILL_DIR / "SKILL.md"
VERSION_PATH = SKILL_DIR / "data" / "VERSION.json"
MANIFEST_PATH = Path("opscli/skills/templates/manifest.json")


def test_ops_xiyou_template_identity_is_consistent():
    text = SKILL_PATH.read_text(encoding="utf-8")
    version = json.loads(VERSION_PATH.read_text(encoding="utf-8"))

    assert text.startswith("---\nname: ops-xiyou\n")
    assert "mcp-version: v1.1.0" in text
    assert version == {"name": "ops-xiyou", "version": "v1.1.0"}


def test_ops_xiyou_requires_explicit_trigger_and_discloses_credit():
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "只有满足以下任一条件才使用本 Skill" in text
    assert "普通 Amazon" in text
    assert "不得自动路由到西柚" in text
    assert "消耗西柚 Credit" in text


def test_ops_xiyou_covers_only_registered_xydc_trial_tools():
    text = SKILL_PATH.read_text(encoding="utf-8")
    expected_tools = {
        "ext_xydc_get_asin_info",
        "ext_xydc_get_asin_traffic",
        "ext_xydc_get_keyword_info",
        "ext_xydc_get_keyword_asin_analysis",
    }

    assert expected_tools == {name for name in expected_tools if name in text}
    assert "source=xydc_mcp" in text
    assert "cost_credits" in text
    assert "xiyou_run" not in text
    assert "xiyou_scenarios" not in text
    assert "xiyou_export" not in text


def test_ops_xiyou_documents_provider_rotation_and_retry_boundary():
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "周额度耗尽" in text
    assert "Token 无效" in text
    assert "自动切换下一个 MySQL 账号" in text
    assert "禁止自动重放相同参数" in text
    assert "空数组、0 流量、0 排名结果" in text


def test_ops_xiyou_is_released_as_experimental():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    config = manifest["skills"]["ops-xiyou"]

    assert config["tier"] == "experimental"
    assert all(
        config[key] is True
        for key in ("source", "wheel", "binary", "binary_full")
    )
    assert "xydc MCP 试用通道" in config["reason"]


def test_ops_xiyou_can_be_installed_from_builtin_templates(tmp_path: Path):
    manager = SkillsManager(registry_path=tmp_path / "registry.json")

    result = manager.install(
        "ops-xiyou",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    installed_dir = tmp_path / "skills" / "ops-xiyou"
    assert result.name == "ops-xiyou"
    assert result.to_dict()["version"] == "v1.1.0"
    assert (installed_dir / "SKILL.md").exists()
    assert json.loads(
        (installed_dir / "data" / "VERSION.json").read_text(encoding="utf-8")
    ) == {"name": "ops-xiyou", "version": "v1.1.0"}
