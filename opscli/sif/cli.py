"""Sif 平台 CLI 入口。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from opscli.sif.compare.provider import SifCompareProvider
from opscli.sif.config import DEFAULT_FEATURE_OUTPUT_DIRS, SifSettings, default_output_dir_for_feature, load_settings
from opscli.sif.domain.models import SifRunRequest
from opscli.sif.sales.models import SifSalesRunRequest
from opscli.sif.sales.provider import SifSalesProvider
from opscli.sif.sites import normalize_site
from opscli.sif.traffic.provider import SifTrafficProvider


app = typer.Typer(help="Sif 平台接口直连")
console = Console()

FEATURE_DEFINITIONS = {
    "查销量": {"key": "sales", "provider": SifSalesProvider, "aliases": ["查销量", "sales"]},
    "查流量": {"key": "traffic", "provider": SifTrafficProvider, "aliases": ["查流量", "查流量词", "查流量(词)", "traffic", "traffic-keywords"]},
    "多产品对比": {"key": "compare", "provider": SifCompareProvider, "aliases": ["多产品对比", "compare"]},
}

FEATURE_ALIASES = {
    alias: canonical
    for canonical, definition in FEATURE_DEFINITIONS.items()
    for alias in definition["aliases"]
}


@app.command("features")
def features(pretty: bool = typer.Option(False, "--pretty", help="格式化 JSON 输出")) -> None:
    """列出 Sif 支持的功能。"""
    data = [
        {"feature": feature, "provider": "sif", "aliases": definition["aliases"]}
        for feature, definition in FEATURE_DEFINITIONS.items()
    ]
    _emit({"success": True, "command": "sif features", "data": data, "error": None}, pretty=True if pretty else False)


@app.command("run")
def run(
    feature: str = typer.Argument(..., help="功能名称，如：查销量"),
    asin: str = typer.Option(..., "--asin", help="目标 ASIN"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE"),
    range_value: str | None = typer.Option(None, "--range", help="查询维度，默认 asin"),
    time_piece_type: str = typer.Option("latelyDay", "--time-piece-type", help="Sif 时间范围类型"),
    time_piece_value: str = typer.Option("7", "--time-piece-value", help="Sif 时间范围值"),
    sections: str | None = typer.Option(None, "--sections", help="逗号分隔子模块；默认 all"),
    my_asin: str | None = typer.Option(None, "--my-asin", help="多产品对比中我的 ASIN"),
    page_num: int = typer.Option(1, "--page-num", min=1, help="下载列表页码，默认 1"),
    page_size: int | None = typer.Option(None, "--page-size", min=1, help="下载列表数量；未指定时按功能默认值"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录；默认使用 OPSCLI_SIF_OUTPUT_DIR 或用户级配置目录"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    sif_username: str | None = typer.Option(None, "--sif-username", help="Sif 登录手机号；优先使用环境变量"),
    sif_password: str | None = typer.Option(None, "--sif-password", help="Sif 登录密码；不会写入输出文件"),
    timeout: float = typer.Option(20.0, "--timeout", min=1.0, help="Sif HTTP 请求超时秒数"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化 JSON 输出"),
    json_output: bool = typer.Option(False, "--json", help="输出机器可读 JSON"),
) -> None:
    """执行一个 Sif 功能。"""
    try:
        canonical_feature = FEATURE_ALIASES.get(feature)
        if not canonical_feature:
            raise ValueError(f"不支持的 Sif 功能：{feature}")
        feature_key = str(FEATURE_DEFINITIONS[canonical_feature]["key"])
        settings = load_settings()
        default_output_dir = default_output_dir_for_feature(feature_key)
        if canonical_feature == "查销量":
            request = SifSalesRunRequest(
                feature=canonical_feature,
                provider="sif",
                asin=asin,
                site=normalize_site(site),
                range_value=range_value,
                time_piece_type=time_piece_type,
                time_piece_value="30" if time_piece_value == "7" else str(time_piece_value),
                page_num=page_num,
                page_size=page_size or 100,
                sections=[sections] if sections else [],
                output_dir=output_dir,
                job_id=job_id,
                sif_username=sif_username,
                sif_password=sif_password,
                timeout=timeout,
            )
            result = SifSalesProvider().run(request, default_output_dir=default_output_dir)
        else:
            request = SifRunRequest(
                feature=canonical_feature,
                asin=asin,
                site=site,
                time_piece_type=time_piece_type,
                time_piece_value=str(time_piece_value),
                sections=[sections] if sections else [],
                my_asin=my_asin,
                page_num=page_num,
                page_size=page_size,
                output_dir=output_dir,
                job_id=job_id,
                sif_username=sif_username,
                sif_password=sif_password,
                timeout=timeout,
            )
            provider_cls = FEATURE_DEFINITIONS[canonical_feature]["provider"]
            result = provider_cls().run(request, default_output_dir=default_output_dir)
    except Exception as exc:
        _emit_error("sif run", exc, pretty=pretty, json_output=json_output)
        raise typer.Exit(1)
    _emit_run_success(result, pretty=pretty, json_output=json_output)


@app.command("login-check")
def login_check(
    sif_username: str | None = typer.Option(None, "--sif-username", help="Sif 登录手机号"),
    sif_password: str | None = typer.Option(None, "--sif-password", help="Sif 登录密码；不会输出"),
    timeout: float = typer.Option(20.0, "--timeout", min=1.0, help="Sif HTTP 请求超时秒数"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化 JSON 输出"),
) -> None:
    """检查 Sif 登录态，不输出敏感值。"""
    try:
        from opscli.sif.client import SifApiClient

        settings = load_settings()
        client = SifApiClient(
            settings=SifSettings(
                base_url=settings.base_url,
                cookie=settings.cookie,
                token=settings.token,
                username=sif_username or settings.username,
                password=sif_password or settings.password,
                output_dir=settings.output_dir,
            ),
            timeout=timeout,
        )
        data = client.login_diagnostics()
    except Exception as exc:
        _emit_error("sif login-check", exc, pretty=pretty, json_output=True)
        raise typer.Exit(1)
    _emit({"success": True, "command": "sif login-check", "data": data, "error": None}, pretty=True if pretty else False)


@app.command("status")
def status(
    job_id: str = typer.Argument(..., help="任务 ID"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化 JSON 输出"),
) -> None:
    """读取 Sif 任务结果。"""
    try:
        settings = load_settings()
        base_dirs = [Path(output_dir).expanduser()] if output_dir else [settings.output_dir, *DEFAULT_FEATURE_OUTPUT_DIRS.values()]
        result_path = None
        for base_dir in dict.fromkeys(base_dirs):
            if not base_dir.is_absolute():
                base_dir = Path.cwd() / base_dir
            candidate = base_dir / job_id / "result.json"
            if candidate.exists():
                result_path = candidate
                break
        if result_path is None:
            searched = ", ".join(str(path) for path in dict.fromkeys(base_dirs))
            raise ValueError(f"Sif 任务不存在：{job_id}；已查找目录：{searched}")
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _emit_error("sif status", exc, pretty=pretty, json_output=True)
        raise typer.Exit(1)
    _emit({"success": True, "command": "sif status", "data": data, "error": None}, pretty=True if pretty else False)


def _emit(payload: dict, pretty: bool) -> None:
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _error_payload(command: str, exc: Exception) -> dict:
    if isinstance(exc, PermissionError):
        error = {
            "code": "SIF_OUTPUT_PERMISSION_DENIED",
            "message": str(exc),
        }
    elif hasattr(exc, "to_dict"):
        error = exc.to_dict()
    else:
        error = {"code": "SIF_ERROR", "message": str(exc)}
    code = str(error.get("code") or "SIF_ERROR")
    message = str(error.get("message") or "执行失败")
    error["user_message"] = _friendly_error_message(code, message, error)
    suggestion = _error_suggestion(code, error)
    if suggestion:
        error["suggestion"] = suggestion
    return {"success": False, "command": command, "data": None, "error": error}


def _emit_run_success(result, *, pretty: bool, json_output: bool) -> None:
    payload = {"success": True, "command": "sif run", "data": result.to_dict(), "error": None}
    if pretty or json_output:
        _emit(payload, pretty=True)
        return
    console.print("[green]Sif 执行成功[/green]")
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("field", style="cyan", no_wrap=True)
    table.add_column("value")
    table.add_row("功能", result.feature)
    if getattr(result, "asin", None):
        table.add_row("ASIN", result.asin)
    asins = getattr(result, "asins", None) or []
    if asins and not getattr(result, "asin", None):
        table.add_row("ASIN 数量", str(len(asins)))
    table.add_row("站点", result.site)
    for label, export_key in (
        ("不同变体销量", "listing_history_xlsx"),
        ("同组变体销量", "bought_by_asin_xlsx"),
        ("流量结构", "traffic_structure_xlsx"),
        ("反查流量词", "traffic_keywords_xlsx"),
        ("多变体自然位", "multi_nf_keywords_xlsx"),
        ("对比销量", "compare_sales_xlsx"),
        ("对比流量词", "compare_traffic_words_xlsx"),
        ("对比流量分", "compare_traffic_score_xlsx"),
        ("重点流量词", "compare_my_traffic_keywords_xlsx"),
        ("重点广告词", "compare_my_ad_keywords_xlsx"),
    ):
        export = result.exports.get(export_key)
        if export:
            table.add_row(label, f"{export.filename}\n{_file_link(export.path)}")
    console.print(table)


def _emit_error(command: str, exc: Exception, *, pretty: bool, json_output: bool) -> None:
    payload = _error_payload(command, exc)
    if pretty or json_output:
        _emit(payload, pretty=True)
        return
    error = payload["error"] or {}
    code = str(error.get("code") or "SIF_ERROR")
    message = str(error.get("message") or "执行失败")
    console.print(f"[red]{command} 执行失败[/red]")
    console.print(f"[cyan]错误码[/cyan] {code}")
    console.print(f"[cyan]原因[/cyan] {error.get('user_message') or _friendly_error_message(code, message, error)}")
    suggestion = str(error.get("suggestion") or _error_suggestion(code, error))
    if suggestion:
        console.print(f"[cyan]建议[/cyan] {suggestion}")


def _friendly_error_message(code: str, message: str, error: dict) -> str:
    if code == "SIF_LOGIN_REQUIRED":
        return "SIF 平台账号登录状态不可用，可能是未登录、登录过期，或 SIF 拒绝访问。"
    if code == "SIF_LOGIN_FAILED":
        return "SIF 平台账号登录失败，请确认账号可用、密码正确，且账号未被平台限制。"
    if code == "SIF_API_REQUEST_FAILED":
        excerpt = str(error.get("response_excerpt") or "")
        if "参数错误" in excerpt:
            return "SIF 平台接口返回参数错误，可能是筛选条件、时间范围或下载模块参数不被平台接受。"
        if "UNAUTHORIZED" in excerpt or "拒绝访问" in excerpt or "access" in excerpt.lower():
            return "SIF 平台接口拒绝访问，账号登录态可能已过期或当前账号没有访问权限。"
        return "SIF 平台接口异常，当前请求未能完成。"
    if code == "SIF_DOWNLOAD_FAILED":
        return "SIF 平台下载接口异常，未返回有效的 XLSX 文件。"
    if code == "SIF_OUTPUT_PERMISSION_DENIED":
        return "当前输出目录没有写入权限。"
    if code == "SIF_SITE_NOT_SUPPORTED":
        return message
    if code.startswith("SIF_"):
        return "SIF 平台发生未知异常，当前请求未能完成。"
    return message


def _error_suggestion(code: str, error: dict) -> str:
    if code in {"SIF_LOGIN_REQUIRED", "SIF_LOGIN_FAILED"}:
        return "先执行 opscli sif login-check，确认 SIF 账号登录状态；如仍失败，请重新配置账号或稍后重试。"
    if code == "SIF_API_REQUEST_FAILED":
        if error.get("request_payload") or error.get("request_query"):
            return "请检查 ASIN、站点、时间范围、sections 和 page-size；必要时对照 SIF 页面 Network 请求，不要粘贴 Cookie/token。"
        return "加 --json 查看结构化错误；若多次出现，可能是 SIF 平台接口临时异常。"
    if code == "SIF_DOWNLOAD_FAILED":
        return "请稍后重试；如果持续失败，对照 SIF 页面下载按钮的 Network 请求确认接口是否变更。"
    if code == "SIF_OUTPUT_PERMISSION_DENIED":
        return "使用 --output-dir 指定可写目录，或设置 OPSCLI_SIF_OUTPUT_DIR。"
    if code.startswith("SIF_"):
        return "请稍后重试；如果持续失败，使用 --json 保存错误详情并反馈。"
    return ""


def _file_link(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    return f"[link=file:///{resolved.as_posix()}]{resolved}[/link]"
