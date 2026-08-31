"""通用 MCP 到 Collector MCP 的共享代理基础设施。"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from opscli.mcp.context import get_current_api_key
from opscli.mcp_client import RemoteMcpClient

from .helpers import _err

ENV_COLLECTOR_MCP_URL = "OPSCLI_COLLECTOR_MCP_URL"


class CollectorMcpProxyError(Exception):
    """Collector MCP 代理配置或调用错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        """返回稳定的 MCP 错误结构。"""
        return {"code": self.code, "message": str(self)}


async def call_collector(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    client_factory: Callable[..., RemoteMcpClient] = RemoteMcpClient,
) -> dict[str, Any]:
    """以当前最终用户身份调用 Collector 的同名 Tool。"""
    try:
        url = _collector_url()
        api_key = _current_api_key()
        client = client_factory(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return await client.call_tool(tool_name, _proxy_arguments(arguments))
    except CollectorMcpProxyError as exc:
        return _err(exc, tool=f"MCP → {tool_name}（Collector 代理）")
    except Exception as exc:  # noqa: BLE001
        if _is_collector_unavailable(exc):
            error = CollectorMcpProxyError(
                "COLLECTOR_MCP_UNAVAILABLE",
                f"数据采集服务不可用：{type(exc).__name__}",
            )
        else:
            error = CollectorMcpProxyError(
                "COLLECTOR_MCP_CALL_FAILED",
                f"数据采集服务调用失败：{type(exc).__name__}",
            )
        return _err(error, tool=f"MCP → {tool_name}（Collector 代理）")


def collector_proxy_tool(
    module_name: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """标记代理 Tool 的额度归属和稳定 Catalog 模块名。"""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__opscli_skip_quota__ = True
        fn.__opscli_catalog_module__ = module_name
        # 网关和 Collector 都会上报遥测；显式角色让统计只计实际执行入口。
        fn.__opscli_telemetry_role__ = "gateway_proxy"
        return fn

    return decorate


def _collector_url() -> str:
    url = os.environ.get(ENV_COLLECTOR_MCP_URL, "").strip()
    if not url:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_CONFIG_MISSING",
            f"缺少 {ENV_COLLECTOR_MCP_URL}，无法访问数据采集服务",
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_CONFIG_INVALID",
            f"{ENV_COLLECTOR_MCP_URL} 必须是有效的 HTTP(S) MCP 地址",
        )
    query_names = {name.strip().lower() for name, _ in parse_qsl(parsed.query)}
    if "api_key" in query_names:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_CONFIG_INVALID",
            f"{ENV_COLLECTOR_MCP_URL} 不得包含共享 api_key",
        )
    return url


def _current_api_key() -> str:
    api_key = str(get_current_api_key() or "").strip()
    if not api_key:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_IDENTITY_MISSING",
            "当前 MCP 请求缺少用户 API Key，已阻止访问数据采集服务",
        )
    return api_key


def _proxy_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in arguments.items()
        if value is not None and key not in {"session_id", "jwt"}
    }


def _is_collector_unavailable(error: BaseException) -> bool:
    """遍历显式/隐式异常链和异常组，识别连接与超时故障。

    异常链可能形成重复引用，因此按对象 ID 去重；只把网络不可达归为
    unavailable，其他远端执行错误统一保留为 call_failed。
    """
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
