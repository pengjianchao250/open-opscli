"""Keepa API CLI。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from opscli.keepa.domain.models import KeepaScenarioRequest
from opscli.keepa.services import KeepaApiManager


app = typer.Typer(help="Keepa API 数据获取")


@app.command("token-status")
def token_status() -> None:
    """读取 Keepa API token 状态。"""
    payload = asyncio.run(KeepaApiManager().token_status())
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("scenarios")
def scenarios() -> None:
    """列出支持的 Keepa 场景。"""
    payload = KeepaApiManager().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 product"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE、GB"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx/json"),
    reserve_tokens: int | None = typer.Option(None, "--reserve-tokens", help="预留 token 阈值"),
    force: bool = typer.Option(False, "--force", help="忽略 token 预检查提醒继续执行"),
    wait: bool = typer.Option(False, "--wait", help="token 不足时等待一次 refill 后执行"),
) -> None:
    """执行 Keepa 场景并保存请求参数与响应数据。"""
    request = KeepaScenarioRequest(
        scenario=scenario,
        site=site,
        params=_parse_params(params),
        job_id=job_id,
        output_dir=output_dir,
        export_format=export_format,
        reserve_tokens=reserve_tokens,
        force=force,
        wait=wait,
    )
    result = asyncio.run(KeepaApiManager().run(request))
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed
