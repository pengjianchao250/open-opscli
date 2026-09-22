"""西柚正式 OpenAPI 的 MCP 入口，旧供应商 MCP 传输已废弃。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from opscli.xiyou.providers.xydc_openapi import (
    XydcOpenApiError,
    XydcOpenApiProvider,
    list_operations,
)

from .helpers import _err


def _xydc_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn.__opscli_catalog_module__ = "external_xydc"
    fn.__opscli_telemetry_role__ = "gateway_proxy"
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


_OPENAPI_OPERATION_NAMES = Literal[
    "asin_traffic",
    "asin_info_change_daily",
    "asin_traffic_score_daily",
    "asin_traffic_score_weekly",
    "asin_traffic_score_monthly",
    "asin_advertising_change_daily",
    "asin_bsr_daily",
    "asin_orders_trends",
    "asin_info_trends_daily",
    "asin_research_period",
    "asin_research_monthly",
    "asin_info",
    "asin_orders",
    "asin_variations",
    "asin_search_terms_traffic_daily",
    "asin_search_terms_rank_daily",
    "asin_search_terms_rank_hourly",
    "search_terms_aba_weekly",
    "search_terms_info",
    "search_terms_analysis_period",
    "search_terms_analysis_monthly",
    "client_quota",
]


@_xydc_tool
async def ext_xydc_openapi_operations() -> dict[str, Any]:
    """列出西柚找词/西柚洞察（Xiyou、xydc、xydx）的 OpenAPI 目录与必填字段，涵盖关键词搜索量、ABA、CPC、反查词、排名趋势及商品数据；本工具仅查看目录。"""
    return {"success": True, "data": list_operations(), "error": None, "source": "xydc_openapi"}


@_xydc_tool
async def ext_xydc_openapi_call(
    operation: _OPENAPI_OPERATION_NAMES,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，查询反查关键词、ABA周趋势、关键词月度竞争、ASIN词排名/流量趋势等；operation 和 payload 按接口目录传入。"""
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
