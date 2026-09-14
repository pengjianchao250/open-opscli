"""西柚 xydc 试用期 MCP 代理工具。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from opscli.xiyou.providers import XydcMcpProvider

from .helpers import _err


def _xydc_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn.__opscli_catalog_module__ = "external_xydc"
    fn.__opscli_telemetry_role__ = "gateway_proxy"
    return fn


async def _call_xydc(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    call_arguments = {key: value for key, value in arguments.items() if value is not None}
    try:
        return await XydcMcpProvider().call(tool_name, call_arguments)
    except Exception as exc:
        return _err(
            exc,
            tool=f"MCP -> ext_xydc_{tool_name}(...)",
            call_params={"argument_names": sorted(call_arguments)},
            feedback_type="query_result",
        )


@_xydc_tool
async def ext_xydc_get_asin_info(asins: list[str], country: str) -> dict[str, Any]:
    """【测试中｜消耗西柚 Credit】仅当用户明确要求使用西柚/xydc 数据时，查询 ASIN 当前商品信息。"""
    return await _call_xydc("get_asin_info", locals())


@_xydc_tool
async def ext_xydc_get_asin_traffic(asins: list[str], country: str) -> dict[str, Any]:
    """【测试中｜消耗西柚 Credit】仅当用户明确要求使用西柚/xydc 数据时，查询 ASIN 近 7 天流量得分。"""
    return await _call_xydc("get_asin_traffic", locals())


@_xydc_tool
async def ext_xydc_get_keyword_info(keywords: list[str], country: str) -> dict[str, Any]:
    """【测试中｜消耗西柚 Credit】仅当用户明确要求使用西柚/xydc 数据时，查询关键词最近一周市场指标。"""
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
    """【测试中｜消耗西柚 Credit】仅当用户明确要求使用西柚/xydc 数据时，查询关键词近 7 天竞争 ASIN。"""
    return await _call_xydc("get_keyword_asin_analysis", locals())


_ALL_TOOLS = [
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
    """向通用 MCP 注册西柚试用工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_READ_ANNOTATIONS)(fn)
