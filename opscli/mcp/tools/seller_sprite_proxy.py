"""通用 MCP 到 Collector MCP 的卖家精灵静默代理。"""

from __future__ import annotations

import os
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


def _collector_url() -> str:
    """读取并校验 Collector 内部地址。"""
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
    """读取需要向 Collector 透传的最终用户 API Key。"""
    api_key = str(get_current_api_key() or "").strip()
    if not api_key:
        raise CollectorMcpProxyError(
            "COLLECTOR_MCP_IDENTITY_MISSING",
            "当前 MCP 请求缺少用户 API Key，已阻止访问数据采集服务",
        )
    return api_key


def _proxy_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """过滤空值及禁止跨服务透传的旧身份参数。"""
    return {
        key: value
        for key, value in arguments.items()
        if value is not None and key not in {"session_id", "jwt"}
    }


def _is_collector_unavailable(error: BaseException) -> bool:
    """识别 MCP SDK 包装前后的连接和超时异常。"""
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


async def _call_collector(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """以当前最终用户身份调用 Collector 的同名 Tool。"""
    try:
        url = _collector_url()
        api_key = _current_api_key()
        client = RemoteMcpClient(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return await client.call_tool(tool_name, _proxy_arguments(arguments))
    except CollectorMcpProxyError as exc:
        return _err(exc, tool=f"MCP → {tool_name}（Collector 代理）")
    except Exception as exc:
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


def _mark_proxy_tool(fn):
    """标记代理 Tool 的额度归属和稳定 Catalog 模块名。"""
    fn.__opscli_skip_quota__ = True
    fn.__opscli_catalog_module__ = "seller_sprite"
    return fn


@_mark_proxy_tool
async def seller_sprite_spec_must_read() -> dict:
    """读取卖家精灵 MCP 使用规范与参数手册。"""
    return await _call_collector("seller_sprite_spec_must_read", {})


@_mark_proxy_tool
async def seller_sprite_scenarios() -> dict:
    """列出卖家精灵场景。"""
    return await _call_collector("seller_sprite_scenarios", {})


@_mark_proxy_tool
async def seller_sprite_quota_status() -> dict:
    """读取当前 MCP 用户的卖家精灵每日额度快照。"""
    return await _call_collector("seller_sprite_quota_status", {})


@_mark_proxy_tool
async def seller_sprite_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    period: str = "30d",
    page_size: int = 100,
    export_format: str = "xls",
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 Collector 执行卖家精灵场景。"""
    return await _call_collector("seller_sprite_run", locals())


@_mark_proxy_tool
async def seller_sprite_listing_analysis_submit(
    asin: str,
    station: str = "GLOBAL",
    site: str = "US",
    export_format: str = "json",
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 Collector 提交 Listing Analysis 任务。"""
    return await _call_collector("seller_sprite_listing_analysis_submit", locals())


@_mark_proxy_tool
async def seller_sprite_listing_analysis_status(
    job_id: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 Collector 读取 Listing Analysis 任务状态。"""
    return await _call_collector("seller_sprite_listing_analysis_status", locals())


@_mark_proxy_tool
async def seller_sprite_listing_analysis_result(
    job_id: str,
    export_format: str = "json",
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 Collector 读取 Listing Analysis 任务结果。"""
    return await _call_collector("seller_sprite_listing_analysis_result", locals())


@_mark_proxy_tool
async def seller_sprite_job_status(job_id: str, wait_seconds: int = 0) -> dict:
    """通过 Collector 读取单个卖家精灵任务状态。"""
    return await _call_collector("seller_sprite_job_status", locals())


@_mark_proxy_tool
async def seller_sprite_jobs_status(
    job_ids: list[str],
    wait_seconds: int = 0,
) -> dict:
    """通过 Collector 批量读取卖家精灵任务状态。"""
    return await _call_collector("seller_sprite_jobs_status", locals())


@_mark_proxy_tool
async def seller_sprite_export(job_id: str) -> dict:
    """通过 Collector 读取卖家精灵任务导出信息。"""
    return await _call_collector("seller_sprite_export", locals())


_ALL_TOOLS = [
    seller_sprite_spec_must_read,
    seller_sprite_scenarios,
    seller_sprite_quota_status,
    seller_sprite_run,
    seller_sprite_listing_analysis_submit,
    seller_sprite_listing_analysis_status,
    seller_sprite_listing_analysis_result,
    seller_sprite_job_status,
    seller_sprite_jobs_status,
    seller_sprite_export,
]


def register(mcp) -> None:
    """向通用 MCP 注册卖家精灵 Collector 代理工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
