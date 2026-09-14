"""Amazon 评论 MCP 静态规范工具测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import Client, FastMCP

from opscli.mcp.tools import amazon_reviews as amazon_reviews_tools


def _run(coro):
    """在同步测试中运行异步调用。"""
    return asyncio.run(coro)


def test_amazon_reviews_spec_returns_packaged_rules():
    """规范工具应返回稳定逻辑来源和页面工具边界。"""
    result = _run(amazon_reviews_tools.ops_amazon_reviews())

    assert result["success"] is True
    assert result["error"] is None
    assert result["data"]["source"] == "ops-amazon-reviews/SKILL_MCP.md"
    assert result["data"]["sources"] == ["ops-amazon-reviews/SKILL_MCP.md"]
    assert "只返回本静态规范" in result["data"]["spec"]
    assert "不承诺纯 MCP 评论采集能力" in result["data"]["spec"]
    assert 'amazon_reviews_get({"asin":"<NORMALIZED_ASIN>"})' in result["data"]["spec"]


def test_amazon_reviews_spec_reports_missing_package_file(monkeypatch, tmp_path: Path):
    """规范文件缺失时返回统一错误，且不泄露本机物理路径。"""
    monkeypatch.setattr(
        amazon_reviews_tools,
        "_amazon_reviews_skill_dir",
        lambda: tmp_path / "missing",
    )

    result = _run(amazon_reviews_tools.ops_amazon_reviews())

    assert result["success"] is False
    assert result["error"]["code"] == "FileNotFoundError"
    assert str(tmp_path) not in result["error"]["message"]
    assert "ops_amazon_reviews" in str(result["feedback"])


def test_amazon_reviews_spec_exposes_empty_input_schema_only():
    """MCP 仅注册无参数规范入口，不注册评论数据代理。"""
    async def scenario():
        mcp = FastMCP("amazon-reviews-schema-test")
        amazon_reviews_tools.register(mcp)
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())

    assert [tool.name for tool in tools] == ["ops_amazon_reviews"]
    assert tools[0].inputSchema == {
        "additionalProperties": False,
        "properties": {},
        "type": "object",
    }
    assert "不会提供、调用或代理" in (tools[0].description or "")
    assert all(fn.__name__ != "amazon_reviews_get" for fn in amazon_reviews_tools._ALL_TOOLS)
