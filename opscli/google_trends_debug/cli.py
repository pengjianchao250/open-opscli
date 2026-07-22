"""Google Trends 本地调试 CLI。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from opscli.google_trends.domain.models import GoogleTrendsScenarioRequest
from opscli.google_trends.services import GoogleTrendsApiManager


app = typer.Typer(help="Google Trends 本地调试命令；保留本地直连执行链路。")


@app.command("scenarios")
def scenarios() -> None:
    """列出支持的 Google Trends 场景。"""
    payload = GoogleTrendsApiManager().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID：trends、autocomplete、trending-now"),
    geo: str = typer.Option("US", "--geo", help="地区代码，如 US；传空字符串查询全球"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx/json"),
    hl: str | None = typer.Option(None, "--hl", help="语言区域，如 en-US"),
    tz: int | None = typer.Option(None, "--tz", help="时区分钟偏移，如 360"),
) -> None:
    """执行本地 Google Trends 场景并保存请求参数与响应数据。"""
    request = GoogleTrendsScenarioRequest(
        scenario=scenario,
        geo=geo,
        params=_parse_params(params),
        job_id=job_id,
        output_dir=output_dir,
        export_format=export_format,
        hl=hl,
        tz=tz,
    )
    result = asyncio.run(GoogleTrendsApiManager().run(request))
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取本地已落盘的 Google Trends 任务结果。"""
    payload = GoogleTrendsApiManager().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取本地 Google Trends 任务导出文件信息。"""
    payload = _extract_export_payload(job_id)
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


def _extract_export_payload(job_id: str) -> dict[str, Any]:
    """提取调试任务的导出信息，缺失时给出明确错误。"""
    payload = GoogleTrendsApiManager().job_status(job_id).get("export")
    if isinstance(payload, dict) and payload:
        return payload
    typer.secho(f"任务未生成导出文件：{job_id}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1)
