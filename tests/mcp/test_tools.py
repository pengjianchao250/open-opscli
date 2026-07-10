import asyncio

import httpx
import respx
from fastmcp import Client

from opscli.mcp.server import mcp
from opscli.mcp.tools.auth import auth_login_poll


def _run(coro):
    return asyncio.run(coro)


def test_mcp_exposes_expected_tools():
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return tools

    tools = _run(scenario())
    names = [tool.name for tool in tools]

    # 工具总数可能随 amazon/chatgpt 等模块增减而变化，此处只验证核心工具存在
    assert len(names) >= 21
    assert "auth_mcp_login" in names
    assert "auth_token_refresh" in names
    assert "skills_install" in names
    assert "query_simple" in names
    assert "query_chart" in names
    assert "mcp_user_list" not in names


def test_mcp_hides_temporarily_closed_service_tools():
    """Sif / 西柚暂不开放时，不应出现在 MCP tool 列表。"""
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    names = _run(scenario())

    assert "sif_run" not in names
    assert "sif_scenarios" not in names
    assert "xiyou_run" not in names
    assert "xiyou_scenarios" not in names


def test_seller_sprite_internal_controls_are_not_exposed():
    """卖家精灵对 Agent 只暴露业务入口，不暴露异步/采集模式开关。"""
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return tools

    tools = _run(scenario())
    names = [tool.name for tool in tools]
    run_tool = next(tool for tool in tools if tool.name == "seller_sprite_run")
    properties = (run_tool.inputSchema or {}).get("properties", {})

    assert "seller_sprite_run" in names
    assert "seller_sprite_listing_analysis_submit" in names
    assert "seller_sprite_listing_analysis_status" in names
    assert "seller_sprite_listing_analysis_result" in names
    assert "seller_sprite_start" not in names
    assert "mode" not in properties
    assert "async_mode" not in properties


def test_context_parameter_is_not_exposed_in_tool_schema():
    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())

    for tool in tools:
        properties = (tool.inputSchema or {}).get("properties", {})
        assert "ctx" not in properties


def test_auth_mcp_login_has_agent_name_param():
    """auth_mcp_login 暴露 agent_name 参数，便于写入后端审计。"""
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return next(tool for tool in tools if tool.name == "auth_mcp_login")

    tool = _run(scenario())
    properties = (tool.inputSchema or {}).get("properties", {})
    assert "agent_name" in properties


@respx.mock
def test_auth_login_poll_pending_returns_without_saving(monkeypatch):
    monkeypatch.setattr("opscli.auth.OPS_URL", "https://ops.example.com")
    monkeypatch.setattr("opscli.mcp.server.OPS_URL", "https://ops.example.com", raising=False)
    respx.get("https://ops.example.com/v1/cli/device/poll").mock(
        return_value=httpx.Response(200, json={"status": "pending"})
    )

    result = _run(auth_login_poll("dc-abc", timeout=1))

    assert result["success"] is True
    assert result["data"]["status"] == "pending"
