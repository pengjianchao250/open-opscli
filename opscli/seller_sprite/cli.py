"""卖家精灵正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


app = typer.Typer(help="卖家精灵远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    """列出远端命令面支持的卖家精灵场景。"""
    payload = SellerSpriteRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("quota-status")
def quota_status() -> None:
    """读取当前用户的卖家精灵额度快照。"""
    payload = SellerSpriteRemoteAdapter().quota_status()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 keyword-reverse"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE"),
    period: str = typer.Option("30d", "--period", help="日期，如 30d、nearly、2026-03"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    page_size: int = typer.Option(100, "--page-size", help="每页数量"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx/json"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
) -> None:
    """按正式公共命令契约执行卖家精灵场景。"""
    payload = SellerSpriteRemoteAdapter().run(
        scenario=scenario,
        site=site,
        period=period,
        params=_parse_params(params),
        page_size=page_size,
        job_id=job_id,
        output_dir=output_dir,
        export_format=export_format,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("listing-analysis-submit")
def listing_analysis_submit(
    asin: str = typer.Option(..., "--asin", help="Amazon ASIN"),
    station: str = typer.Option("GLOBAL", "--station", help="Listing Analysis station，默认 GLOBAL"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE"),
    export_format: str = typer.Option("json", "--export-format", help="导出格式：json/xlsx/xls"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
) -> None:
    """提交 Listing Analysis 任务并返回 job_id。"""
    payload = SellerSpriteRemoteAdapter().listing_analysis_submit(
        asin=asin,
        station=station,
        site=site,
        export_format=export_format,
        output_dir=output_dir,
        job_id=job_id,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("listing-analysis-status")
def listing_analysis_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Listing Analysis 任务状态。"""
    payload = SellerSpriteRemoteAdapter().listing_analysis_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("listing-analysis-result")
def listing_analysis_result(
    job_id: str = typer.Argument(..., help="任务 ID"),
    export_format: str = typer.Option("json", "--export-format", help="导出格式：json/xlsx/xls"),
) -> None:
    """读取 Listing Analysis 任务结果。"""
    payload = SellerSpriteRemoteAdapter().listing_analysis_result(job_id, export_format=export_format)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取卖家精灵任务结果。"""
    payload = SellerSpriteRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取卖家精灵任务导出文件信息。"""
    payload = SellerSpriteRemoteAdapter().export(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed
