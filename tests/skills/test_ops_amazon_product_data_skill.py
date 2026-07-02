from pathlib import Path


SKILL_PATH = Path("opscli/skills/templates/ops-amazon-product-data/SKILL.md")


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    assert start != -1, f"missing section: {heading}"
    next_start = text.find("\n## ", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def test_cli_path_documents_auth_and_remote_mcp_config_exchange():
    text = _skill_text()
    cli_section = _section(text, "CLI 授权与执行流程")

    assert "opscli auth token status" in cli_section
    assert "opscli auth login" in cli_section
    assert "opscli scrape-do scenarios" in cli_section
    assert "opscli scrape-do run" in cli_section
    assert "opscli scrape-do job-status" in cli_section
    assert "opscli scrape-do export" in cli_section
    assert "本地登录态" in cli_section
    assert "远端 MCP 配置/API Key" in cli_section
    assert "不要要求用户提供 API Key" in cli_section
    assert "不要手动拼接远端 MCP URL" in cli_section


def test_mcp_tools_are_limited_to_mcp_direct_path():
    text = _skill_text()
    route_section = _section(text, "运行路径选择")
    cli_section = _section(text, "CLI 授权与执行流程")
    mcp_section = _section(text, "MCP 授权与执行流程")

    assert "CLI 优先" in route_section
    assert "MCP 直连" in route_section
    assert "scrape_do_spec_must_read" not in cli_section
    assert "scrape_do_scenarios" not in cli_section
    assert "scrape_do_spec_must_read" in mcp_section
    assert "scrape_do_scenarios" in mcp_section
    assert "scrape_do_run()" in mcp_section
    assert "scrape_do_job_status" in mcp_section
    assert "scrape_do_export" in mcp_section


def test_mcp_direct_path_documents_auth_status_before_product_data_tools():
    text = _skill_text()
    mcp_section = _section(text, "MCP 授权与执行流程")

    assert "auth_is_authenticated()" in mcp_section
    assert "auth_mcp_login()" in mcp_section
    assert mcp_section.index("auth_is_authenticated()") < mcp_section.index("scrape_do_spec_must_read")
    assert mcp_section.index("auth_mcp_login()") < mcp_section.index("scrape_do_spec_must_read")


def test_skill_does_not_make_mcp_spec_tools_universal_prerequisites():
    text = _skill_text()

    forbidden_phrases = [
        "首次使用本能力时，先调用",
        "这两个工具是当前 Amazon 商品数据接口的 MCP 入口",
        "调用 `scrape_do_spec_must_read` 和 `scrape_do_scenarios`。",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in text
