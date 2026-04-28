"""seller-sprite CLI 子命令定义。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from opscli.seller_sprite.domain.exceptions import SellerSpriteError
from opscli.seller_sprite.domain.models import SellerSpriteCollectOptions
from opscli.seller_sprite.services.account_store import SellerSpriteAccountStore
from opscli.seller_sprite.services.manager import SellerSpriteManager

app = typer.Typer(help="卖家精灵关键词与 Listing 分析材料采集")
account_app = typer.Typer(help="管理卖家精灵命名账号")
app.add_typer(account_app, name="account")


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(payload, ensure_ascii=False)
    sys.stdout.buffer.write(f"{text}\n".encode("utf-8"))


def _error_payload(command: str, exc: Exception) -> dict:
    """统一错误输出。"""
    if isinstance(exc, SellerSpriteError):
        error = exc.to_dict()
    else:
        error = {
            "code": "SELLER_SPRITE_ERROR",
            "message": str(exc),
        }
    return {
        "success": False,
        "command": command,
        "data": None,
        "error": error,
    }


@app.command("collect")
def collect(
    asin: str | None = typer.Option(None, "--asin", help="Amazon ASIN，可选，用于关联后续 Listing 分析对象"),
    keyword: str = typer.Option(..., "--keyword", help="卖家精灵关键词挖掘入口词"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，例如 30d 或 2026-03"),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="关键词采集条数，默认 50"),
    frequency_phrase_count: int = typer.Option(1, "--frequency-phrase-count", min=1, max=10, help="高频词词组个数，默认 1"),
    trend_limit: int = typer.Option(0, "--trend-limit", min=0, max=50, help="采集前 N 个关键词的历史走势弹窗，默认 0 不采集"),
    trend_tabs: str = typer.Option("all", "--trend-tabs", help="历史走势子 tab，默认 all"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档截图、HTML、Markdown 和接口响应"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="输出目录，默认当前目录下 seller_sprite_runs"),
    account: str | None = typer.Option(None, "--account", help="命名账号，未登录时自动登录后继续采集"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """围绕显式关键词执行完整采集。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect(
            SellerSpriteCollectOptions(
                asin=asin,
                keyword=keyword,
                site=site,
                period=period,
                limit=limit,
                frequency_phrase_count=frequency_phrase_count,
                trend_limit=trend_limit,
                trend_tabs=trend_tabs,
                archive=archive,
                output_dir=str(output_dir) if output_dir else None,
                account=account,
            )
        )
        payload = {"success": True, "command": "seller-sprite collect", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite collect", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("frequency")
def frequency(
    keyword: str = typer.Option(..., "--keyword", help="卖家精灵关键词挖掘入口词"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，例如 30d 或 2026-03"),
    frequency_phrase_count: int = typer.Option(1, "--frequency-phrase-count", min=1, max=10, help="高频词词组个数，默认 1"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档页面证据"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="输出目录，默认当前目录下 seller_sprite_runs"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """采集高频词。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect_frequency(
            SellerSpriteCollectOptions(
                keyword=keyword,
                site=site,
                period=period,
                frequency_phrase_count=frequency_phrase_count,
                archive=archive,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
        payload = {"success": True, "command": "seller-sprite frequency", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite frequency", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("keyword-mining")
def keyword_mining(
    keyword: str = typer.Option(..., "--keyword", help="卖家精灵关键词挖掘入口词"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，例如 30d 或 2026-03"),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="关键词采集条数，默认 50"),
    trend_limit: int = typer.Option(0, "--trend-limit", min=0, max=50, help="采集前 N 个关键词的历史走势弹窗，默认 0 不采集"),
    trend_tabs: str = typer.Option("all", "--trend-tabs", help="历史走势子 tab，默认 all"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档页面证据"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="输出目录，默认当前目录下 seller_sprite_runs"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """采集关键词挖掘结果。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect_keyword_mining(
            SellerSpriteCollectOptions(
                keyword=keyword,
                site=site,
                period=period,
                limit=limit,
                trend_limit=trend_limit,
                trend_tabs=trend_tabs,
                archive=archive,
                output_dir=str(output_dir) if output_dir else None,
            )
        )
        payload = {"success": True, "command": "seller-sprite keyword-mining", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite keyword-mining", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("keyword-reverse")
def keyword_reverse(
    asin: str = typer.Option(..., "--asin", help="Amazon ASIN 或产品链接中的 ASIN"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，例如 30d 或 2026-03"),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="关键词采集条数，默认 50"),
    trend_limit: int = typer.Option(0, "--trend-limit", min=0, max=50, help="采集前 N 个关键词的历史走势弹窗，默认 0 不采集"),
    trend_tabs: str = typer.Option("all", "--trend-tabs", help="历史走势子 tab，默认 all"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档页面证据"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="输出目录，默认当前目录下 seller_sprite_runs"),
    account: str | None = typer.Option(None, "--account", help="命名账号，未登录时自动登录后继续采集"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """采集关键词反查结果。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect_keyword_reverse(
            SellerSpriteCollectOptions(
                asin=asin,
                site=site,
                period=period,
                limit=limit,
                trend_limit=trend_limit,
                trend_tabs=trend_tabs,
                archive=archive,
                output_dir=str(output_dir) if output_dir else None,
                account=account,
            )
        )
        payload = {"success": True, "command": "seller-sprite keyword-reverse", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite keyword-reverse", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("archive")
def archive(
    url: str = typer.Option(..., "--url", help="需要归档的卖家精灵页面 URL"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="输出目录，默认当前目录下 seller_sprite_runs"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """归档指定页面。"""
    manager = SellerSpriteManager()
    try:
        result = manager.archive_url(SellerSpriteCollectOptions(url=url, output_dir=str(output_dir) if output_dir else None))
        payload = {"success": True, "command": "seller-sprite archive", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite archive", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("login")
def login(pretty: bool = typer.Option(False, "--pretty", help="格式化输出")):
    """打开浏览器并手动建立卖家精灵登录态。"""
    manager = SellerSpriteManager()
    try:
        result = manager.login()
        payload = {"success": True, "command": "seller-sprite login", "data": result, "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite login", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("login-status")
def login_status(
    output_dir: Path | None = typer.Option(None, "--output-dir", help="输出目录，默认当前目录下 seller_sprite_runs"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """检查当前浏览器 profile 是否已有卖家精灵登录态。"""
    manager = SellerSpriteManager()
    try:
        result = manager.login_status(SellerSpriteCollectOptions(output_dir=str(output_dir) if output_dir else None))
        payload = {"success": True, "command": "seller-sprite login-status", "data": result, "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite login-status", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@account_app.command("save")
def account_save(
    name: str = typer.Option(..., "--name", help="账号别名，例如 default"),
    username: str = typer.Option(..., "--username", help="卖家精灵用户名"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """保存卖家精灵命名账号，密码写入系统凭据管理器。"""
    password = typer.prompt("卖家精灵密码", hide_input=True)
    store = SellerSpriteAccountStore()
    try:
        result = store.save(name=name, username=username, password=password)
        payload = {"success": True, "command": "seller-sprite account save", "data": result, "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite account save", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@account_app.command("list")
def account_list(pretty: bool = typer.Option(False, "--pretty", help="格式化输出")):
    """列出卖家精灵命名账号，不输出密码。"""
    store = SellerSpriteAccountStore()
    try:
        result = store.list()
        payload = {"success": True, "command": "seller-sprite account list", "data": result, "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite account list", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@account_app.command("delete")
def account_delete(
    name: str = typer.Option(..., "--name", help="账号别名"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """删除卖家精灵命名账号。"""
    store = SellerSpriteAccountStore()
    try:
        result = {"name": name, "deleted": store.delete(name=name)}
        payload = {"success": True, "command": "seller-sprite account delete", "data": result, "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite account delete", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("schema")
def schema(pretty: bool = typer.Option(False, "--pretty", help="格式化输出")):
    """输出当前字段契约。"""
    manager = SellerSpriteManager()
    payload = {
        "success": True,
        "command": "seller-sprite schema",
        "data": manager.schema(),
        "error": None,
    }
    _emit(payload, pretty)
