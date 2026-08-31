"""通用 MCP 到 Collector MCP 的卖家精灵静默代理。"""

from __future__ import annotations

from typing import Any
from opscli.mcp_client import RemoteMcpClient

from .collector_proxy import call_collector, collector_proxy_tool


async def _call_collector(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """以当前最终用户身份调用 Collector 的同名 Tool。"""
    return await call_collector(
        tool_name,
        arguments,
        client_factory=RemoteMcpClient,
    )


_mark_proxy_tool = collector_proxy_tool("seller_sprite")


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
