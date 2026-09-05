"""AppHub 应用创建、Git 初始化、源码推送与版本发布命令。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.app.domain.exceptions import AppError
from opscli.app.services.manager import AppManager

app = typer.Typer(help="管理 AppHub 应用信息、Git 仓库、源码推送和版本发布")


def _emit_release_event(event: dict) -> None:
    if event.get("level") == "hidden":
        return
    message = event.get("message")
    if message:
        typer.echo(f"[release:{event.get('seq', '-')}] {message}")


def _emit(payload: dict, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("success"):
        data = payload.get("data") or {}
        if data.get("message"):
            typer.echo(data["message"])
        for key in (
            "app_id",
            "app_name",
            "slug",
            "path",
            "repo_url",
            "default_branch",
            "commit_sha",
            "release_id",
            "version",
            "status",
            "url",
            "reason_code",
        ):
            if data.get(key) is not None:
                typer.echo(f"{key}: {data[key]}")
        return
    error = payload.get("error") or {}
    typer.echo(f"错误 [{error.get('code', 'UNKNOWN')}]: {error.get('message', '未知错误')}", err=True)
    if error.get("fix_hint"):
        typer.echo(f"建议: {error['fix_hint']}", err=True)
    if error.get("request_id"):
        typer.echo(f"request_id: {error['request_id']}", err=True)


def _run(command: str, action, *, json_output: bool) -> None:
    manager = AppManager(
        release_event_handler=None if json_output else _emit_release_event
    )
    try:
        _emit(
            {"success": True, "command": command, "data": action(manager), "error": None},
            json_output=json_output,
        )
    except AppError as exc:
        _emit(
            {"success": False, "command": command, "data": None, "error": exc.to_dict()},
            json_output=json_output,
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
                    "detail": {"error_type": type(exc).__name__},
                },
            },
            json_output=json_output,
        )
        raise typer.Exit(1) from exc
    finally:
        manager.close()


@app.command("create")
def create_app(
    app_name: str = typer.Argument(..., help="应用名称"),
    path: Path | None = typer.Option(None, "--path", help="绑定目录；默认使用应用 slug"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """在 AppHub 创建应用并保存本地基础信息。"""
    _run(
        "app create",
        lambda manager: manager.create_app(app_name, path=path),
        json_output=json_output,
    )


@app.command("init")
def init_git(
    path: Path = typer.Argument(Path("."), help="应用源码目录"),
    app_slug: str | None = typer.Option(None, "--app", help="要恢复或创建的应用 slug"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """恢复应用信息并初始化本地 Git，不生成或覆盖业务源码。"""
    _run(
        "app init",
        lambda manager: manager.init_git(path, app_slug=app_slug),
        json_output=json_output,
    )


@app.command("push")
def push(
    path: Path = typer.Argument(Path("."), help="应用源码目录"),
    message: str = typer.Option(..., "--message", "-m", help="Git 提交说明"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """提交并推送源码到远端 main，不创建 AppHub release。"""
    _run(
        "app push",
        lambda manager: manager.push(path, message=message),
        json_output=json_output,
    )


@app.command("release")
def release(
    path: Path = typer.Argument(Path("."), help="应用源码目录"),
    message: str = typer.Option(..., "--message", "-m", help="版本发布说明"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """确保源码已推送，再创建并跟踪 AppHub release。"""
    _run(
        "app release",
        lambda manager: manager.release(path, message=message),
        json_output=json_output,
    )
