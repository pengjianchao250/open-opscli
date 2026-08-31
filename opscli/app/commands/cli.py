"""AppHub 应用发布 Typer 命令。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from opscli.app.domain.exceptions import AppError
from opscli.app.services.publish import PublishManager

app = typer.Typer(help="AppHub 应用发布")
git_app = typer.Typer(help="AppHub Git 凭据管理")
app.add_typer(git_app, name="git")


def _emit(payload: dict, *, json_output: bool, pretty: bool = True) -> None:
    """输出稳定 JSON 或简洁人类可读结果。"""
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))
        return
    if payload.get("success"):
        data = payload.get("data") or {}
        message = data.get("message") or "操作成功。"
        typer.echo(message)
        for key in ("slug", "status", "commit_sha", "release_id", "version", "tag", "url"):
            if data.get(key) is not None:
                typer.echo(f"{key}: {data[key]}")
        return
    error = payload.get("error") or {}
    typer.echo(f"错误 [{error.get('code', 'UNKNOWN')}]: {error.get('message', '未知错误')}", err=True)
    if error.get("fix_hint"):
        typer.echo(f"建议: {error['fix_hint']}", err=True)
    if error.get("request_id"):
        typer.echo(f"request_id: {error['request_id']}", err=True)


def _run(command: str, action, *, json_output: bool, pretty: bool = True) -> None:
    manager = PublishManager()
    try:
        data = action(manager)
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        _emit({"success": True, "command": command, "data": data, "error": None}, json_output=json_output, pretty=pretty)
    except AppError as exc:
        _emit(
            {"success": False, "command": command, "data": None, "error": exc.to_dict()},
            json_output=json_output,
            pretty=pretty,
        )
        raise typer.Exit(1) from exc
    except Exception as exc:
        _emit(
            {
                "success": False,
                "command": command,
                "data": None,
                "error": {
                    "code": "UNKNOWN",
                    "message": "命令发生未预期错误。",
                    "fix_hint": "重试后仍失败请提交反馈。",
                    "request_id": None,
                    "release_id": None,
                    "detail": {"error_type": type(exc).__name__},
                },
            },
            json_output=json_output,
            pretty=pretty,
        )
        raise typer.Exit(1) from exc
    finally:
        manager.close()


@app.command("publish")
def publish(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    message: str | None = typer.Option(None, "--message", "-m", help="Git commit 与 release 说明，最长 512 字符"),
    resume: bool = typer.Option(False, "--resume", help="续订上一次中断的 release"),
    json_output: bool = typer.Option(False, "--json", help="只输出单个稳定 JSON 对象"),
    pretty: bool = typer.Option(True, "--pretty/--no-pretty", help="格式化 JSON 输出"),
) -> None:
    """校验、普通 commit/push，并显式创建 AppHub release。"""
    if not resume and not message and sys.stdin.isatty():
        message = typer.prompt("发布说明")

    def action(manager: PublishManager):
        def progress(frame: dict) -> None:
            if not json_output and frame.get("message"):
                typer.echo(f"[{frame.get('status') or frame.get('level', 'info')}] {frame['message']}")

        return manager.publish(
            path,
            message=message,
            resume=resume,
            on_progress=progress,
        )

    _run("app publish", action, json_output=json_output, pretty=pretty)


@git_app.command("status")
def git_status(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """检查应用仓库和本机 Git 凭据。"""
    _run("app git status", lambda manager: manager.git_status(path), json_output=json_output)


@git_app.command("bind")
def git_bind(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    rotate: bool = typer.Option(False, "--rotate", help="吊销旧凭据后签发新凭据"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """签发一次性 token，写入受控 helper 并探活。"""
    _run(
        "app git bind",
        lambda manager: manager.git_bind(path, rotate=rotate),
        json_output=json_output,
    )


@git_app.command("revoke")
def git_revoke(
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """吊销当前用户的 AppHub Git 凭据并删除本地副本。"""
    _run("app git revoke", lambda manager: manager.git_revoke(), json_output=json_output)
