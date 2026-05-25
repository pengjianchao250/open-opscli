"""卖家精灵接口直连 CLI。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services import SellerSpriteApiManager


app = typer.Typer(help="卖家精灵接口直连")


@app.command("scenarios")
def scenarios() -> None:
    """列出支持的卖家精灵场景。"""
    payload = SellerSpriteApiManager().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 keyword-reverse"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE"),
    period: str = typer.Option("30d", "--period", help="日期，如 30d、nearly、2026-03"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    page_size: int = typer.Option(100, "--page-size", help="每页数量"),
    export_format: str = typer.Option("xlsx", "--export-format", help="导出格式：xlsx/xls/json"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
) -> None:
    """执行场景并导出文件。"""
    request = SellerSpriteScenarioRequest(
        scenario=scenario,
        site=site,
        period=period,
        params=_parse_params(params),
        page_size=page_size,
        job_id=job_id,
        output_dir=output_dir,
        export_format=export_format,
    )
    result = asyncio.run(SellerSpriteApiManager().run(request))
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed
