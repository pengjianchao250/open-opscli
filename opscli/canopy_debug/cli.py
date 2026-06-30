"""Canopy 本地调试 CLI。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer

from opscli.beta.canopy.config import CANOPY_API_KEY_PLACEHOLDER, CanopySettings, load_local_api_key
from opscli.beta.canopy.domain.models import CanopyScenarioRequest
from opscli.beta.canopy.services import CanopyApiManager
from opscli.mcp.tools.beta import CANOPY_SCENARIOS


app = typer.Typer(help="Canopy 本地调试命令；保留本地直连链路，`run` 支持 `--api-key` 等本地调试参数。")


@app.command("scenarios")
def scenarios() -> None:
    """列出支持的 Canopy 场景。"""
    payload = [{"scenario_id": scenario_id, **meta} for scenario_id, meta in CANOPY_SCENARIOS.items()]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 product、search、product-reviews"),
    domain: str = typer.Option("US", "--domain", help="Amazon 站点，如 US、JP、DE"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    api_key: str | None = typer.Option(None, "--api-key", help="本地调试覆盖 Canopy API key"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls"),
    timeout_seconds: int = typer.Option(60, "--timeout-seconds", help="本地请求超时时间（秒）"),
) -> None:
    """执行本地 Canopy 场景并保存请求、响应和导出数据。"""
    meta = _get_scenario(scenario)
    resolved_api_key = _resolve_api_key(api_key)
    request = CanopyScenarioRequest(
        scenario=scenario,
        domain=domain,
        params=_parse_params(params),
        path=meta["path"],
        method=meta["method"],
        title=meta["title"],
        api_key=resolved_api_key,
        api_key_placeholder_used=resolved_api_key == CANOPY_API_KEY_PLACEHOLDER,
        timeout_seconds=timeout_seconds,
        output_dir=output_dir,
        job_id=job_id,
        export_format=export_format,
    )
    result = asyncio.run(CanopyApiManager().run(request))
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(
    job_id: str = typer.Argument(..., help="任务 ID"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="任务输出目录"),
) -> None:
    """读取本地已落盘的 Canopy 任务结果。"""
    payload = _build_manager(output_dir).job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(
    job_id: str = typer.Argument(..., help="任务 ID"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="任务输出目录"),
) -> None:
    """读取本地 Canopy 任务导出文件信息。"""
    payload = _extract_export_payload(job_id, output_dir=output_dir)
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


def _get_scenario(scenario: str) -> dict[str, Any]:
    """读取调试场景元数据。"""
    meta = CANOPY_SCENARIOS.get(scenario)
    if not meta:
        supported = ", ".join(CANOPY_SCENARIOS)
        raise typer.BadParameter(f"不支持的 Canopy 场景：{scenario}。支持场景：{supported}")
    return meta


def _resolve_api_key(api_key: str | None) -> str:
    """解析本地调试使用的 API key。"""
    for candidate in (api_key, load_local_api_key()):
        if candidate and candidate.strip():
            return candidate.strip()
    return CANOPY_API_KEY_PLACEHOLDER


def _build_manager(output_dir: str | None = None) -> CanopyApiManager:
    """按需构造本地 Canopy 管理器。"""
    if not output_dir:
        return CanopyApiManager()
    return CanopyApiManager(settings=CanopySettings(output_dir=Path(output_dir).expanduser()))


def _extract_export_payload(job_id: str, *, output_dir: str | None = None) -> dict[str, Any]:
    """提取调试任务的导出信息，缺失时给出明确错误。"""
    payload = _build_manager(output_dir).job_status(job_id).get("export")
    if isinstance(payload, dict) and payload:
        return payload
    typer.secho(f"任务未生成导出文件：{job_id}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1)
