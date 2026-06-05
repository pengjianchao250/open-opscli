"""西柚洞察 MCP 工具模块。"""

from __future__ import annotations

from pathlib import Path

from .helpers import _err, _get_auth_pair, _ok


async def xiyou_scenarios() -> dict:
    """列出西柚洞察接口直连场景。"""
    try:
        from opscli.xiyou.services import XiyouApiManager

        return _ok(XiyouApiManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP -> xiyou_scenarios()")


async def xiyou_run(
    function: str,
    provider: str = "xiyou",
    target: str = "asin",
    site: str = "US",
    period: str = "week",
    rank_pattern: str | None = None,
    query: str = "",
    page: int = 1,
    page_size: int = 50,
    export_format: str = "json",
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行西柚洞察接口场景并导出 JSON/XLSX。"""
    try:
        from opscli.xiyou.domain.models import XiyouRankingRequest
        from opscli.xiyou.services import XiyouApiManager

        request = XiyouRankingRequest(
            function=function,
            provider=provider,
            target=target,
            site=site,
            period=period,
            rank_pattern=rank_pattern,
            query=query,
            page=page,
            page_size=page_size,
            job_id=job_id,
            output_dir=output_dir,
            export_format=export_format,
        )
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        result = await XiyouApiManager(jwt=jw, session_id=sid).run(request)
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(
            exc,
            tool="MCP -> xiyou_run(...)",
            call_params={
                "function": function,
                "provider": provider,
                "target": target,
                "site": site,
                "period": period,
                "rank_pattern": rank_pattern,
                "page": page,
                "page_size": page_size,
                "export_format": export_format,
                "job_id": job_id,
            },
        )


async def xiyou_job_status(job_id: str) -> dict:
    """读取西柚洞察任务结果。"""
    try:
        from opscli.xiyou.services import XiyouApiManager

        return _ok(XiyouApiManager().job_status(job_id))
    except Exception as exc:
        return _err(exc, tool="MCP -> xiyou_job_status(...)", call_params={"job_id": job_id})


async def xiyou_export(job_id: str) -> dict:
    """读取西柚洞察任务导出文件信息。"""
    try:
        from opscli.xiyou.services import XiyouApiManager

        status = XiyouApiManager().job_status(job_id)
        export = status.get("export")
        if not export:
            raise ValueError(f"任务无导出文件：{job_id}")
        if export.get("path") and not export.get("url"):
            export["url"] = Path(export["path"]).expanduser().resolve().as_uri()
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP -> xiyou_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    xiyou_scenarios,
    xiyou_run,
    xiyou_job_status,
    xiyou_export,
]


def register(mcp) -> None:
    """向 FastMCP 实例注册西柚洞察工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
