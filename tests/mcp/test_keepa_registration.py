"""通用 MCP Keepa 本地注册测试。"""

from __future__ import annotations

import asyncio
import inspect

from opscli.keepa.mcp_runtime import KeepaMcpRuntime
from opscli.mcp.tools import keepa as keepa_tools


def _run(coro):
    return asyncio.run(coro)


def test_registered_keepa_tool_executes_in_general_mcp(monkeypatch):
    from fastmcp import Client

    from opscli.mcp.server import mcp

    class LocalManager:
        def scenarios(self):
            return [{"scenario_id": "product", "title": "商品详情"}]

    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", LocalManager)

    async def scenario():
        async with Client(mcp) as client:
            return await client.call_tool("keepa_scenarios", {})

    result = _run(scenario())

    assert result.is_error is False
    assert result.data["success"] is True
    assert result.data["data"] == [{"scenario_id": "product", "title": "商品详情"}]
    assert keepa_tools.keepa_scenarios.__module__ == "opscli.mcp.tools.keepa"
    assert (
        getattr(KeepaMcpRuntime.keepa_run, "__opscli_catalog_module__")
        == "keepa"
    )
    assert getattr(KeepaMcpRuntime.keepa_run, "__opscli_skip_quota__", False) is False
    assert "output_dir" not in inspect.signature(KeepaMcpRuntime.keepa_run).parameters
