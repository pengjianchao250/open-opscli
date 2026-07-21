"""通用通知 CLI 子命令。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from opscli.notify.client import NotifyError, send_wecom_markdown


app = typer.Typer(help="发送企业微信等内部通知")


@app.callback()
def main() -> None:
    """保留 notify 命令组，避免单子命令时被 Typer 自动扁平化。"""


def _emit(payload: dict[str, Any]) -> None:
    """输出结构化 JSON 结果。"""
    typer.echo(json.dumps(payload, ensure_ascii=False))


def _read_wecom_webhook(credentials_file: Path) -> str:
    """从本地凭据 JSON 读取企业微信群机器人 Webhook。"""
    try:
        payload = json.loads(credentials_file.expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotifyError(f"通知凭据文件不存在: {credentials_file}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise NotifyError(f"无法读取通知凭据文件: {credentials_file}") from exc
    webhook = payload.get("wecom_webhook_url") if isinstance(payload, dict) else None
    if not isinstance(webhook, str) or not webhook.strip() or webhook.startswith("REPLACE_WITH_"):
        raise NotifyError("尚未配置企业微信机器人 Webhook")
    return webhook.strip()


def _read_markdown(content_file: Path) -> str:
    """从 UTF-8 文件读取待发送的 Markdown V2 内容。"""
    try:
        return content_file.expanduser().read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise NotifyError(f"Markdown 内容文件不存在: {content_file}") from exc
    except OSError as exc:
        raise NotifyError(f"无法读取 Markdown 内容文件: {content_file}") from exc


@app.command("wecom-markdown")
def wecom_markdown(
    credentials_file: Path = typer.Option(..., "--credentials-file", help="包含 wecom_webhook_url 的本地 JSON 文件"),
    content_file: Path = typer.Option(..., "--content-file", help="待发送的 UTF-8 Markdown 文件"),
) -> None:
    """从本地文件读取配置和内容并发送企业微信 Markdown V2。"""
    try:
        result = send_wecom_markdown(
            _read_wecom_webhook(credentials_file),
            _read_markdown(content_file),
        )
    except NotifyError as exc:
        _emit(
            {
                "success": False,
                "command": "notify wecom-markdown",
                "data": None,
                "error": {"code": "NOTIFY_ERROR", "message": str(exc)},
            }
        )
        raise typer.Exit(1)

    _emit(
        {
            "success": True,
            "command": "notify wecom-markdown",
            "data": result,
            "error": None,
        }
    )
