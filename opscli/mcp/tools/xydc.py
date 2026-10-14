"""西柚正式 OpenAPI 的 MCP 入口，旧供应商 MCP 传输已废弃。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import ToolAnnotations

from opscli.xiyou.contracts import XydcOperation
from opscli.xiyou.providers.xydc_openapi import (
    OPERATIONS,
    PUBLIC_OPERATION_NAMES,
    XydcOpenApiError,
    XydcOpenApiProvider,
    list_operations,
)

from .helpers import _err


def _xydc_telemetry_dimensions(arguments: dict[str, Any]) -> dict[str, str]:
    """按正式 operation 记录场景与接口，目录调用只记录 Provider。"""
    operation = str(arguments.get("operation") or "").strip()
    dimensions = {"provider": "xydc_openapi"}
    if operation in OPERATIONS:
        dimensions["scenario"] = operation
        dimensions["endpoint"] = OPERATIONS[operation].endpoint
    return dimensions


def _xydc_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn.__opscli_catalog_module__ = "external_xydc"
    fn.__opscli_telemetry_role__ = "gateway_proxy"
    fn.__opscli_telemetry_dimension_resolver__ = _xydc_telemetry_dimensions
    return fn


@_xydc_tool
async def ext_xydc_openapi_operations() -> dict[str, Any]:
    """列出西柚找词/西柚洞察（Xiyou、xydc、xydx）的 OpenAPI 目录、必填字段、payload_schema、example_payload、constraints 与官方文档链接，涵盖关键词搜索量、ABA、CPC、反查词、排名趋势及商品数据；本工具仅查看目录。"""
    return {"success": True, "data": list_operations(), "error": None, "source": "xydc_openapi"}


@_xydc_tool
async def ext_xydc_openapi_call(
    operation: XydcOperation,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """【OpenAPI｜消耗西柚 Credit】用户已选择西柚找词/西柚洞察（Xiyou、xydc、xydx）时，统一查询商品、流量、关键词搜索量/ABA/CPC、竞争ASIN、反查词、排名趋势、订单和变体；operation 和 payload 按 ext_xydc_openapi_operations 目录传入。"""
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


_ALL_TOOLS = [
    ext_xydc_openapi_operations,
    ext_xydc_openapi_call,
]

_NETWORK_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def register(mcp) -> None:
    """仅注册正式 API 目录与通用查询，所有业务按 operation 区分。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_READ_ANNOTATIONS)(fn)
