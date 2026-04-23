"""amazon CLI 子命令定义。"""

from __future__ import annotations

import json

import typer

from opscli.amazon.domain.exceptions import AmazonError
from opscli.amazon.services.manager import AmazonManager

app = typer.Typer(help="Amazon 商品抓取与 ops 提交通道")


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _error_payload(command: str, exc: Exception) -> dict:
    """统一错误输出。"""
    if isinstance(exc, AmazonError):
        error = exc.to_dict()
    else:
        error = {
            "code": "AMAZON_ERROR",
            "message": str(exc),
        }
    return {
        "success": False,
        "command": command,
        "data": None,
        "error": error,
    }


@app.command("scrape")
def scrape(
    asin: str = typer.Option(..., "--asin", help="目标 ASIN"),
    zip_code: str = typer.Option("10001", "--zip-code", help="邮编，用于稳定价格口径"),
    save_history: bool = typer.Option(True, "--save-history/--no-save-history", help="是否保存本地历史"),
    include_raw: bool = typer.Option(False, "--include-raw", help="是否输出原始抓取字段"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """抓取单个商品。"""
    manager = AmazonManager()
    try:
        result = manager.scrape_product(
            asin=asin,
            zip_code=zip_code,
            save_history=save_history,
        )
        payload = {
            "success": True,
            "command": "amazon scrape",
            "data": result.to_dict(include_raw=include_raw),
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("amazon scrape", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("payload")
def payload(
    asin: str = typer.Option(..., "--asin", help="目标 ASIN"),
    zip_code: str = typer.Option("10001", "--zip-code", help="邮编，用于稳定价格口径"),
    save_history: bool = typer.Option(True, "--save-history/--no-save-history", help="是否保存本地历史"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """抓取商品并输出未来提交给 ops 的标准 payload。"""
    manager = AmazonManager()
    try:
        result = manager.scrape_payload(
            asin=asin,
            zip_code=zip_code,
            save_history=save_history,
        )
        response = {
            "success": True,
            "command": "amazon payload",
            "data": result,
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("amazon payload", exc), pretty)
        raise typer.Exit(1)

    _emit(response, pretty)


@app.command("search")
def search(
    keyword: str = typer.Option(..., "--keyword", help="搜索关键词"),
    zip_code: str = typer.Option("10001", "--zip-code", help="邮编，用于稳定价格口径"),
    limit: int = typer.Option(10, "--limit", min=1, max=50, help="最大结果数"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """抓取搜索结果页。"""
    manager = AmazonManager()
    try:
        results = manager.search_products(keyword=keyword, zip_code=zip_code, limit=limit)
        payload = {
            "success": True,
            "command": "amazon search",
            "data": {
                "keyword": keyword,
                "zip_code": zip_code,
                "count": len(results),
                "results": [item.to_dict() for item in results],
            },
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("amazon search", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)


@app.command("schema")
def schema(pretty: bool = typer.Option(False, "--pretty", help="格式化输出")):
    """输出当前 Amazon 抓取模型与 API 预留结构。"""
    payload = {
        "success": True,
        "command": "amazon schema",
        "data": {
            "snapshot_fields": {
                "asin": "string",
                "zip_code": "string",
                "marketplace": "string",
                "page_url": "string",
                "page_title": "string",
                "product_name": "string",
                "price_text": "string",
                "price_amount": "number|null",
                "currency": "string|null",
                "rating_text": "string",
                "rating_value": "number|null",
                "review_count_text": "string",
                "review_count_value": "integer|null",
                "location": "string",
                "collected_at": "string",
                "valid": "boolean",
                "error": "string|null",
                "raw": "object|null",
            },
            "reserved_submit_payload": {
                "source": "string",
                "snapshot": "AmazonProductSnapshot",
            },
            "search_result_fields": {
                "asin": "string",
                "keyword": "string",
                "zip_code": "string",
                "rank": "integer",
                "title": "string",
                "price_text": "string",
                "price_amount": "number|null",
                "rating_text": "string",
                "rating_value": "number|null",
                "review_count_text": "string",
                "review_count_value": "integer|null",
                "is_best_seller": "boolean",
            },
        },
        "error": None,
    }
    _emit(payload, pretty)


@app.command("history")
def history(
    asin: str = typer.Option(..., "--asin", help="目标 ASIN"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取本地历史快照。"""
    manager = AmazonManager()
    try:
        records = manager.load_history(asin)
        payload = {
            "success": True,
            "command": "amazon history",
            "data": {
                "asin": asin.upper(),
                "count": len(records),
                "records": records,
            },
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("amazon history", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)
