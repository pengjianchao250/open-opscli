"""通用 MCP 卖家精灵静默代理测试。"""

from __future__ import annotations

import asyncio

import httpx

from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.tools import seller_sprite_proxy


def _run(coro):
    return asyncio.run(coro)


class RecordingRemoteClient:
    """记录通用 MCP 到 Collector 的转发内容。"""

    calls: list[dict] = []

    def __init__(self, url: str, *, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = headers or {}

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append(
            {
                "url": self.url,
                "headers": self.headers,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        return {"success": True, "data": {"proxied": True}, "error": None}


def test_proxy_forwards_current_user_identity_and_arguments(monkeypatch):
    RecordingRemoteClient.calls = []
    monkeypatch.setenv(
        "OPSCLI_COLLECTOR_MCP_URL",
        "http://127.0.0.1:8766/mcp",
    )
    monkeypatch.setattr(seller_sprite_proxy, "RemoteMcpClient", RecordingRemoteClient)
    token = mcp_request_ctx.set(
        {
            "api_key": "mcp-user-key",
            "auth_mode": "remote",
            "user_id": "101",
            "email": "user@example.com",
        }
    )

    try:
        result = _run(
            seller_sprite_proxy.seller_sprite_run(
                scenario="keyword-reverse",
                params={"asin": "B012345678"},
                site="US",
                period="30d",
                page_size=100,
                export_format="xls",
                page_prepare=True,
                output_dir=None,
                job_id="job-1",
                session_id="must-not-forward",
                jwt="must-not-forward",
            )
        )
    finally:
        mcp_request_ctx.reset(token)

    assert result["success"] is True
    assert RecordingRemoteClient.calls == [
        {
            "url": "http://127.0.0.1:8766/mcp",
            "headers": {"Authorization": "Bearer mcp-user-key"},
            "tool_name": "seller_sprite_run",
            "arguments": {
                "scenario": "keyword-reverse",
                "params": {"asin": "B012345678"},
                "site": "US",
                "period": "30d",
                "page_size": 100,
                "export_format": "xls",
                "page_prepare": True,
                "job_id": "job-1",
            },
        }
    ]


def test_proxy_requires_collector_url(monkeypatch):
    monkeypatch.delenv("OPSCLI_COLLECTOR_MCP_URL", raising=False)
    token = mcp_request_ctx.set({"api_key": "mcp-user-key"})

    try:
        result = _run(seller_sprite_proxy.seller_sprite_scenarios())
    finally:
        mcp_request_ctx.reset(token)

    assert result["success"] is False
    assert result["error"]["code"] == "COLLECTOR_MCP_CONFIG_MISSING"


def test_proxy_requires_current_user_api_key(monkeypatch):
    monkeypatch.setenv("OPSCLI_COLLECTOR_MCP_URL", "http://127.0.0.1:8766/mcp")

    result = _run(seller_sprite_proxy.seller_sprite_scenarios())

    assert result["success"] is False
    assert result["error"]["code"] == "COLLECTOR_MCP_IDENTITY_MISSING"


def test_proxy_rejects_shared_api_key_in_collector_url(monkeypatch):
    monkeypatch.setenv(
        "OPSCLI_COLLECTOR_MCP_URL",
        "http://127.0.0.1:8766/mcp?api_key=shared-key",
    )
    token = mcp_request_ctx.set({"api_key": "mcp-user-key"})

    try:
        result = _run(seller_sprite_proxy.seller_sprite_scenarios())
    finally:
        mcp_request_ctx.reset(token)

    assert result["success"] is False
    assert result["error"]["code"] == "COLLECTOR_MCP_CONFIG_INVALID"


def test_proxy_returns_unavailable_without_local_fallback(monkeypatch):
    class UnavailableRemoteClient:
        def __init__(self, url: str, *, headers: dict[str, str] | None = None) -> None:
            self.url = url
            self.headers = headers

        async def call_tool(self, tool_name: str, arguments: dict) -> dict:
            request = httpx.Request("POST", self.url)
            raise ExceptionGroup(
                "collector transport failed",
                [httpx.ConnectError("collector stopped", request=request)],
            )

    monkeypatch.setenv("OPSCLI_COLLECTOR_MCP_URL", "http://127.0.0.1:8766/mcp")
    monkeypatch.setattr(seller_sprite_proxy, "RemoteMcpClient", UnavailableRemoteClient)
    token = mcp_request_ctx.set({"api_key": "mcp-user-key"})

    try:
        result = _run(seller_sprite_proxy.seller_sprite_scenarios())
    finally:
        mcp_request_ctx.reset(token)

    assert result["success"] is False
    assert result["error"]["code"] == "COLLECTOR_MCP_UNAVAILABLE"


def test_registered_proxy_returns_unavailable_without_local_execution(monkeypatch):
    from fastmcp import Client

    from opscli.mcp.server import mcp

    class UnavailableRemoteClient:
        def __init__(self, url: str, *, headers: dict[str, str] | None = None) -> None:
            self.url = url

        async def call_tool(self, tool_name: str, arguments: dict) -> dict:
            request = httpx.Request("POST", self.url)
            raise httpx.ConnectError("collector stopped", request=request)

    def fail_local_execution(*args, **kwargs):
        raise AssertionError("通用 MCP 不应执行本地 SellerSprite")

    async def allow_all():
        return None

    monkeypatch.setenv("OPSCLI_COLLECTOR_MCP_URL", "http://127.0.0.1:8766/mcp")
    monkeypatch.setattr(seller_sprite_proxy, "RemoteMcpClient", UnavailableRemoteClient)
    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    monkeypatch.setattr(
        "opscli.seller_sprite.services.SellerSpriteApiManager",
        fail_local_execution,
    )
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        fail_local_execution,
    )
    token = mcp_request_ctx.set({"api_key": "mcp-user-key"})

    async def scenario():
        async with Client(mcp) as client:
            return await client.call_tool("seller_sprite_scenarios", {})

    try:
        result = _run(scenario())
    finally:
        mcp_request_ctx.reset(token)

    assert result.is_error is False
    assert result.data["success"] is False
    assert result.data["error"]["code"] == "COLLECTOR_MCP_UNAVAILABLE"


def test_proxy_tools_skip_common_mcp_quota():
    assert seller_sprite_proxy._ALL_TOOLS
    assert all(
        getattr(tool, "__opscli_skip_quota__", False)
        for tool in seller_sprite_proxy._ALL_TOOLS
    )


def test_registration_does_not_apply_common_mcp_quota(monkeypatch):
    from opscli.mcp import app_factory
    from opscli.mcp.tool_catalog import ToolCatalog

    registered = []

    class FakeMcp:
        def tool(self, *args, **kwargs):
            return lambda fn: registered.append(fn) or fn

    monkeypatch.setattr(
        app_factory,
        "quota_wrap",
        lambda fn: (_ for _ in ()).throw(AssertionError("代理 Tool 不应重复额度包装")),
    )
    monkeypatch.setattr(app_factory, "telemetry_wrap", lambda fn: fn)
    catalog = ToolCatalog()
    proxy = app_factory.InstrumentedMcpProxy(FakeMcp(), catalog=catalog)

    proxy.tool()(seller_sprite_proxy.seller_sprite_run)

    assert registered == [seller_sprite_proxy.seller_sprite_run]
    assert catalog.get_catalog()[0]["module"] == "seller_sprite"
