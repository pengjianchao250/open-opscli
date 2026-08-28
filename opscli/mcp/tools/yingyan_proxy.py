"""打包版通用 MCP 到中央鹰眼 Tool 的只读代理。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import anyio
import httpx
from mcp.types import ToolAnnotations
from pydantic import Field

from opscli.mcp_client import McpConfigClient, RemoteMcpClient

from .helpers import _err

TOTAL_TIMEOUT_SECONDS = 30.0


class YingyanMcpProxyError(Exception):
    """鹰眼中央 MCP 配置或调用错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        """返回不包含远端地址和原始响应的稳定错误。"""
        return {"code": self.code, "message": str(self)}


async def _call_yingyan(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """通过 OPS 配置中心选择 BI 运营系统并调用一次鹰眼 Tool。"""
    try:
        with anyio.fail_after(TOTAL_TIMEOUT_SECONDS):
            try:
                config_client = McpConfigClient()
                payload = await anyio.to_thread.run_sync(
                    config_client.fetch_remote_config
                )
                server = config_client.select_server(
                    payload,
                    transport="http",
                    preferred_name="BI运营系统",
                    require_preferred=True,
                )
            except Exception as exc:  # noqa: BLE001
                return _proxy_error(tool_name, arguments, exc, unavailable=True)

            try:
                client = RemoteMcpClient(server.url)
                return await client.call_tool(tool_name, _proxy_arguments(arguments))
            except Exception as exc:  # noqa: BLE001
                return _proxy_error(
                    tool_name,
                    arguments,
                    exc,
                    unavailable=_is_remote_unavailable(exc),
                )
    except TimeoutError:
        error = YingyanMcpProxyError(
            "YINGYAN_MCP_TIMEOUT",
            "鹰眼远程 MCP 超过总截止时间",
        )
        return _err(
            error,
            tool=f"MCP → {tool_name}（鹰眼代理）",
            call_params={"argument_names": sorted(_proxy_arguments(arguments))},
        )


def _proxy_error(
    tool_name: str,
    arguments: dict[str, Any],
    exc: Exception,
    *,
    unavailable: bool,
) -> dict[str, Any]:
    code = "YINGYAN_MCP_UNAVAILABLE" if unavailable else "YINGYAN_MCP_CALL_FAILED"
    subject = "不可用" if unavailable else "调用失败"
    error = YingyanMcpProxyError(
        code,
        f"鹰眼远程 MCP {subject}：{type(exc).__name__}",
    )
    return _err(
        error,
        tool=f"MCP → {tool_name}（鹰眼代理）",
        call_params={"argument_names": sorted(_proxy_arguments(arguments))},
    )


def _proxy_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if value is not None}


def _is_remote_unavailable(error: BaseException) -> bool:
    """识别异常链中的连接和超时故障。"""
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            pending.append(context)
        nested = getattr(current, "exceptions", None)
        if isinstance(nested, tuple):
            pending.extend(item for item in nested if isinstance(item, BaseException))
    return False


def _yingyan_proxy_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """标记中央代理的 Catalog、额度和遥测归属。"""
    fn.__opscli_skip_quota__ = True
    fn.__opscli_catalog_module__ = "external_pnd"
    fn.__opscli_telemetry_role__ = "gateway_proxy"
    return fn


@_yingyan_proxy_tool
async def ext_pnd_list_available_datasets() -> dict:
    """仅当用户明确提到“鹰眼”时，查询可访问的鹰眼数据集目录。"""
    return await _call_yingyan("ext_pnd_list_available_datasets", {})


@_yingyan_proxy_tool
async def ext_pnd_execute_readonly_sql(sql: str) -> dict:
    """仅当用户明确提到“鹰眼”时，执行已收窄且经过校验的只读 SQL。"""
    return await _call_yingyan("ext_pnd_execute_readonly_sql", locals())


@_yingyan_proxy_tool
async def ext_pnd_search_similar_terms(
    search_term: str,
    site: str | None = None,
    top: Annotated[int | None, Field(ge=1, le=1100)] = None,
) -> dict:
    """仅当用户明确提到“鹰眼”时，按站点和种子词查询相似搜索词。"""
    return await _call_yingyan("ext_pnd_search_similar_terms", locals())


@_yingyan_proxy_tool
async def ext_pnd_get_report_task_status(task_id: str) -> dict:
    """仅当用户明确提到“鹰眼”时，查询已有报告任务的状态。"""
    return await _call_yingyan("ext_pnd_get_report_task_status", locals())


_ALL_TOOLS = [
    ext_pnd_list_available_datasets,
    ext_pnd_execute_readonly_sql,
    ext_pnd_search_similar_terms,
    ext_pnd_get_report_task_status,
]

_NETWORK_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def register(mcp) -> None:
    """向未配置 PND 直连上游的通用 MCP 注册中央代理 Tool。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_READ_ANNOTATIONS)(fn)
