"""西柚 OpenAPI 远端 MCP 正式 CLI。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import typer

from opscli.xiyou.contracts import XydcOperation
from opscli.xiyou.remote_adapter import XiyouRemoteAdapter


app = typer.Typer(help="西柚 OpenAPI 远端 MCP 正式命令面。")


@app.command("operations")
def operations() -> None:
    """读取远端公共操作目录及其参数合同。"""
    _emit(XiyouRemoteAdapter().operations())


@app.command("call")
def call_operation(
    operation: str = typer.Argument(..., help="公共操作名，先用 operations 查看目录"),
    payload: str | None = typer.Option(None, "--payload", help="请求参数 JSON 对象字符串"),
    payload_file: Path | None = typer.Option(
        None, "--payload-file", help="UTF-8 JSON 对象文件，避免终端转义问题",
        exists=True, dir_okay=False, readable=True,
    ),
    output: Path | None = typer.Option(
        None, "--output", help="保存完整响应为 UTF-8 JSON 文件",
        dir_okay=False,
    ),
) -> None:
    """通过正式远端 MCP 执行查询，不在本机初始化供应商 Provider。"""
    if operation not in get_args(XydcOperation):
        raise typer.BadParameter("不支持的公共 operation，请先查看 opscli xiyou operations")
    request = _read_payload(payload, payload_file)
    # 输出参数先校验，避免收费请求完成后才发现目标目录不存在。
    if output is not None and not output.parent.is_dir():
        raise typer.BadParameter("--output 的父目录必须已存在")
    _emit(XiyouRemoteAdapter().call(operation, request), output)


def _read_payload(payload: str | None, payload_file: Path | None) -> dict[str, Any]:
    """强制二选一并检查 JSON 对象；业务字段由远端正式合同校验。"""
    if (payload is not None) == (payload_file is not None):
        raise typer.BadParameter("必须且只能提供 --payload 或 --payload-file 其中一个")
    try:
        raw = payload_file.read_text(encoding="utf-8-sig") if payload_file else payload
        value = json.loads(raw)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter("payload 必须是有效的 UTF-8 JSON 对象") from exc
    if not isinstance(value, dict):
        raise typer.BadParameter("payload 必须是 JSON 对象")
    return value


def _emit(response: dict[str, Any], output: Path | None = None) -> None:
    """保留完整远端合同和错误取证，业务失败以非零退出码标识。"""
    text = json.dumps(response, ensure_ascii=False, indent=2)
    if output is not None:
        output.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)
    if response.get("success") is False:
        raise typer.Exit(1)
