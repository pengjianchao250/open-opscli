"""西柚正式 OpenAPI 的 MCP 入口，旧供应商 MCP 传输已废弃。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from opscli.xiyou.contracts import XydcOperation
from opscli.xiyou.providers.xydc_openapi import (
    LEGACY_OPERATION_ALIASES,
    OPERATIONS,
    PUBLIC_OPERATION_NAMES,
    XydcOpenApiError,
    XydcOpenApiProvider,
    list_operations,
)

from .helpers import _err


_COMPATIBILITY_TOOL_OPERATIONS = {
    "ext_xydc_get_asin_info": "get_asin_info",
    "ext_xydc_get_asin_traffic": "get_asin_traffic",
    "ext_xydc_get_keyword_info": "get_keyword_info",
    "ext_xydc_get_keyword_asin_analysis": "get_keyword_asin_analysis",
}


def _xydc_telemetry_dimensions(
    arguments: dict[str, Any],
    *,
    tool_name: str,
) -> dict[str, str]:
    """把西柚 MCP 入口归一为可聚合的正式 OpenAPI 场景。"""
    operation = arguments.get("operation")
    if operation is None:
        operation = _COMPATIBILITY_TOOL_OPERATIONS.get(tool_name)
    normalized = LEGACY_OPERATION_ALIASES.get(str(operation or "").strip(), str(operation or "").strip())
    dimensions = {"provider": "xydc_openapi"}
    if normalized in OPERATIONS:
        dimensions["scenario"] = normalized
        dimensions["endpoint"] = OPERATIONS[normalized].endpoint
    return dimensions


def _xydc_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn.__opscli_catalog_module__ = "external_xydc"
    fn.__opscli_telemetry_role__ = "gateway_proxy"
    fn.__opscli_telemetry_dimension_resolver__ = lambda arguments: _xydc_telemetry_dimensions(
        arguments,
        tool_name=fn.__name__,
    )
    return fn


async def _call_xydc(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    call_arguments = {key: value for key, value in arguments.items() if value is not None}
    try:
        return await XydcOpenApiProvider().call(tool_name, call_arguments)
    except Exception as exc:
        return _err(
            exc,
            tool=f"MCP -> ext_xydc_{tool_name}(...)",
            call_params={"argument_names": sorted(call_arguments)},
            feedback_type="query_result",
        )

@_xydc_tool
async def ext_xydc_openapi_operations() -> dict[str, Any]:
    """列出西柚找词/西柚洞察（Xiyou、xydc、xydx）的 OpenAPI 目录与必填字段，涵盖关键词搜索量、ABA、CPC、反查词、排名趋势及商品数据；本工具仅查看目录。"""
    return {"success": True, "data": list_operations(), "error": None, "source": "xydc_openapi"}


@_xydc_tool
async def ext_xydc_openapi_call(
    operation: XydcOperation,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，查询反查关键词、ABA周趋势、关键词月度竞争、ASIN词排名/流量趋势等；operation 和 payload 按接口目录传入。"""
    if operation not in PUBLIC_OPERATION_NAMES:
        return _err(
            XydcOpenApiError(
                "XYDC_OPENAPI_INTERNAL_OPERATION",
                "该西柚 OpenAPI 操作仅供服务端内部逻辑使用",
            ),
            tool=f"MCP -> ext_xydc_openapi_call({operation})",
            call_params={"operation": operation},
            feedback_type="query_result",
        )
    try:
        return await XydcOpenApiProvider().call(operation, payload)
    except XydcOpenApiError as exc:
        return _err(
            exc,
            tool=f"MCP -> ext_xydc_openapi_call({operation})",
            call_params={"operation": operation, "payload": payload},
            feedback_type="query_result",
        )
    except Exception as exc:
        return _err(
            exc,
            tool=f"MCP -> ext_xydc_openapi_call({operation})",
            call_params={"operation": operation, "payload": payload},
            feedback_type="query_result",
        )


@_xydc_tool
async def ext_xydc_get_asin_info(asins: list[str], country: str) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，查询 ASIN 当前标题、价格、评分、评分数和主图。"""
    return await _call_xydc("get_asin_info", locals())


@_xydc_tool
async def ext_xydc_get_asin_traffic(asins: list[str], country: str) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，查询 ASIN 近7天自然、广告和总流量得分。"""
    return await _call_xydc("get_asin_traffic", locals())


@_xydc_tool
async def ext_xydc_get_keyword_info(keywords: list[str], country: str) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，查词/搜词：查询 Amazon 关键词最近一周搜索量、ABA排名、竞争难度、点击转化率、CPC及建议竞价。"""
    return await _call_xydc("get_keyword_info", locals())


@_xydc_tool
async def ext_xydc_get_keyword_asin_analysis(
    keyword: str,
    country: str,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=100)] = 20,
    sort_field: str = "traffic",
    sort_order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，分析关键词近7天竞争ASIN、自然/广告排名和流量，回答这个词有哪些竞品、哪些ASIN在抢流量。"""
    return await _call_xydc("get_keyword_asin_analysis", locals())


_ALL_TOOLS = [
    ext_xydc_openapi_operations,
    ext_xydc_openapi_call,
    ext_xydc_get_asin_info,
    ext_xydc_get_asin_traffic,
    ext_xydc_get_keyword_info,
    ext_xydc_get_keyword_asin_analysis,
]

_NETWORK_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def register(mcp) -> None:
    """向通用 MCP 注册正式 API 目录、通用调用及四个兼容入口。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_READ_ANNOTATIONS)(fn)
