"""Scrape.do 正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.scrape_do.remote_adapter import ScrapeDoRemoteAdapter


app = typer.Typer(help="Scrape.do Amazon Scraper 远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    """列出远端命令面支持的 Scrape.do 场景。"""
    payload = ScrapeDoRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 amazon-pdp、amazon-offer-listing、amazon-search"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE、GB"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx"),
    timeout_seconds: int | None = typer.Option(None, "--timeout-seconds", help="请求超时时间秒数"),
) -> None:
    """按正式公共命令契约执行 Scrape.do 场景。"""
    payload = ScrapeDoRemoteAdapter().run(
        scenario=scenario,
        site=site,
        params=_parse_params(params),
        job_id=job_id,
        export_format=export_format,
        timeout_seconds=timeout_seconds,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Scrape.do 任务结果。"""
    payload = ScrapeDoRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Scrape.do 任务导出文件信息。"""
    payload = ScrapeDoRemoteAdapter().export(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    """解析场景 JSON 参数。"""
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed
