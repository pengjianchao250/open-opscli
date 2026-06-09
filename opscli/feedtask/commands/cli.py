"""通用工单 CLI 命令。

提供工单创建和查询的命令行入口，所有命令输出统一 JSON 格式。
"""

import json
import sys
from typing import Optional

import typer

from opscli.feedtask.domain.exceptions import FeedTaskError
from opscli.feedtask.services.manager import FeedTaskManager

app = typer.Typer(help="通用工单管理")


def _emit(payload: dict, *, pretty: bool = True) -> None:
    """输出 JSON 结果。"""
    indent = 2 if pretty else None
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=indent))


def _error_payload(command: str, exc: Exception) -> dict:
    """构造错误输出，识别认证异常并给出友好提示。"""
    from opscli.auth.exceptions import NotAuthenticatedError

    if isinstance(exc, FeedTaskError):
        return {"success": False, "command": command, "data": None, "error": exc.to_dict()}
    if isinstance(exc, NotAuthenticatedError):
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": {
                "code": "NOT_AUTHENTICATED",
                "message": str(exc),
                "hint": "请先执行 opscli auth login 完成 polaris 系统授权登录",
            },
        }
    return {"success": False, "command": command, "data": None, "error": {"code": "UNKNOWN", "message": str(exc)}}


def _check_auth() -> None:
    """执行命令前检查 polaris 登录状态，未登录则直接报错退出。"""
    from opscli.auth import AuthClient

    client = AuthClient()
    if not client.is_authenticated():
        _emit({
            "success": False,
            "command": "feedtask",
            "data": None,
            "error": {
                "code": "NOT_AUTHENTICATED",
                "message": "未登录，请先完成 polaris 授权",
                "hint": "执行 opscli auth login 完成登录后重试",
            },
        })
        raise typer.Exit(1)


@app.command("create")
def create(
    payload_file: str = typer.Option(..., "--payload", help="工单 payload JSON 文件路径"),
) -> None:
    """创建工单（通用）。"""
    _check_auth()
    manager = FeedTaskManager()
    try:
        with open(payload_file, encoding="utf-8") as f:
            payload = json.load(f)
        result = manager.create(payload)
        _emit({"success": True, "command": "feedtask create", "data": result.to_dict(), "error": None})
    except Exception as exc:
        _emit(_error_payload("feedtask create", exc))
        sys.exit(1)


@app.command("status")
def status(
    task_id: str = typer.Option(..., "--task-id", help="工单 ID"),
) -> None:
    """查询工单状态/详情。"""
    _check_auth()
    manager = FeedTaskManager()
    try:
        result = manager.get_detail(task_id)
        _emit({"success": True, "command": "feedtask status", "data": result.to_dict(), "error": None})
    except Exception as exc:
        _emit(_error_payload("feedtask status", exc))
        sys.exit(1)
