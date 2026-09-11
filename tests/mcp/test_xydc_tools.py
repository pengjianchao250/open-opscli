"""西柚 xydc 试用工具注册与转发测试。"""

from __future__ import annotations

import asyncio

from fastmcp import Client

from opscli.mcp import server as server_module
from opscli.mcp.tools import xydc as xydc_tools


XYDC_TOOL_NAMES = {
    "ext_xydc_get_asin_info",
    "ext_xydc_get_asin_traffic",
    "ext_xydc_get_keyword_info",
    "ext_xydc_get_keyword_asin_analysis",
}


def _run(coro):
    return asyncio.run(coro)


def test_xydc_tool_forwards_frozen_business_arguments(monkeypatch):
    calls = []

    class FakeProvider:
        async def call(self, tool_name, arguments):
            calls.append((tool_name, arguments))
            return {"success": True, "data": [], "error": None}

    monkeypatch.setattr(xydc_tools, "XydcMcpProvider", FakeProvider)

    result = _run(
        xydc_tools.ext_xydc_get_keyword_asin_analysis(
            keyword="usb c charger",
            country="US",
            page=2,
            page_size=5,
        )
    )

    assert result["success"] is True
    assert calls == [
        (
            "get_keyword_asin_analysis",
            {
                "keyword": "usb c charger",
                "country": "US",
                "page": 2,
                "page_size": 5,
                "sort_field": "traffic",
                "sort_order": "desc",
            },
        )
    ]


def test_xydc_tools_have_testing_description_and_gateway_metadata():
    assert {tool.__name__ for tool in xydc_tools._ALL_TOOLS} == XYDC_TOOL_NAMES
    for tool in xydc_tools._ALL_TOOLS:
        assert (tool.__doc__ or "").startswith("【测试中｜消耗西柚 Credit】")
        assert getattr(tool, "__opscli_catalog_module__", None) == "external_xydc"
        assert getattr(tool, "__opscli_telemetry_role__", None) == "gateway_proxy"
        assert getattr(tool, "__opscli_skip_quota__", False) is False


def test_xydc_tools_register_as_readonly_open_world_tools():
    registrations = []

    class FakeMcp:
        def tool(self, **kwargs):
            def decorator(fn):
                registrations.append((fn, kwargs))
                return fn

            return decorator

    xydc_tools.register(FakeMcp())

    assert {fn.__name__ for fn, _kwargs in registrations} == XYDC_TOOL_NAMES
    for _fn, kwargs in registrations:
        annotations = kwargs["annotations"]
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is True
        assert annotations.openWorldHint is True


def test_default_server_registers_xydc_tools_with_frozen_schemas(monkeypatch, tmp_path):
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

    tools = {tool.name: tool for tool in _run(scenario())}

    assert XYDC_TOOL_NAMES <= set(tools)
    assert xydc_tools.register in registrars
    keyword_tool = tools["ext_xydc_get_keyword_asin_analysis"]
    assert keyword_tool.inputSchema["required"] == ["keyword", "country"]
    assert keyword_tool.inputSchema["properties"]["page"]["minimum"] == 1
    assert keyword_tool.inputSchema["properties"]["page_size"] == {
        "default": 20,
        "maximum": 100,
        "minimum": 1,
        "type": "integer",
    }
