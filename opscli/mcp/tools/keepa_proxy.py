"""通用 MCP 到 Collector MCP 的 Keepa 静默代理。"""

from __future__ import annotations

from typing import Any

from opscli.mcp_client import RemoteMcpClient

from .collector_proxy import call_collector, collector_proxy_tool

_mark_proxy_tool = collector_proxy_tool("keepa")


async def _call_collector(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return await call_collector(
        tool_name,
        arguments,
        client_factory=RemoteMcpClient,
    )


@_mark_proxy_tool
async def keepa_spec_must_read() -> dict:
    """通过 Collector 读取 Keepa MCP 使用规范。"""
    return await _call_collector("keepa_spec_must_read", {})


@_mark_proxy_tool
async def keepa_scenarios() -> dict:
    """通过 Collector 列出 Keepa 场景。"""
    return await _call_collector("keepa_scenarios", {})


@_mark_proxy_tool
async def keepa_quota_status() -> dict:
    """通过 Collector 读取 Keepa 每日额度快照。"""
    return await _call_collector("keepa_quota_status", {})


@_mark_proxy_tool
async def keepa_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    export_format: str = "xls",
    job_id: str | None = None,
    reserve_tokens: int | None = None,
    force: bool = False,
    wait: bool = False,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 Collector 执行 Keepa 场景。"""
    return await _call_collector("keepa_run", locals())


@_mark_proxy_tool
async def keepa_job_status(job_id: str) -> dict:
    """通过 Collector 读取 Keepa 任务结果。"""
    return await _call_collector("keepa_job_status", locals())


@_mark_proxy_tool
async def keepa_export(job_id: str) -> dict:
    """通过 Collector 读取 Keepa 导出文件。"""
    return await _call_collector("keepa_export", locals())


_ALL_TOOLS = [
    keepa_spec_must_read,
    keepa_scenarios,
    keepa_quota_status,
    keepa_run,
    keepa_job_status,
    keepa_export,
]


def register(mcp: Any) -> None:
    """向通用 MCP 注册 Keepa Collector 代理工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
