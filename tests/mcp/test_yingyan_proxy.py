"""打包版通用 MCP 的鹰眼代理测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from fastmcp import Client

from opscli.mcp import server as server_module
from opscli.mcp.tools import yingyan_proxy


PND_TOOL_NAMES = {
    "ext_pnd_list_available_datasets",
    "ext_pnd_execute_readonly_sql",
    "ext_pnd_search_similar_terms",
    "ext_pnd_get_report_task_status",
}


def _run(coro):
    return asyncio.run(coro)


def test_default_packaged_server_discovers_all_yingyan_tools(monkeypatch, tmp_path):
    """无部署侧上游配置时，本地打包版仍应暴露四个鹰眼代理 Tool。"""
    monkeypatch.setenv(
        "OPSCLI_MCP_UPSTREAM_CONFIG_PATH",
        str(tmp_path / "missing-mcp-upstreams.json"),
    )

    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    mcp, registrars = server_module._build_server()

    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())
    names = {tool.name for tool in tools}

    assert PND_TOOL_NAMES <= names
    assert yingyan_proxy.register in registrars


def test_deployment_pnd_config_uses_direct_tools_without_proxy(monkeypatch, tmp_path):
    """部署端已有 PND 上游时只注册直连 Tool，避免与本地代理重名。"""
    example_path = Path(__file__).parents[2] / "configs" / "mcp-upstreams.example.json"
    config_path = tmp_path / "mcp-upstreams.json"
    config_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("OPSCLI_MCP_UPSTREAM_CONFIG_PATH", str(config_path))

    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    mcp, registrars = server_module._build_server()

    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())
    names = [tool.name for tool in tools if tool.name in PND_TOOL_NAMES]

    assert set(names) == PND_TOOL_NAMES
    assert len(names) == len(PND_TOOL_NAMES)
    assert yingyan_proxy.register not in registrars


def test_yingyan_proxy_forwards_approved_tool_and_narrow_arguments(monkeypatch):
    """代理只选择 BI 运营系统，并原样转发单次窄查询。"""
    calls = []

    class RecordingConfigClient:
        def fetch_remote_config(self):
            calls.append(("fetch_remote_config",))
            return {"success": True, "data": {}}

        def select_server(self, payload, **kwargs):
            calls.append(("select_server", payload, kwargs))
            return SimpleNamespace(url="https://mcp.example.test/mcp")

    class RecordingRemoteClient:
        def __init__(self, url):
            calls.append(("remote_client", url))

        async def call_tool(self, tool_name, arguments):
            calls.append(("call_tool", tool_name, arguments))
            return {"success": True, "data": [{"asin": "B012345678"}], "error": None}

    monkeypatch.setattr(yingyan_proxy, "McpConfigClient", RecordingConfigClient)
    monkeypatch.setattr(yingyan_proxy, "RemoteMcpClient", RecordingRemoteClient)

    result = _run(
        yingyan_proxy.ext_pnd_execute_readonly_sql(
            "SELECT asin FROM products WHERE site = 'US' AND category_id = 123 LIMIT 20"
        )
    )

    assert result["success"] is True
    assert calls == [
        ("fetch_remote_config",),
        (
            "select_server",
            {"success": True, "data": {}},
            {
                "transport": "http",
                "preferred_name": "BI运营系统",
                "require_preferred": True,
            },
        ),
        ("remote_client", "https://mcp.example.test/mcp"),
        (
            "call_tool",
            "ext_pnd_execute_readonly_sql",
            {
                "sql": "SELECT asin FROM products WHERE site = 'US' "
                "AND category_id = 123 LIMIT 20"
            },
        ),
    ]


def test_yingyan_proxy_returns_stable_error_without_retry(monkeypatch):
    """中央 MCP 不可用时返回稳定错误，且同一调用不自动重放。"""
    attempts = 0

    class BrokenConfigClient:
        def fetch_remote_config(self):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("sensitive backend detail")

    monkeypatch.setattr(yingyan_proxy, "McpConfigClient", BrokenConfigClient)

    result = _run(yingyan_proxy.ext_pnd_list_available_datasets())

    assert attempts == 1
    assert result["success"] is False
    assert result["error"] == {
        "code": "YINGYAN_MCP_UNAVAILABLE",
        "message": "鹰眼远程 MCP 不可用：RuntimeError",
    }
    assert "sensitive backend detail" not in json.dumps(result, ensure_ascii=False)


def test_yingyan_proxy_enforces_one_shared_deadline_without_retry(monkeypatch):
    """配置读取和远端调用共享一个截止时间，超时后不重放。"""
    attempts = 0

    class RecordingConfigClient:
        def fetch_remote_config(self):
            return {"success": True, "data": {}}

        def select_server(self, payload, **kwargs):
            return SimpleNamespace(url="https://mcp.example.test/mcp")

    class SlowRemoteClient:
        def __init__(self, url):
            self.url = url

        async def call_tool(self, tool_name, arguments):
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(1)
            return {"success": True, "data": {}, "error": None}

    monkeypatch.setattr(yingyan_proxy, "McpConfigClient", RecordingConfigClient)
    monkeypatch.setattr(yingyan_proxy, "RemoteMcpClient", SlowRemoteClient)
    monkeypatch.setattr(yingyan_proxy, "TOTAL_TIMEOUT_SECONDS", 0.01)

    result = _run(yingyan_proxy.ext_pnd_list_available_datasets())

    assert attempts == 1
    assert result["success"] is False
    assert result["error"] == {
        "code": "YINGYAN_MCP_TIMEOUT",
        "message": "鹰眼远程 MCP 超过总截止时间",
    }


def test_yingyan_proxy_tools_are_readonly_gateway_tools():
    """代理由远端执行和计量，本地不重复扣额度。"""
    assert {tool.__name__ for tool in yingyan_proxy._ALL_TOOLS} == PND_TOOL_NAMES
    assert all(
        getattr(tool, "__opscli_skip_quota__", False)
        for tool in yingyan_proxy._ALL_TOOLS
    )
    assert all(
        getattr(tool, "__opscli_catalog_module__", None) == "external_pnd"
        for tool in yingyan_proxy._ALL_TOOLS
    )
    assert all(
        getattr(tool, "__opscli_telemetry_role__", None) == "gateway_proxy"
        for tool in yingyan_proxy._ALL_TOOLS
    )
