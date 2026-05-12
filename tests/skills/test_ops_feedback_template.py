from pathlib import Path


TEMPLATE_DIR = Path("opscli/skills/templates/ops-feedback")


def test_ops_feedback_skill_frontmatter_uses_supported_fields_only():
    text = (TEMPLATE_DIR / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]

    assert "name: ops-feedback" in frontmatter
    assert "description: Use when" in frontmatter
    assert "version:" not in frontmatter


def test_feedback_rule_has_no_local_config_link():
    text = (TEMPLATE_DIR / "data" / "FEEDBACK_RULE.md").read_text(encoding="utf-8")

    assert ".claude/CLAUDE.md" not in text
    assert "../../../../" not in text


def test_feedback_rule_blocks_recursive_feedback_submission():
    text = (TEMPLATE_DIR / "data" / "FEEDBACK_RULE.md").read_text(encoding="utf-8")

    assert "feedback_submit" in text
    assert "递归反馈" in text
