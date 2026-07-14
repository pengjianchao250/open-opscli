from pathlib import Path

from opscli.asin_data.cli import FileKey, LiveDataReturnMode, LiveDataScope


ROOT = Path(__file__).resolve().parents[2]
CLI_MANUAL = ROOT / "docs" / "guide" / "ASIN取数CLI命令手册.md"
MCP_MANUAL = ROOT / "docs" / "guide" / "ASIN取数MCP工具手册.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cli_manual_covers_public_commands_and_enums():
    content = _read(CLI_MANUAL)

    for command in (
        "opscli asin-data live-data",
        "opscli asin-data fetch-file",
        "opscli asin-data yicopy-keyword-engine",
        "opscli asin-data category-top",
    ):
        assert command in content
    for value in FileKey:
        assert f"`{value.value}`" in content
    for value in LiveDataScope:
        assert f"`{value.value}`" in content
    for value in LiveDataReturnMode:
        assert f"`{value.value}`" in content


def test_mcp_manual_covers_public_tools():
    content = _read(MCP_MANUAL)

    for tool in (
        "asin_data_live_data",
        "asin_data_fetch_file",
        "asin_data_yicopy_keyword_engine",
        "asin_data_category_top",
    ):
        assert f"`{tool}`" in content


def test_manuals_define_auth_and_response_contracts_without_legacy_invocation():
    for path in (CLI_MANUAL, MCP_MANUAL):
        content = _read(path)
        assert '"success": true' in content
        assert '"success": false' in content
        assert '"error"' in content
        assert "polaris_enabled = true" in content
        assert "POLARIS_USER_AUTH_MISSING" in content
        assert "polaris-bjx-token" in content
        assert "asin-data collect" not in content


def test_manuals_define_category_top_leaf_category_workflow():
    category_path = "Home & Kitchen,Furniture,Home Office Furniture,Bookcases"
    for path in (CLI_MANUAL, MCP_MANUAL):
        content = _read(path)
        assert category_path in content
        assert "`类目`" in content
        assert "`Bookcases`" in content
        assert "先调用" in content
        assert "最后一个非空" in content
        assert "不得猜测" in content
