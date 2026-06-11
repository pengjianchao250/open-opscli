"""西柚洞察接口直连 CLI。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import typer

from opscli.xiyou.config import load_settings
from opscli.xiyou.credentials import XiyouCredentialProvider
from opscli.xiyou.domain.exceptions import XiyouConfigError
from opscli.xiyou.domain.models import XiyouRankingRequest
from opscli.xiyou.notify import load_notify_config, notify_token_required
from opscli.xiyou.services import XiyouApiManager


app = typer.Typer(help="西柚洞察接口直连")
credential_app = typer.Typer(help="西柚凭据管理")
notify_app = typer.Typer(help="西柚登录超期通知")
app.add_typer(credential_app, name="credential")
app.add_typer(notify_app, name="notify")


@app.command("scenarios")
def scenarios() -> None:
    """列出支持的西柚洞察场景。"""
    payload = XiyouApiManager().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command(
    "run",
    help=(
        "ranking 场景支持把 `asin` / `keyword` 作为 `query` 别名传入；"
        "`flow-diagnosis`（流量诊断仪）现按列表接口拉取数据并在本地导出文件。"
    ),
)
def run_function(
    function: str = typer.Argument(
        ...,
        help=(
            "功能名称，如 ranking、reverse-keyword、asin-compare、keyword-analysis、keyword-explorer、"
            "keyword-historical-traffic、keyword-ad-replay、keyword-organic-replay、keyword-ad-toppers、"
            "ad-analysis、parent-analysis、sales-analysis、flow-diagnosis、flow-insight、ad-insight、flow-weekly"
        ),
    ),
    provider: str = typer.Option("xiyou", "--provider", help="服务商，默认 xiyou"),
    target: str = typer.Option("asin", "--target", help="排行榜目标：asin/keyword"),
    site: str = typer.Option("US", "--site", help="站点，如 US、DE、UK、CA、FR"),
    period: str = typer.Option(
        "week",
        "--period",
        help="周期：ASIN 排行榜支持 week/month；关键词排行榜仅支持 week；历史流量分析会自动按 month（最近1个月）处理",
    ),
    rank_pattern: str | None = typer.Option(None, "--rank-pattern", help="榜单类型，如 flow/surge/aba"),
    dataset: str | None = typer.Option(None, "--dataset", help="业务数据块，如 keywords/analysis"),
    asin: str | None = typer.Option(None, "--asin", help="单个 ASIN，用于反查关键词"),
    asins: str | None = typer.Option(
        None,
        "--asins",
        help="多个 ASIN，逗号分隔，用于多ASIN对比；广告分析缺省时会尝试自动补齐",
    ),
    keyword: str | None = typer.Option(
        None,
        "--keyword",
        help="关键词，用于关键词分析、以词找词、历史流量分析、广告放映机、自然放映机、广告金主榜",
    ),
    parent_asin: str | None = typer.Option(
        None,
        "--parent-asin",
        help="父体 ASIN，用于广告分析、父体分析、订单量分析；缺省时会尝试自动补齐",
    ),
    query: str = typer.Option("", "--query", help="搜索过滤词"),
    search_terms: str | None = typer.Option(None, "--search-terms", help="搜索词列表，逗号分隔；主要用于广告分析"),
    cycle_period: str | None = typer.Option(
        None,
        "--cycle-period",
        help="时间范围：last7days/last1month/last3months/last6months/last12months/custom_month_range",
    ),
    start_month: str | None = typer.Option(
        None,
        "--start-month",
        help="自定义月区间起始月，格式 YYYY-MM；主要用于反查关键词/关键词分析/以词找词",
    ),
    end_month: str | None = typer.Option(
        None,
        "--end-month",
        help="自定义月区间结束月，格式 YYYY-MM；主要用于反查关键词/关键词分析/以词找词",
    ),
    start_date: str | None = typer.Option(
        None,
        "--start-date",
        help="日期区间起始日，格式 YYYY-MM-DD；历史流量分析已不再支持该参数",
    ),
    end_date: str | None = typer.Option(
        None,
        "--end-date",
        help="日期区间结束日，格式 YYYY-MM-DD；历史流量分析已不再支持该参数",
    ),
    report_date: str | None = typer.Option(
        None,
        "--report-date",
        help="报表日期，格式 YYYY-MM-DD；主要用于广告放映机/自然放映机",
    ),
    view_mode: str | None = typer.Option(
        None,
        "--view-mode",
        help="视图：reverse-keyword 支持 data/trends/top10；keyword-analysis 支持 data/trends；asin-compare 下载时忽略该参数",
    ),
    replay_type: str | None = typer.Option(
        None,
        "--replay-type",
        help="放映机类型：ac/oor；主要用于自然放映机，默认 oor",
    ),
    keyword_type: str | None = typer.Option(
        None,
        "--keyword-type",
        help="关键词类型：all/organic/advertising；用于反查关键词和多 ASIN 对比，默认 all",
    ),
    page: int = typer.Option(1, "--page", help="页码"),
    page_size: int = typer.Option(50, "--page-size", help="每页数量"),
    export_format: str = typer.Option("xlsx", "--export-format", help="导出格式：xlsx/xls/json"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
) -> None:
    """执行西柚洞察功能并导出文件。"""
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
        parent_asin=parent_asin,
        query=query,
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
    result = asyncio.run(XiyouApiManager().run(request))
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


@credential_app.command("status")
def credential_status() -> None:
    """查看当前西柚凭据状态，不输出 token/cookie。"""
    settings = load_settings()
    try:
        credential = XiyouCredentialProvider(settings).get_default()
        payload = credential.to_public_dict()
        payload["expires_in_seconds"] = _expires_in_seconds(credential.expires_at)
    except XiyouConfigError as exc:
        payload = {
            "has_authorization": False,
            "has_cookie": False,
            "error": exc.to_dict(),
            "expires_in_seconds": None,
        }
    payload["has_credential_latest_url"] = bool(settings.credential_latest_url)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@notify_app.command("status")
def notify_status() -> None:
    """查看西柚登录超期通知配置，不输出敏感 webhook。"""
    settings = load_settings()
    config = load_notify_config(settings)
    payload = {
        "source": config.source,
        "enabled": config.enabled,
        "has_webhook_url": bool(config.webhook_url),
        "has_quick_login_url": bool(config.quick_login_url),
        "quick_login_url": config.quick_login_url,
        "dedupe_minutes": config.dedupe_minutes,
        "mentioned_list": list(config.mentioned_list),
        "mentioned_mobile_list": list(config.mentioned_mobile_list),
        "mention_all": config.mention_all,
        "state_path": str(config.state_path),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@notify_app.command("test")
def notify_test(
    job_id: str = typer.Option("manual-verify", "--job-id", help="测试消息里的业务标识"),
) -> None:
    """发送一条西柚登录超期测试通知。"""
    result = notify_token_required(
        reason="manual_verify",
        status_code=401,
        business_code="TokenInvalid",
        job_id=job_id,
        force=True,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("sent"):
        raise typer.Exit(1)


def _expires_in_seconds(expires_at: str | None) -> int | None:
    if not expires_at:
        return None
    try:
        parsed = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int((parsed - datetime.now(timezone.utc)).total_seconds())
