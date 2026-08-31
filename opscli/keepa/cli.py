"""Keepa 正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.keepa.remote_adapter import KeepaRemoteAdapter


app = typer.Typer(help="Keepa 远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    """列出远端命令面支持的 Keepa 场景。"""
    payload = KeepaRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("quota-status")
def quota_status() -> None:
    """读取当前用户的 Keepa 每日额度快照。"""
    payload = KeepaRemoteAdapter().quota_status()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 product"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE、GB"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx/json"),
    reserve_tokens: int | None = typer.Option(None, "--reserve-tokens", help="预留 token 阈值"),
    force: bool = typer.Option(False, "--force", help="忽略 token 预检查提醒继续执行"),
    wait: bool = typer.Option(False, "--wait", help="token 不足时等待一次 refill 后执行"),
) -> None:
    """按正式公共命令契约执行 Keepa 场景。"""
    payload = KeepaRemoteAdapter().run(
        scenario=scenario,
        site=site,
        params=_parse_params(params),
        job_id=job_id,
        export_format=export_format,
        reserve_tokens=reserve_tokens,
        force=force,
        wait=wait,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Keepa 任务结果。"""
    payload = KeepaRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Keepa 任务导出文件信息。"""
    payload = KeepaRemoteAdapter().export(job_id)
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
