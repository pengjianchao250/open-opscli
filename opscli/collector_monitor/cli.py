"""Collector Monitor JSON CLI。"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx
import typer

from opscli.collector_monitor.config import load_settings

app = typer.Typer(help="只读查看 Collector Monitor 状态。", no_args_is_help=True)
_HTTP_TIMEOUT = 10.0


@app.command("serve")
def serve(
    host: str | None = typer.Option(None, help="监听地址，默认读取环境配置。"),
    port: int | None = typer.Option(None, min=1, max=65535, help="监听端口。"),
) -> None:
    """启动独立 Collector Monitor Web 服务。"""
    from opscli.collector_monitor.server import run

    run(host=host, port=port)


@app.command("status")
def status() -> None:
    """输出监控状态；数据源未就绪或有活动事故时返回非零码。"""
    payload = _get("/api/v1/status")
    _print_json(payload)
    source_ready = bool(payload.get("source", {}).get("ready"))
    active_count = int(payload.get("summary", {}).get("active_incident_count") or 0)
    if not source_ready or active_count > 0:
        raise typer.Exit(code=2)


@app.command("tasks")
def tasks(
    health: str | None = typer.Option(None, help="按健康分类过滤。"),
) -> None:
    """输出任务列表。"""
    params = {"health": health} if health else None
    _print_json(_get("/api/v1/tasks", params=params))


@app.command("show")
def show(job_id: str = typer.Argument(..., help="任务标识。")) -> None:
    """输出单个任务与进度时间线。"""
    _print_json(_get(f"/api/v1/tasks/{quote(job_id, safe='')}"))


@app.command("incidents")
def incidents() -> None:
    """输出活动和已恢复事故。"""
    _print_json(_get("/api/v1/incidents"))


def _get(path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
    """访问监控 HTTP API，并统一输出安全错误。"""
    base_url = load_settings().monitor_url
    try:
        response = httpx.get(
            f"{base_url}{path}",
            params=params,
            timeout=_HTTP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("响应不是 JSON 对象")
        return payload
    except httpx.HTTPStatusError as exc:
        _fail(
            "monitor_http_error",
            f"Collector Monitor 请求失败（HTTP {exc.response.status_code}）",
            code=1,
        )
    except Exception as exc:
        _fail(
            "monitor_unreachable",
            f"Collector Monitor 不可达（{type(exc).__name__}）",
            code=1,
        )
    raise AssertionError("unreachable")


def _fail(error_code: str, message: str, *, code: int) -> None:
    """输出稳定 JSON 错误并终止命令。"""
    _print_json(
        {
            "success": False,
            "error": {"code": error_code, "message": message},
        }
    )
    raise typer.Exit(code=code)


def _print_json(payload: Any) -> None:
    """以 UTF-8 友好的稳定 JSON 输出结果。"""
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    app()
