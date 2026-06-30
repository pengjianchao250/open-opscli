"""asin_review CLI 子命令。

提供复盘 ASIN 数据查询的命令行入口。

命令：
    opscli asin-review fetch    — 拉取复盘数据
"""

from __future__ import annotations

import json

import typer

from opscli.asin_review.services.manager import AsinReviewManager

app = typer.Typer(help="复盘 ASIN 数据查询")


@app.callback()
def _main() -> None:
    """复盘 ASIN 命令组入口。"""


def _emit(payload: dict, pretty: bool) -> None:
    """输出 JSON 到终端。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    typer.echo(text)


def _error_payload(command: str, exc: Exception) -> dict:
    """构造标准错误响应。"""
    if hasattr(exc, "to_dict"):
        error = exc.to_dict()
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}
    return {"success": False, "command": command, "data": None, "error": error}


@app.command("fetch")
def fetch(
    asin: str = typer.Option(..., "--asin", help="Amazon ASIN"),
    start_date: str = typer.Option(..., "--start-date", help="开始日期，格式 YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="结束日期，格式 YYYY-MM-DD"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
) -> None:
    """拉取指定 ASIN 在日期范围内的复盘数据。

    示例：
        opscli asin-review fetch --asin 10043986503 --start-date 2026-01-01 --end-date 2026-01-31 --pretty
    """
    try:
        manager = AsinReviewManager()
        result = manager.fetch(
            asin=asin,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        _emit(_error_payload("asin-review fetch", exc), pretty)
        raise typer.Exit(1)

    _emit(result.to_dict(), pretty)


__all__ = ["app"]
