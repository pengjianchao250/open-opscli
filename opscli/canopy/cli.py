"""Canopy 正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.canopy.remote_adapter import CanopyRemoteAdapter


app = typer.Typer(help="Canopy 远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    """列出远端命令面支持的 Canopy 场景。"""
    payload = CanopyRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 product、search、product-reviews"),
    domain: str = typer.Option("US", "--domain", help="Amazon 站点，如 US、JP、DE"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls"),
    timeout_seconds: int = typer.Option(60, "--timeout-seconds", help="远端请求超时时间（秒）"),
) -> None:
    """按正式公共命令契约执行 Canopy 场景。"""
    payload = CanopyRemoteAdapter().run(
        scenario=scenario,
        domain=domain,
        params=_parse_params(params),
        job_id=job_id,
        export_format=export_format,
        timeout_seconds=timeout_seconds,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Canopy 任务结果。"""
    payload = CanopyRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Canopy 任务导出文件信息。"""
    payload = CanopyRemoteAdapter().export(job_id)
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
