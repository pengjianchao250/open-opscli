"""Codex 站点创建、Git 初始化与源码推送命令。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.app.domain.exceptions import AppError
from opscli.app.services.manager import AppManager

app = typer.Typer(help="创建并绑定 Codex 站点，初始化 Git 项目并推送源码")


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
            "site_name",
            "slug",
            "path",
            "repo_url",
            "default_branch",
            "template_applied",
            "commit_sha",
            "release_id",
            "version",
            "status",
            "url",
            "error_code",
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
def create_site(
    site_name: str = typer.Argument(..., help="站点名称"),
    path: Path | None = typer.Option(None, "--path", help="绑定目录；默认使用服务返回的 slug"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """在 AppHub 创建站点并绑定本地目录。"""
    _run(
        "app create",
        lambda manager: manager.create_site(site_name, path=path),
        json_output=json_output,
    )


@app.command("init")
def init_git(
    path: Path = typer.Argument(Path("."), help="已绑定的站点目录"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """初始化 Git；已有源码时保留源码并跳过模板。"""
    _run("app init", lambda manager: manager.init_git(path), json_output=json_output)


@app.command("push")
def push(
    path: Path = typer.Argument(Path("."), help="已初始化的站点目录"),
    message: str = typer.Option(..., "--message", "-m", help="Codex 对当前修改的一句话总结"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """普通推送站点源码，并触发 AppHub release 与 SSE 跟踪。"""
    _run(
        "app push",
        lambda manager: manager.push(path, message=message),
        json_output=json_output,
    )
