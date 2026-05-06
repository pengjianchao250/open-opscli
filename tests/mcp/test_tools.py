import asyncio

import httpx
import respx
from fastmcp import Client

from opscli.mcp.context import configure_multi_user
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
    assert "auth_login_start" in names
    assert "auth_token_refresh" in names
    assert "skills_install" in names
    assert "query_simple" in names
    assert "query_chart" in names
    assert "mcp_user_list" not in names


def test_context_parameter_is_not_exposed_in_tool_schema():
    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())

    for tool in tools:
        properties = (tool.inputSchema or {}).get("properties", {})
        assert "ctx" not in properties


@respx.mock
def test_auth_login_poll_pending_returns_without_saving(monkeypatch):
    configure_multi_user(enabled=False)
    monkeypatch.setattr("opscli.auth.OPS_URL", "https://ops.example.com")
    monkeypatch.setattr("opscli.mcp.server.OPS_URL", "https://ops.example.com", raising=False)
    respx.get("https://ops.example.com/v1/cli/device/poll").mock(
        return_value=httpx.Response(200, json={"status": "pending"})
    )

    result = _run(auth_login_poll("dc-abc", timeout=1))

    assert result["success"] is True
    assert result["data"]["status"] == "pending"
