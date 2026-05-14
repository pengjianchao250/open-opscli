"""amazon-rufus CLI 子命令。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

from opscli.amazon_rufus.domain.exceptions import RufusError
from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter
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


def _emit_answer_report(data: dict) -> None:
    """将前端风格的 Rufus 答案报告写入运行目录。"""
    report_text = AnswerReportFormatter().format_data(data)
    report_path = _write_answer_report(data, report_text)
    typer.echo(f"Rufus 答案报告已保存：{report_path.as_posix()}")


def _write_answer_report(data: dict, report_text: str) -> Path:
    """写入 Rufus 答案报告并返回面向用户的相对路径。"""
    output_dir = Path("output") / "amazon-rufus"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / _build_answer_report_filename(data)
    report_path.write_text(report_text, encoding="utf-8")
    return report_path


def _build_answer_report_filename(data: dict) -> str:
    """按 ASIN 与秒级运行时间生成稳定报告文件名。"""
    asin = str(data.get("asin") or "UNKNOWN").strip().upper() or "UNKNOWN"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{asin}-{timestamp}.md"


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
    question: str | None = typer.Option(None, "--question", help="指定单题 Rufus 问题，传入后跳过默认题库"),
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
            question=question,
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
    _emit_answer_report(data)


@app.command("init")
def init(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址"),
    timeout_seconds: int = typer.Option(30, "--timeout", min=1, help="等待超时秒数"),
    pretty: bool = typer.Option(False, "--pretty", help="错误时格式化输出"),
):
    """打开对应国家站点，供用户登录 Amazon。"""
    manager = RufusManager()
    try:
        manager.init(country=country, cdp_url=cdp_url, timeout_seconds=timeout_seconds)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus init", exc), pretty)
        raise typer.Exit(1)
    typer.echo("请在新窗口中登录亚马逊")

