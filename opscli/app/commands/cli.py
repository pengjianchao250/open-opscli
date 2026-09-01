"""AppHub 完整客户端 Typer 命令。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from opscli.app.domain.exceptions import AppError
from opscli.app.services.manager import AppManager

app = typer.Typer(help="AppHub 应用开发、校验、发布与运维")
git_app = typer.Typer(help="AppHub Git 凭据管理")
env_app = typer.Typer(help="应用环境变量管理")
secret_app = typer.Typer(help="应用密钥管理")
members_app = typer.Typer(help="应用成员管理")
db_app = typer.Typer(help="应用 SQLite 管理")
app.add_typer(git_app, name="git")
app.add_typer(env_app, name="env")
app.add_typer(secret_app, name="secret")
app.add_typer(members_app, name="members")
app.add_typer(db_app, name="db")


def _emit(payload: dict, *, json_output: bool, pretty: bool = True) -> None:
    """输出稳定 JSON 或简洁人类可读结果。"""
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))
        return
    if payload.get("success"):
        data = payload.get("data") or {}
        message = data.get("message")
        if message:
            typer.echo(message)
        for key in ("slug", "path", "status", "commit_sha", "release_id", "version", "tag", "url"):
            if data.get(key) is not None:
                typer.echo(f"{key}: {data[key]}")
        if not message and not any(data.get(key) is not None for key in ("slug", "status", "commit_sha", "release_id", "version", "tag", "url")):
            typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    error = payload.get("error") or {}
    typer.echo(f"错误 [{error.get('code', 'UNKNOWN')}]: {error.get('message', '未知错误')}", err=True)
    if error.get("fix_hint"):
        typer.echo(f"建议: {error['fix_hint']}", err=True)
    if error.get("request_id"):
        typer.echo(f"request_id: {error['request_id']}", err=True)


def _run(command: str, action, *, json_output: bool, pretty: bool = True) -> None:
    manager = AppManager()
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


@app.command("init")
def init_project(
    slug: str = typer.Argument(..., help="应用唯一 slug"),
    path: Path | None = typer.Option(None, "--path", help="目标目录，默认 ./<slug>"),
    runtime: str = typer.Option("streamlit", "--runtime", help="streamlit/fastapi/gradio"),
    title: str | None = typer.Option(None, "--title", help="应用显示名称"),
    offline: bool = typer.Option(False, "--offline", help="只生成模板，不登记 AppHub/Git"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    _run(
        "app init",
        lambda manager: manager.init_project(slug, path=path, runtime=runtime, title=title, offline=offline),
        json_output=json_output,
    )


@app.command("run")
def run(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    port: int = typer.Option(8000, "--port", min=1, max=65535),
    json_output: bool = typer.Option(False, "--json", help="应用退出后输出 JSON"),
) -> None:
    _run("app run", lambda manager: manager.run(path, port=port), json_output=json_output)


@app.command("validate")
def validate(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    _run("app validate", lambda manager: manager.validate(path), json_output=json_output)


@app.command("publish")
def publish(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    message: str | None = typer.Option(None, "--message", "-m", help="Git commit 与 release 说明，最长 512 字符"),
    resume: bool = typer.Option(False, "--resume", help="续订上一次中断的 release"),
    json_output: bool = typer.Option(False, "--json", help="只输出单个稳定 JSON 对象"),
    pretty: bool = typer.Option(True, "--pretty/--no-pretty", help="格式化 JSON 输出"),
) -> None:
    """强制 validate 后普通 commit/push，并显式创建 AppHub release。"""
    if not resume and not message and sys.stdin.isatty():
        message = typer.prompt("发布说明")

    def action(manager: AppManager):
        def progress(frame: dict) -> None:
            if not json_output and frame.get("message"):
                typer.echo(f"[{frame.get('status') or frame.get('level', 'info')}] {frame['message']}")

        return manager.publish(path, message=message, resume=resume, on_progress=progress)

    _run("app publish", action, json_output=json_output, pretty=pretty)


@app.command("pull")
def pull(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    _run("app pull", lambda manager: manager.pull(path), json_output=json_output)


@app.command("versions")
def versions(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(20, "--size", min=1, max=200),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    _run("app versions", lambda manager: manager.versions(path, page=page, size=size), json_output=json_output)


@app.command("rollback")
def rollback(
    version: str = typer.Argument(..., help="目标版本，如 v3 或 3"),
    path: Path = typer.Option(Path("."), "--path", help="应用根目录"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    version_number = _version_number(version)
    if not yes and not typer.confirm(f"确认回滚到 v{version_number}？"):
        raise typer.Abort()

    def action(manager: AppManager):
        return manager.rollback(
            version_number,
            path,
            on_progress=lambda frame: typer.echo(frame.get("message") or json.dumps(frame, ensure_ascii=False)) if not json_output else None,
        )

    _run("app rollback", action, json_output=json_output)


@app.command("logs")
def logs(
    path: Path = typer.Argument(Path("."), help="应用根目录"),
    build: bool = typer.Option(False, "--build", help="查看构建日志"),
    follow: bool = typer.Option(False, "--follow", "-f", help="持续跟踪日志"),
    tail: int = typer.Option(200, "--tail", help="200/500/1000"),
    release: str | None = typer.Option(None, "--release", help="指定 vN"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    def progress(frame: dict) -> None:
        if not json_output:
            typer.echo(frame.get("message") or frame.get("line") or json.dumps(frame, ensure_ascii=False))

    _run(
        "app logs",
        lambda manager: manager.logs(path, build=build, follow=follow, tail=tail, release=release, on_progress=progress),
        json_output=json_output,
    )


@git_app.command("status")
def git_status(path: Path = typer.Argument(Path(".")), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app git status", lambda manager: manager.git_status(path), json_output=json_output)


@git_app.command("bind")
def git_bind(
    path: Path = typer.Argument(Path(".")),
    rotate: bool = typer.Option(False, "--rotate"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run("app git bind", lambda manager: manager.git_bind(path, rotate=rotate), json_output=json_output)


@git_app.command("revoke")
def git_revoke(json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app git revoke", lambda manager: manager.git_revoke(), json_output=json_output)


@env_app.command("get")
def env_get(path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app env get", lambda manager: manager.env_get(path), json_output=json_output)


@env_app.command("set")
def env_set(
    key: str,
    value: str,
    path: Path = typer.Option(Path("."), "--path"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run("app env set", lambda manager: manager.env_set(key, value, path), json_output=json_output)


@env_app.command("unset")
def env_unset(key: str, path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app env unset", lambda manager: manager.env_unset(key, path), json_output=json_output)


@secret_app.command("list")
def secret_list(path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app secret list", lambda manager: manager.secret_list(path), json_output=json_output)


@secret_app.command("set")
def secret_set(
    key: str,
    value: str | None = typer.Option(None, "--value", help="省略时隐藏输入"),
    path: Path = typer.Option(Path("."), "--path"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    secret_value = value if value is not None else typer.prompt("Secret value", hide_input=True, confirmation_prompt=True)
    _run("app secret set", lambda manager: manager.secret_set(key, secret_value, path), json_output=json_output)


@secret_app.command("unset")
def secret_unset(key: str, path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app secret unset", lambda manager: manager.secret_unset(key, path), json_output=json_output)


@members_app.command("list")
def members_list(path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app members list", lambda manager: manager.members_list(path), json_output=json_output)


@members_app.command("add")
def members_add(email: str, path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app members add", lambda manager: manager.members_add(email, path), json_output=json_output)


@members_app.command("remove")
def members_remove(email: str, path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app members remove", lambda manager: manager.members_remove(email, path), json_output=json_output)


@db_app.command("info")
def db_info(path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app db info", lambda manager: manager.db_info(path), json_output=json_output)


@db_app.command("backups")
def db_backups(path: Path = typer.Option(Path("."), "--path"), json_output: bool = typer.Option(False, "--json")) -> None:
    _run("app db backups", lambda manager: manager.db_backups(path), json_output=json_output)


@db_app.command("restore")
def db_restore(
    backup_date: str = typer.Argument(..., help="YYYY-MM-DD"),
    path: Path = typer.Option(Path("."), "--path"),
    filename: str | None = typer.Option(None, "--file", help="final/prerestore 备份文件名"),
    confirm: str | None = typer.Option(None, "--confirm", help="必须等于应用 slug"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    confirmation = confirm if confirm is not None else typer.prompt("请输入应用 slug 确认恢复")
    _run(
        "app db restore",
        lambda manager: manager.db_restore(backup_date, confirmation, path, filename=filename),
        json_output=json_output,
    )


def _version_number(value: str) -> int:
    normalized = value.strip().lower().removeprefix("v")
    if not normalized.isdigit() or int(normalized) < 1:
        raise typer.BadParameter("版本必须为 vN 或正整数 N")
    return int(normalized)
