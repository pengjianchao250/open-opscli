"""MCP 管理 CLI。

提供 MCP Server 多用户模式下的用户注册、删除与 API Key 轮换能力。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.mcp.user_store import MCPUserStore


app = typer.Typer(help="MCP Server 管理")
user_app = typer.Typer(help="MCP 用户管理")
app.add_typer(user_app, name="user")


def _emit(payload: dict, pretty: bool) -> None:
    """统一 JSON 输出。"""
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


def _store(config_dir: str | None = None) -> MCPUserStore:
    """创建用户注册表实例，测试可通过 --config-dir 指向临时目录。"""
    return MCPUserStore(base_dir=Path(config_dir).expanduser() if config_dir else None)


@user_app.command("list")
def list_users(
    config_dir: str | None = typer.Option(None, "--config-dir", help="指定 opscli 配置目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """列出所有 MCP 用户。"""
    users = [item.to_dict() for item in _store(config_dir).list_users()]
    _emit({"success": True, "command": "mcp user list", "data": users, "error": None}, pretty)


@user_app.command("add")
def add_user(
    desc: str = typer.Option("", "--desc", help="用户描述"),
    config_dir: str | None = typer.Option(None, "--config-dir", help="指定 opscli 配置目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """创建 MCP 用户并输出只展示一次的 API Key。"""
    result = _store(config_dir).add_user(description=desc)
    _emit(
        {
            "success": True,
            "command": "mcp user add",
            "data": result,
            "warning": "请立即保存 api_key，它只显示一次，服务端不保存明文。",
            "error": None,
        },
        pretty,
    )


@user_app.command("remove")
def remove_user(
    user_id: str = typer.Option(..., "--id", help="MCP 用户 ID"),
    keep_credentials: bool = typer.Option(False, "--keep-credentials", help="保留凭证目录"),
    config_dir: str | None = typer.Option(None, "--config-dir", help="指定 opscli 配置目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """删除 MCP 用户，默认同步删除隔离凭证目录。"""
    removed = _store(config_dir).remove_user(user_id, keep_credentials=keep_credentials)
    payload = {
        "success": removed,
        "command": "mcp user remove",
        "data": {"removed": user_id} if removed else None,
        "error": None if removed else {"code": "MCP_USER_NOT_FOUND", "message": f"未找到 MCP 用户: {user_id}"},
    }
    _emit(payload, pretty)
    if not removed:
        raise typer.Exit(1)


@user_app.command("rotate")
def rotate_user(
    user_id: str = typer.Option(..., "--id", help="MCP 用户 ID"),
    config_dir: str | None = typer.Option(None, "--config-dir", help="指定 opscli 配置目录"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """轮换 MCP 用户 API Key，新 Key 只展示一次。"""
    try:
        result = _store(config_dir).rotate_api_key(user_id)
        payload = {
            "success": True,
            "command": "mcp user rotate",
            "data": result,
            "warning": "请立即保存 api_key，它只显示一次，服务端不保存明文。",
            "error": None,
        }
    except Exception as exc:
        payload = {
            "success": False,
            "command": "mcp user rotate",
            "data": None,
            "error": {"code": type(exc).__name__, "message": str(exc)},
        }
        _emit(payload, pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)
