"""仪表盘 MCP 规范工具测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import Client, FastMCP

from opscli.mcp.tools import dashboard as dashboard_tools


def _run(coro):
    """在同步测试中运行异步调用。"""
    return asyncio.run(coro)


def test_dashboard_data_analysis_spec_reads_skill():
    """数据分析规范工具应返回单一 Skill 来源。"""
    result = _run(dashboard_tools.dashboard_data_analysis_spec_must_read())

    assert result["success"] is True
    assert result["error"] is None
    assert "# 仪表盘数据分析" in result["data"]["spec"]
    source = Path(result["data"]["source"])
    assert source.parts[-3:] == ("templates", "ops-dashboard-data-analysis", "SKILL.md")
    assert result["data"]["sources"] == [str(source)]


def test_dashboard_ai_bridge_spec_reads_all_references():
    """Bridge 规范工具应按固定顺序合并入口和三份 reference。"""
    result = _run(dashboard_tools.dashboard_ai_bridge_spec_must_read())

    assert result["success"] is True
    assert result["error"] is None
    assert "# 仪表盘智能编辑" in result["data"]["spec"]
    assert "# Dashboard Operation Standards" in result["data"]["spec"]
    assert "# Bridge Result Protocol" in result["data"]["spec"]
    assert "# Dashboard Tool Flow" in result["data"]["spec"]
    assert [Path(path).name for path in result["data"]["sources"]] == [
        "SKILL.md",
        "dashboard-operation-standards.md",
        "bridge-result-protocol.md",
        "tool-flow.md",
    ]


def test_dashboard_spec_returns_structured_error_when_file_is_missing(monkeypatch, tmp_path: Path):
    """规范文件缺失时应返回统一错误和明确 feedback 工具名。"""
    monkeypatch.setattr(dashboard_tools, "_dashboard_skill_dir", lambda _name: tmp_path / "missing")

    result = _run(dashboard_tools.dashboard_data_analysis_spec_must_read())

    assert result["success"] is False
    assert result["error"]["code"] == "FileNotFoundError"
    assert "dashboard_data_analysis_spec_must_read" in str(result["feedback"])


def test_dashboard_spec_tools_expose_empty_input_schema():
    """两个无参数工具必须暴露空对象输入 Schema。"""
    async def scenario():
        mcp = FastMCP("dashboard-schema-test")
        dashboard_tools.register(mcp)
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())
    by_name = {tool.name: tool for tool in tools}

    for name in (
        "dashboard_data_analysis_spec_must_read",
        "dashboard_ai_bridge_spec_must_read",
    ):
        assert by_name[name].inputSchema == {
            "additionalProperties": False,
            "properties": {},
            "type": "object",
        }
        assert "不会" in (by_name[name].description or "")
