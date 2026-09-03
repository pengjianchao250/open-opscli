import json
from pathlib import Path

from opscli.skills.services.manager import SkillsManager


SKILL_DIR = Path("opscli/skills/templates/ops-commerce-playbooks")
REFERENCES_DIR = SKILL_DIR / "references"


def test_ops_commerce_playbooks_is_a_lightweight_skill_only():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "不建立独立规划器" in text
    assert "opscli commerce-playbook" not in text
    assert not Path("opscli/commerce_playbooks/planner.py").exists()
    assert "opscli.commerce_playbooks.recipes" not in Path("pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_ops_commerce_playbooks_routes_to_three_operational_cases():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "references/如何找竞品.md" in text
    assert "references/Listing关键词差距.md" in text
    assert "references/多竞品关键词库.md" in text
    assert "事实、判断、动作和验证" in text

    for name in ("如何找竞品.md", "Listing关键词差距.md", "多竞品关键词库.md"):
        assert (REFERENCES_DIR / name).exists()


def test_competitor_case_uses_operational_feedback_instead_of_asin_lookup():
    text = (REFERENCES_DIR / "如何找竞品.md").read_text(encoding="utf-8")

    assert "不能单独回答“谁是这个 ASIN 的竞品”" in text
    assert "keyword-reverse" in text
    assert '"keyword":"desk lamp"' in text
    assert "association-traffic" in text
    assert "ops-amazon-stylesnap" in text
    assert "父体" in text and "变体" in text

    keyword_section = text.split("### 3.", maxsplit=1)[1].split("### 4.", maxsplit=1)[0]
    assert '"asins":["B0XXXXXXXX"]' not in keyword_section


def test_seller_sprite_skill_discloses_asin_filter_semantics():
    skill_text = Path("opscli/skills/templates/ops-seller-sprite/SKILL.md").read_text(
        encoding="utf-8"
    )
    params_text = Path(
        "opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md"
    ).read_text(encoding="utf-8")

    assert "只用于查询指定商品" in skill_text
    assert "结果可能包含父子体或变体" in params_text
    assert "从一个 ASIN 找竞品" in params_text
    assert "ops-commerce-playbooks" in params_text


def test_ops_commerce_playbooks_identity_release_and_install(tmp_path: Path):
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    version = json.loads(
        (SKILL_DIR / "data" / "VERSION.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        Path("opscli/skills/templates/manifest.json").read_text(encoding="utf-8")
    )

    assert text.startswith("---\nname: ops-commerce-playbooks\n")
    assert "version: v0.1.0" in text
    assert version == {"name": "ops-commerce-playbooks", "version": "v0.1.0"}
    assert manifest["skills"]["ops-commerce-playbooks"]["tier"] == "experimental"

    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    result = manager.install(
        "ops-commerce-playbooks",
        skills_dir=str(tmp_path / "skills"),
        force=False,
    )

    installed = tmp_path / "skills" / "ops-commerce-playbooks"
    assert result.name == "ops-commerce-playbooks"
    assert (installed / "SKILL.md").exists()
    assert (installed / "references" / "如何找竞品.md").exists()
