"""西柚洞察 MCP 工具模块。"""

from __future__ import annotations

from pathlib import Path

from .helpers import _err, _get_auth_pair, _ok


def _xiyou_terminal_credential_error(exc: Exception, *, call_params: dict) -> dict | None:
    """将西柚凭据过期返回为终态错误，避免 Agent 误调 OPS auth 工具。"""
    if getattr(exc, "code", None) != "XIYOU_CREDENTIAL_EXPIRED":
        return None
    to_dict = getattr(exc, "to_dict", None)
    error = to_dict() if callable(to_dict) else {"code": "XIYOU_CREDENTIAL_EXPIRED", "message": str(exc)}
    return {
        "success": False,
        "data": None,
        "error": error,
        "next_action": "STOP_AND_WAIT_FOR_XIYOU_CREDENTIAL_UPDATE",
        "retryable": False,
        "do_not_retry": True,
        "do_not_call_tools": ["auth_mcp_login", "auth_get_token", "auth_token_refresh"],
        "agent_message": (
            "西柚业务凭据已过期，企微补登通知已发送。"
            "不要刷新 OPS/MCP 登录，也不要继续重试当前西柚任务；"
            "等待运维在运营后台补登西柚 token/cookie 后，让用户重新发起任务。"
        ),
        "feedback": {
            "feedback_type": "data_issue",
            "severity": "medium",
            "source": "mcp",
            "execution_summary": {
                "summary": "xiyou_run 因西柚业务凭据过期终止，已触发补登通知。",
                "failed_calls": [
                    {
                        "tool": "MCP -> xiyou_run(...)",
                        "call_params": call_params,
                        "error_message": f"{error.get('code')}: {error.get('message')}",
                        "reason": "西柚 authorization/cookie 过期或被服务端判定失效；这不是 OPS/MCP 登录态问题。",
                        "fix_suggestion": "等待运维通过运营后台补登西柚凭据；不要调用 auth_mcp_login/auth_get_token/auth_token_refresh。",
                    }
                ],
                "successful_calls": [],
                "final_resolution": "当前任务已终止，等待西柚凭据更新后由用户重新发起。",
            },
        },
    }


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
    dataset: str | None = None,
    asin: str | None = None,
    asins: list[str] | str | None = None,
    keyword: str | None = None,
    query: str = "",
    parent_asin: str | None = None,
    cycle_period: str | None = None,
    start_month: str | None = None,
    end_month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    report_date: str | None = None,
    search_terms: list[str] | str | None = None,
    view_mode: str | None = None,
    replay_type: str | None = None,
    keyword_type: str | None = None,
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
            dataset=dataset,
            asin=asin,
            asins=asins,
            keyword=keyword,
            query=query,
            parent_asin=parent_asin,
            cycle_period=cycle_period,
            start_month=start_month,
            end_month=end_month,
            start_date=start_date,
            end_date=end_date,
            report_date=report_date,
            search_terms=search_terms,
            view_mode=view_mode,
            replay_type=replay_type,
            keyword_type=keyword_type,
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
        call_params = {
            "function": function,
            "provider": provider,
            "target": target,
            "site": site,
            "period": period,
            "rank_pattern": rank_pattern,
            "dataset": dataset,
            "asin": asin,
            "asins": asins,
            "keyword": keyword,
            "query": query,
            "parent_asin": parent_asin,
            "page": page,
            "page_size": page_size,
            "cycle_period": cycle_period,
            "start_month": start_month,
            "end_month": end_month,
            "start_date": start_date,
            "end_date": end_date,
            "report_date": report_date,
            "search_terms": search_terms,
            "view_mode": view_mode,
            "replay_type": replay_type,
            "keyword_type": keyword_type,
            "export_format": export_format,
            "job_id": job_id,
        }
        terminal_error = _xiyou_terminal_credential_error(exc, call_params=call_params)
        if terminal_error:
            return terminal_error
        return _err(exc, tool="MCP -> xiyou_run(...)", call_params=call_params)


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
        export = dict(status.get("export") or {})
        if not export:
            raise ValueError(f"任务无导出文件：{job_id}")
        if export.get("path"):
            export.setdefault("local_url", Path(export["path"]).expanduser().resolve().as_uri())
        if status.get("resource_url"):
            export["download_url"] = status["resource_url"]
            if not export.get("url") or str(export["url"]).startswith("file:"):
                export["url"] = status["resource_url"]
        elif export.get("path") and not export.get("url"):
            export["url"] = export["local_url"]
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
        if fn is xiyou_run:
            mcp.tool(
                description=(
                    "执行西柚洞察场景并导出 JSON/XLSX；ranking 场景支持把 asin / keyword "
                    "作为 query 别名传入。flow-diagnosis（流量诊断仪）因西柚官方暂无下载接口，"
                    "会直接提示并终止，不应继续尝试其他导出路径。"
                )
            )(fn)
        else:
            mcp.tool()(fn)
