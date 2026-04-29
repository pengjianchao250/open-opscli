"""amazon-rufus CLI 子命令。"""

from __future__ import annotations

import json

import typer

from opscli.amazon_rufus.domain.exceptions import RufusError
from opscli.amazon_rufus.services.manager import RufusManager

app = typer.Typer(help="Amazon Rufus 自动问答采集")


@app.callback()
def main():
    """Amazon Rufus 命令组入口。"""


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _emit_answers_text(data: dict) -> None:
    """只输出 Rufus 回答文本。"""
    lines: list[str] = []
    for index, answer in enumerate(data.get("answers", []), start=1):
        text = str(answer.get("text") or "").strip()
        if text:
            lines.append(text)
            continue
        if answer.get("isSuccess") is False:
            lines.append(f"第 {index} 题未获取到答案")
    typer.echo("\n\n".join(lines))


def _error_payload(command: str, exc: Exception) -> dict:
    """统一错误结构。"""
    if isinstance(exc, RufusError):
        error = exc.to_dict()
    else:
        error = {"code": "RUFUS_ERROR", "message": str(exc)}
    return {"success": False, "command": command, "data": None, "error": error}


@app.command("get")
def get(
    asin: str = typer.Argument(..., help="目标 ASIN"),
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 根目录"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址"),
    new_chrome: bool = typer.Option(False, "--new-chrome", help="先新开 Chrome 调试窗口再连接"),
    keep_chrome_open: bool = typer.Option(False, "--keep-chrome-open", help="--new-chrome 执行完成后保留 Chrome 窗口"),
    chrome_path: str | None = typer.Option(None, "--chrome-path", help="Chrome 路径，当前预留"),
    launch_if_needed: bool = typer.Option(False, "--launch-if-needed", help="预留：必要时启动 Chrome"),
    timeout_seconds: int = typer.Option(90, "--timeout", min=1, help="等待超时秒数"),
    include_upload_payload: bool = typer.Option(True, "--upload-payload/--no-upload-payload", help="是否输出上传 payload"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """获取指定 ASIN 在 Rufus 中的题库回答。"""
    manager = RufusManager()
    try:
        data = manager.get(
            asin=asin,
            country=country,
            skills_dir=skills_dir,
            cdp_url=cdp_url,
            new_chrome=new_chrome,
            keep_chrome_open=keep_chrome_open,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            timeout_seconds=timeout_seconds,
            include_upload_payload=include_upload_payload,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus get", exc), pretty)
        raise typer.Exit(1)
    _emit_answers_text(data)

