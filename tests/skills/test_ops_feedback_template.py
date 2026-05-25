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


def test_ops_feedback_skill_requires_interface_level_skill_fields():
    text = (TEMPLATE_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "`skill_name`" in text
    assert "`skill_version`" in text
    assert "`command_name` / `mcp_tool_name`" in text
    assert "不能替代 `skill_name`、`skill_version`、`command_name`、`mcp_tool_name`" in text


def test_ops_feedback_references_do_not_manualize_client_versions():
    combined = "\n".join(
        [
            (TEMPLATE_DIR / "SKILL.md").read_text(encoding="utf-8"),
            (TEMPLATE_DIR / "references" / "cli.md").read_text(encoding="utf-8"),
            (TEMPLATE_DIR / "references" / "mcp.md").read_text(encoding="utf-8"),
        ]
    )

    assert "app_version" in combined
    assert "client_version" in combined
    assert "不要手工传" in combined or "不要传" in combined
    assert '"app_version":' not in combined
    assert '"client_version":' not in combined


def test_ops_feedback_cli_and_mcp_examples_pass_skill_metadata_as_top_level_params():
    cli_text = (TEMPLATE_DIR / "references" / "cli.md").read_text(encoding="utf-8")
    mcp_text = (TEMPLATE_DIR / "references" / "mcp.md").read_text(encoding="utf-8")

    assert '"skill_name": "ops-dataset-query"' in cli_text
    assert '"skill_version": "v1.0.0"' in cli_text
    assert "--skill-name ops-dataset-query" in cli_text
    assert "--skill-version v1.0.0" in cli_text
    assert 'skill_name="ops-dataset-query"' in mcp_text
    assert 'skill_version="v1.0.0"' in mcp_text
    assert 'mcp_tool_name="query_simple"' in mcp_text
