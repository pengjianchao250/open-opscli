"""feedback CLI 子命令定义。"""

from __future__ import annotations

import json

import typer

from opscli.feedback.domain.exceptions import FeedbackError, InvalidPayloadError
from opscli.feedback.services.manager import FeedbackManager, load_json_arg, load_json_file

app = typer.Typer(help="用户反馈提交与查询")


def _emit(payload: dict, pretty: bool) -> None:
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _error_payload(command: str, exc: Exception) -> dict:
    if isinstance(exc, FeedbackError):
        error = exc.to_dict()
    else:
        error = {
            "code": "FEEDBACK_ERROR",
            "message": str(exc),
        }
    return {
        "success": False,
        "command": command,
        "data": None,
        "error": error,
    }


def _pick_json(inline_value: str | None, file_path: str | None, *, label: str):
    if inline_value and file_path:
        raise InvalidPayloadError(f"--{label} 和 --{label}-file 只能使用一种")
    return load_json_arg(inline_value, label=label) if inline_value else load_json_file(file_path, label=label)


@app.command("schema")
def schema(pretty: bool = typer.Option(False, "--pretty", help="格式化输出")):
    """输出反馈 payload schema。"""
    payload = {
        "success": True,
        "command": "feedback schema",
        "data": FeedbackManager().schema(),
        "error": None,
    }
    _emit(payload, pretty)


@app.command("submit")
def submit(
    file: str | None = typer.Option(None, "--file", help="完整反馈 JSON 文件路径"),
    feedback_type: str | None = typer.Option(None, "--type", "--feedback-type", help="反馈类型"),
    severity: str = typer.Option("medium", "--severity", help="严重度"),
    title: str | None = typer.Option(None, "--title", help="反馈标题"),
    content: str | None = typer.Option(None, "--content", help="反馈正文"),
    source: str = typer.Option("cli", "--source", help="反馈来源: cli/mcp/skill/api"),
    payload_json: str | None = typer.Option(None, "--payload", help="原始结构化反馈 JSON 字符串"),
    payload_file: str | None = typer.Option(None, "--payload-file", help="原始结构化反馈 JSON 文件"),
    context_json: str | None = typer.Option(None, "--context", help="执行上下文 JSON 字符串"),
    context_file: str | None = typer.Option(None, "--context-file", help="执行上下文 JSON 文件"),
    execution_summary_json: str | None = typer.Option(None, "--execution-summary", help="执行总结 JSON 字符串"),
    execution_summary_file: str | None = typer.Option(None, "--execution-summary-file", help="执行总结 JSON 文件"),
    attachments_json: str | None = typer.Option(None, "--attachments", help="附件引用 JSON 数组字符串"),
    attachments_file: str | None = typer.Option(None, "--attachments-file", help="附件引用 JSON 数组文件"),
    skill_name: str | None = typer.Option(None, "--skill-name", help="Skill 名称"),
    skill_version: str | None = typer.Option(None, "--skill-version", help="Skill 版本"),
    command_name: str | None = typer.Option(None, "--command-name", help="CLI 命令名称"),
    mcp_tool_name: str | None = typer.Option(None, "--mcp-tool-name", help="MCP Tool 名称"),
    client_name: str = typer.Option("opscli", "--client-name", help="客户端名称"),
    system_alias: str = typer.Option("ops", "--system", help="系统别名"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """提交用户反馈。"""
    manager = FeedbackManager()
    try:
        if file:
            if any([feedback_type, title, content, payload_json, payload_file, context_json, context_file]):
                raise InvalidPayloadError("--file 模式下不要同时传入字段覆盖参数")
            full_payload = load_json_file(file, label="file")
            if not isinstance(full_payload, dict):
                raise InvalidPayloadError("--file 内容必须是 JSON 对象")
            result = manager.submit_payload(full_payload)
        else:
            if not feedback_type:
                raise InvalidPayloadError("必须提供 --type 或使用 --file")
            if not title:
                raise InvalidPayloadError("必须提供 --title 或使用 --file")
            if not content:
                raise InvalidPayloadError("必须提供 --content 或使用 --file")

            payload_obj = _pick_json(payload_json, payload_file, label="payload")
            context_obj = _pick_json(context_json, context_file, label="context")
            execution_summary = _pick_json(execution_summary_json, execution_summary_file, label="execution-summary")
            attachments = _pick_json(attachments_json, attachments_file, label="attachments")

            if attachments is not None and not isinstance(attachments, list):
                raise InvalidPayloadError("attachments 必须是 JSON 数组")

            result = manager.submit(
                feedback_type=feedback_type,
                title=title,
                content=content,
                severity=severity,
                source=source,
                payload=payload_obj,
                context=context_obj,
                execution_summary=execution_summary,
                attachments=attachments,
                system_alias=system_alias,
                client_name=client_name,
                skill_name=skill_name,
                skill_version=skill_version,
                command_name=command_name,
                mcp_tool_name=mcp_tool_name,
            )

        response = {
            "success": True,
            "command": "feedback submit",
            "data": result.get("data", result),
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("feedback submit", exc), pretty)
        raise typer.Exit(1)

    _emit(response, pretty)


@app.command("detail")
def detail(
    feedback_uuid: str = typer.Option(..., "--uuid", "--feedback-uuid", help="反馈 UUID"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """按 feedback_uuid 查询当前用户反馈详情。"""
    manager = FeedbackManager()
    try:
        result = manager.detail(feedback_uuid)
        payload = {
            "success": True,
            "command": "feedback detail",
            "data": result.get("data", result),
            "error": None,
        }
    except Exception as exc:
        _emit(_error_payload("feedback detail", exc), pretty)
        raise typer.Exit(1)

    _emit(payload, pretty)
