"""西柚洞察接口直连 CLI。"""

from __future__ import annotations

import asyncio
import json

import typer

from opscli.xiyou.domain.models import XiyouRankingRequest
from opscli.xiyou.services import XiyouApiManager


app = typer.Typer(help="西柚洞察接口直连")


@app.command("scenarios")
def scenarios() -> None:
    """列出支持的西柚洞察场景。"""
    payload = XiyouApiManager().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_function(
    function: str = typer.Argument(..., help="功能名称，首期支持 ranking"),
    provider: str = typer.Option("xiyou", "--provider", help="服务商，默认 xiyou"),
    target: str = typer.Option("asin", "--target", help="排行榜目标：asin/keyword"),
    site: str = typer.Option("US", "--site", help="站点，如 US、DE、UK、CA、FR"),
    period: str = typer.Option("week", "--period", help="周期：week/month"),
    rank_pattern: str | None = typer.Option(None, "--rank-pattern", help="榜单类型，如 flow/surge/aba"),
    dataset: str | None = typer.Option(None, "--dataset", help="业务数据块，如 keywords/analysis"),
    asin: str | None = typer.Option(None, "--asin", help="单个 ASIN，用于反查关键词"),
    asins: str | None = typer.Option(None, "--asins", help="多个 ASIN，逗号分隔，用于多ASIN对比"),
    keyword: str | None = typer.Option(None, "--keyword", help="关键词，用于关键词分析/以词找词"),
    query: str = typer.Option("", "--query", help="搜索过滤词"),
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
        query=query,
        page=page,
        page_size=page_size,
        job_id=job_id,
        output_dir=output_dir,
        export_format=export_format,
    )
    result = asyncio.run(XiyouApiManager().run(request))
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
