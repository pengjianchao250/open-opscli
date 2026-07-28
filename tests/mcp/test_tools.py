import asyncio

import httpx
import pytest
import respx
from fastmcp import Client

from opscli.mcp.server import mcp
from opscli.mcp.tools.auth import auth_login_poll, auth_me


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _allow_all_tools_without_local_credentials(monkeypatch):
    """注册契约测试不得读取真实本地凭证或受 stdio 权限状态影响。"""
    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)


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
    assert "auth_me" in names
    assert "skills_install" in names
    assert "query_simple" in names
    assert "query_chart" in names
    assert "dashboard_data_analysis_spec_must_read" in names
    assert "dashboard_ai_bridge_spec_must_read" in names
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
    job_status_tool = next(tool for tool in tools if tool.name == "seller_sprite_job_status")
    jobs_status_tool = next(tool for tool in tools if tool.name == "seller_sprite_jobs_status")
    run_properties = (run_tool.inputSchema or {}).get("properties", {})
    job_status_schema = job_status_tool.inputSchema or {}
    jobs_status_schema = jobs_status_tool.inputSchema or {}
    job_status_properties = job_status_schema.get("properties", {})
    jobs_status_properties = jobs_status_schema.get("properties", {})

    assert "seller_sprite_run" in names
    assert "seller_sprite_listing_analysis_submit" in names
    assert "seller_sprite_listing_analysis_status" in names
    assert "seller_sprite_listing_analysis_result" in names
    assert "seller_sprite_job_status" in names
    assert "seller_sprite_jobs_status" in names
    assert "seller_sprite_start" not in names
    assert "mode" not in run_properties
    assert "async_mode" not in run_properties
    assert "wait" not in run_properties
    assert "wait_seconds" not in run_properties
    assert set(job_status_properties) == {"job_id", "wait_seconds"}
    assert job_status_properties["wait_seconds"]["default"] == 0
    assert job_status_schema["required"] == ["job_id"]
    assert set(jobs_status_properties) == {"job_ids", "wait_seconds"}
    assert jobs_status_properties["job_ids"]["items"]["type"] == "string"
    assert jobs_status_properties["wait_seconds"]["default"] == 0
    assert jobs_status_schema["required"] == ["job_ids"]


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


@respx.mock
def test_auth_me_returns_user_info_with_explicit_jwt():
    """显式传 session_id + ops jwt 时，auth_me 应携带该 JWT 调 /me 并返回用户信息。"""
    route = respx.get(url__regex=r".*/api/v1/auth/me$").mock(
        return_value=httpx.Response(200, json={"data": {"email": "mcp@example.com"}})
    )
    result = _run(auth_me(session_id="sid", jwt="ops-jwt"))
    assert result["success"] is True
    assert result["data"]["data"]["email"] == "mcp@example.com"
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer ops-jwt"


@respx.mock
def test_auth_me_exchanges_via_session_when_jwt_missing(monkeypatch):
    """仅传 session_id 时，auth_me 应先经 cli-token 换取 JWT，再调 /me。"""
    # 隔离本地凭证：强制未提供 jwt 时不读本机缓存，走 session 换取路径（铁律8）
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_jwt", lambda *a, **k: None)
    token_route = respx.post(url__regex=r".*/api/v1/auth/cli-token$").mock(
        return_value=httpx.Response(200, json={"jwt": "exchanged-jwt"})
    )
    me_route = respx.get(url__regex=r".*/api/v1/auth/me$").mock(
        return_value=httpx.Response(200, json={"data": {"email": "mcp@example.com"}})
    )
    result = _run(auth_me(session_id="sid-only"))
    assert result["success"] is True
    assert token_route.called
    assert me_route.called
    assert me_route.calls.last.request.headers["Authorization"] == "Bearer exchanged-jwt"
