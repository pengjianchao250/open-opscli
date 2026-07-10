"""卖家精灵正式 CLI。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import typer

from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


app = typer.Typer(help="卖家精灵远端 MCP 正式命令面。")
queue_app = typer.Typer(help="卖家精灵本地 SQLite 队列运维命令。")
app.add_typer(queue_app, name="queue")


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


@queue_app.command("status")
def queue_status(
    stale_running_seconds: int = typer.Option(1800, "--stale-running-seconds", help="running 超时判定秒数"),
) -> None:
    """读取本机卖家精灵 SQLite 队列摘要。"""
    payload = _get_queue_store().queue_status(stale_running_seconds=stale_running_seconds)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@queue_app.command("list")
def queue_list(
    state: str | None = typer.Option(None, "--state", help="按状态过滤，如 queued/running/failed"),
    limit: int = typer.Option(50, "--limit", help="返回条数，最大 500"),
) -> None:
    """列出本机卖家精灵队列任务。"""
    payload = _get_queue_store().list_tasks(state=state, limit=limit)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@queue_app.command("fail")
def queue_fail(
    state: str = typer.Option("queued", "--state", help="要终止的任务状态，默认 queued"),
    job_ids: list[str] | None = typer.Option(None, "--job-id", help="指定任务 ID，可重复传入"),
    before: str | None = typer.Option(None, "--before", help="只终止 created_at 不晚于该 ISO 时间的任务"),
    reason: str = typer.Option("人工终止队列任务", "--reason", help="写入 error_json 的原因"),
    all_tasks: bool = typer.Option(False, "--all", help="允许在无 job-id/before 时终止全部匹配状态任务"),
) -> None:
    """将匹配队列任务标记为 failed。"""
    if not job_ids and not before and not all_tasks:
        raise typer.BadParameter("必须提供 --job-id、--before，或显式传入 --all")
    changed = _get_queue_store().fail_tasks(
        state=state,
        job_ids=job_ids,
        before=before,
        reason=reason,
    )
    typer.echo(json.dumps({"changed": changed}, ensure_ascii=False, indent=2))


@queue_app.command("requeue-running")
def queue_requeue_running(
    older_than_minutes: int = typer.Option(30, "--older-than-minutes", help="仅重排 started_at 早于该分钟数的 running 任务"),
) -> None:
    """将超时 running 任务重新放回 queued。"""
    before_started_at = _minutes_ago_iso(max(0, older_than_minutes))
    changed = _get_queue_store().reset_running_tasks(before_started_at=before_started_at)
    typer.echo(
        json.dumps(
            {
                "changed": changed,
                "before_started_at": before_started_at,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@queue_app.command("worker-health")
def queue_worker_health(
    stale_running_seconds: int = typer.Option(1800, "--stale-running-seconds", help="running 超时判定秒数"),
) -> None:
    """读取队列健康摘要。当前版本未持久化 worker heartbeat。"""
    payload = _get_queue_store().queue_status(stale_running_seconds=stale_running_seconds)
    payload["worker_state"] = "no_heartbeat"
    payload["healthy"] = payload.get("stale_running_count", 0) == 0
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed


def _get_queue_store():
    """延迟加载队列仓储，避免普通远端命令初始化本地 SQLite。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    return SellerSpriteTaskQueueStore()


def _minutes_ago_iso(minutes: int) -> str:
    """返回当前时间向前偏移指定分钟后的本地 ISO 字符串。"""
    return (datetime.now(timezone.utc).astimezone() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
