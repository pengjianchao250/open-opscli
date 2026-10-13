"""西柚 OpenAPI 统一入口的注册与转发测试。"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from opscli.mcp import server as server_module
from opscli.mcp.tools import xydc as xydc_tools


XYDC_TOOL_NAMES = {
    "ext_xydc_openapi_operations",
    "ext_xydc_openapi_call",
}
LEGACY_TOOL_NAMES = {
    "ext_xydc_get_asin_info",
    "ext_xydc_get_asin_traffic",
    "ext_xydc_get_keyword_info",
    "ext_xydc_get_keyword_asin_analysis",
}


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("asin_info", {"entities": [{"asin": "B012345678", "country": "US"}]}),
        ("asin_traffic", {"entities": [{"asin": "B012345678", "country": "US"}]}),
        (
            "search_terms_info",
            {
                "country": "US",
                "searchTerms": ["usb c charger"],
                "sort": {"field": "weeklySearchVolume", "order": "desc"},
            },
        ),
        (
            "search_terms_analysis_period",
            {
                "searchTerm": "usb c charger",
                "country": "US",
                "page": 2,
                "pageSize": 5,
                "period": "last7days",
                "sort": {"field": "traffic", "order": "desc"},
            },
        ),
    ],
)
def test_xydc_tool_forwards_frozen_business_arguments(monkeypatch, operation, payload):
    """四种原包装能力使用同一入口，分页与排序原样透传。"""
    calls = []

    class FakeProvider:
        async def call(self, tool_name, arguments):
            calls.append((tool_name, arguments))
            return {"success": True, "data": [], "error": None}

    monkeypatch.setattr(xydc_tools, "XydcOpenApiProvider", FakeProvider)

    result = _run(
        xydc_tools.ext_xydc_openapi_call(operation=operation, payload=payload)
    )

    assert result["success"] is True
    assert calls == [(operation, payload)]
    dimensions = xydc_tools.ext_xydc_openapi_call.__opscli_telemetry_dimension_resolver__(
        {"operation": operation, "payload": payload}
    )
    assert dimensions["scenario"] == operation
    assert dimensions["endpoint"] == xydc_tools.OPERATIONS[operation].endpoint


def test_client_quota_is_rejected_before_provider_call(monkeypatch):
    def forbidden():
        raise AssertionError("内部额度操作不应进入公开 MCP Provider")

    monkeypatch.setattr(xydc_tools, "XydcOpenApiProvider", forbidden)
    result = _run(
        xydc_tools.ext_xydc_openapi_call(
            operation="client_quota",
            payload={},
        )
    )

    assert result["success"] is False
    assert result["error"]["code"] == "XYDC_OPENAPI_INTERNAL_OPERATION"


def test_xydc_tools_have_openapi_description_and_gateway_metadata():
    assert {tool.__name__ for tool in xydc_tools._ALL_TOOLS} == XYDC_TOOL_NAMES
    for tool in xydc_tools._ALL_TOOLS:
        assert "OpenAPI" in (tool.__doc__ or "")
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

    assert {name for name in tools if name.startswith("ext_xydc_")} == XYDC_TOOL_NAMES
    assert LEGACY_TOOL_NAMES.isdisjoint(tools)
    assert xydc_tools.register in registrars
    call_tool = tools["ext_xydc_openapi_call"]
    assert call_tool.inputSchema["required"] == ["operation", "payload"]
    assert call_tool.inputSchema["properties"]["payload"]["type"] == "object"


def test_default_server_registers_full_openapi_operation_contract(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "OPSCLI_MCP_UPSTREAM_CONFIG_PATH",
        str(tmp_path / "missing-mcp-upstreams.json"),
    )

    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    mcp, _registrars = server_module._build_server()

    async def scenario():
        async with Client(mcp) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    tools = _run(scenario())
    operation_tool = tools["ext_xydc_openapi_call"]
    operation_schema = operation_tool.inputSchema["properties"]["operation"]

    assert len(operation_schema["enum"]) == 21
    assert "asin_info" in operation_schema["enum"]
    assert "search_terms_analysis_monthly" in operation_schema["enum"]
    assert "client_quota" not in operation_schema["enum"]
