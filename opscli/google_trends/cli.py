"""Google Trends 正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.google_trends.api.key_store import SerpApiKeyRecord, SerpApiKeyStore
from opscli.google_trends.api.serpapi_client import SerpApiGoogleTrendsClient
from opscli.google_trends.remote_adapter import GoogleTrendsRemoteAdapter


app = typer.Typer(help="Google Trends 正式场景与本地运维命令。")
api_key_app = typer.Typer(help="Google Trends 本地 SerpApi Key 运维命令。")
app.add_typer(api_key_app, name="api-key")


@api_key_app.command("add")
def api_key_add(
    name: str = typer.Option(..., "--name", help="本地账号名称"),
    remark: str | None = typer.Option(None, "--remark", help="账号备注"),
) -> None:
    """新增或更新 SerpApi Key；Key 使用隐藏输入。"""
    api_key = typer.prompt("SerpApi API Key", hide_input=True)
    record = SerpApiKeyStore().add_key(
        name=name,
        api_key=api_key,
        remark=remark,
    )
    _echo_public_key(record)


@api_key_app.command("list")
def api_key_list() -> None:
    """列出本地 SerpApi 账号，不输出明文 Key。"""
    records = SerpApiKeyStore().list_keys()
    typer.echo(
        json.dumps(
            [record.to_public_dict() for record in records],
            ensure_ascii=False,
            indent=2,
        )
    )


@api_key_app.command("test")
def api_key_test(
    name: str = typer.Option(..., "--name", help="要检查额度的账号名称"),
) -> None:
    """通过免费 Account API 检查指定账号，不发起搜索。"""
    store = SerpApiKeyStore()
    record = _get_key_by_name(store, name)
    client = SerpApiGoogleTrendsClient(key_store=store)
    try:
        payload = client.check_account(record.key_id)
    finally:
        client.close()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@api_key_app.command("enable")
def api_key_enable(
    name: str = typer.Option(..., "--name", help="要启用的账号名称"),
) -> None:
    """显式启用指定 SerpApi 账号。"""
    _set_key_status(name, "active")


@api_key_app.command("disable")
def api_key_disable(
    name: str = typer.Option(..., "--name", help="要禁用的账号名称"),
) -> None:
    """显式禁用指定 SerpApi 账号。"""
    _set_key_status(name, "disabled")


@app.command("scenarios")
def scenarios() -> None:
    """列出远端命令面支持的 Google Trends 场景。"""
    payload = GoogleTrendsRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID：trends、autocomplete、trending-now"),
    geo: str = typer.Option("US", "--geo", help="地区代码，如 US；传空字符串查询全球"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx/json"),
    hl: str | None = typer.Option(None, "--hl", help="语言区域，如 en-US"),
    tz: int | None = typer.Option(None, "--tz", help="时区分钟偏移，如 360"),
) -> None:
    """按正式公共命令契约执行 Google Trends 场景。"""
    payload = GoogleTrendsRemoteAdapter().run(
        scenario=scenario,
        geo=geo,
        params=_parse_params(params),
        job_id=job_id,
        export_format=export_format,
        hl=hl,
        tz=tz,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Google Trends 任务结果。"""
    payload = GoogleTrendsRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Google Trends 任务导出文件信息。"""
    payload = GoogleTrendsRemoteAdapter().export(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _set_key_status(name: str, status: str) -> None:
    """按账号名称更新状态并输出最新公开摘要。"""
    store = SerpApiKeyStore()
    record = _get_key_by_name(store, name)
    store.set_status(record.key_id, status)
    updated = store.get_by_name(name)
    if updated is None:
        raise typer.BadParameter(f"SerpApi 账号不存在：{name}")
    _echo_public_key(updated)


def _get_key_by_name(store: SerpApiKeyStore, name: str) -> SerpApiKeyRecord:
    """读取命名账号，不存在时转换为 CLI 参数错误。"""
    record = store.get_by_name(name)
    if record is None:
        raise typer.BadParameter(f"SerpApi 账号不存在：{name}")
    return record


def _echo_public_key(record: SerpApiKeyRecord) -> None:
    """输出不含明文凭证的 SerpApi 账号摘要。"""
    typer.echo(json.dumps(record.to_public_dict(), ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    """解析场景 JSON 参数。"""
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed
