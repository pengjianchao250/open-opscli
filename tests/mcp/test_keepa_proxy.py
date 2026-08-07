"""通用 MCP Keepa 静默代理测试。"""

from __future__ import annotations

import asyncio
import inspect

import httpx

from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.tools import keepa_proxy


def _run(coro):
    return asyncio.run(coro)


class RecordingRemoteClient:
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


def test_keepa_proxy_forwards_identity_and_filters_internal_credentials(monkeypatch):
    RecordingRemoteClient.calls = []
    monkeypatch.setenv("OPSCLI_COLLECTOR_MCP_URL", "http://127.0.0.1:8766/mcp")
    monkeypatch.setattr(keepa_proxy, "RemoteMcpClient", RecordingRemoteClient)
    token = mcp_request_ctx.set({"api_key": "mcp-user-key", "email": "user@example.com"})

    try:
        result = _run(
            keepa_proxy.keepa_run(
                scenario="product",
                params={"asin": "B0088PUEPK"},
                site="US",
                export_format="xls",
                job_id="keepa-job-1",
                reserve_tokens=10,
                force=False,
                wait=False,
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
            "tool_name": "keepa_run",
            "arguments": {
                "scenario": "product",
                "params": {"asin": "B0088PUEPK"},
                "site": "US",
                "export_format": "xls",
                "job_id": "keepa-job-1",
                "reserve_tokens": 10,
                "force": False,
                "wait": False,
            },
        }
    ]


def test_keepa_proxy_tools_skip_general_mcp_quota():
    assert keepa_proxy._ALL_TOOLS
    assert all(
        getattr(tool, "__opscli_skip_quota__", False)
        for tool in keepa_proxy._ALL_TOOLS
    )


def test_keepa_proxy_does_not_expose_server_output_directory():
    assert "output_dir" not in inspect.signature(keepa_proxy.keepa_run).parameters


def test_registered_keepa_tool_does_not_fallback_to_local_execution(monkeypatch):
    from fastmcp import Client

    from opscli.mcp.server import mcp

    class UnavailableRemoteClient:
        def __init__(self, url: str, *, headers: dict[str, str] | None = None) -> None:
            self.url = url

        async def call_tool(self, tool_name: str, arguments: dict) -> dict:
            request = httpx.Request("POST", self.url)
            raise httpx.ConnectError("collector stopped", request=request)

    def fail_local_execution(*args, **kwargs):
        raise AssertionError("通用 MCP 不应执行本地 Keepa")

    async def allow_all():
        return None

    monkeypatch.setenv("OPSCLI_COLLECTOR_MCP_URL", "http://127.0.0.1:8766/mcp")
    monkeypatch.setattr(keepa_proxy, "RemoteMcpClient", UnavailableRemoteClient)
    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    monkeypatch.setattr(
        "opscli.keepa.services.KeepaApiManager",
        fail_local_execution,
    )
    token = mcp_request_ctx.set({"api_key": "mcp-user-key"})

    async def scenario():
        async with Client(mcp) as client:
            return await client.call_tool("keepa_scenarios", {})

    try:
        result = _run(scenario())
    finally:
        mcp_request_ctx.reset(token)

    assert result.is_error is False
    assert result.data["success"] is False
    assert result.data["error"]["code"] == "COLLECTOR_MCP_UNAVAILABLE"
    assert all(
        getattr(tool, "__opscli_catalog_module__", None) == "keepa"
        for tool in keepa_proxy._ALL_TOOLS
    )
