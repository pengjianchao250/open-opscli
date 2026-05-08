"""Feedback 工具模块。

将用户反馈提交能力暴露为 MCP 工具：
- feedback_submit  — 保存结构化用户反馈
- feedback_detail  — 按 feedback_uuid 查询当前用户反馈详情

反馈中的 execution_summary 用于记录本次 Skill/CLI/MCP 执行总结，
特别是失败工具调用的复盘信息。
"""

from __future__ import annotations

from .helpers import _auth_client, _err, _get_auth_pair, _ok


def _feedback_manager(jwt: str | None = None, session_id: str | None = None):
    from opscli.feedback.services.manager import FeedbackManager

    return FeedbackManager(auth_client=_auth_client(), jwt=jwt, session_id=session_id)


async def feedback_submit(
    feedback_type: str,
    title: str,
    content: str,
    severity: str = "medium",
    source: str = "mcp",
    payload: dict | None = None,
    context: dict | None = None,
    execution_summary: dict | None = None,
    attachments: list[dict] | None = None,
    skill_name: str | None = None,
    skill_version: str | None = None,
    command_name: str | None = None,
    mcp_tool_name: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """保存用户反馈的信息，以 JSON 结构提交到 ops。

    Args:
        feedback_type: 反馈类型：bug/feature/data_issue/ux/docs/other
        title: 反馈标题，最多 200 字符
        content: 反馈正文
        severity: 严重度：low/medium/high/critical，默认 medium
        source: 反馈来源：cli/mcp/skill/api，默认 mcp
        payload: 原始结构化反馈内容
        context: 执行上下文，如命令、工具、Skill、版本、cwd 等
        execution_summary: 本次执行总结。若有失败工具调用，failed_calls 每项必须包含：
            - tool: 具体工具或命令，如 "Bash → opscli query simple --table-id 1 ..."
            - call_params: 具体关键参数和字段值
            - error_message: 原始错误码和错误文本
            - reason: 原因；不确定时标注为推测
            - fix_suggestion: 已采用的修复方式或下一步建议
        attachments: 附件、截图、日志等引用信息；不上传大文件
        skill_name: Skill 名称
        skill_version: Skill 版本
        command_name: CLI 命令名称
        mcp_tool_name: MCP Tool 名称
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt: 可选，已有 JWT（为空则自动加载本地缓存的）
    """
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"), auto_feedback=False)
    try:
        result = _feedback_manager(jwt=jw, session_id=sid).submit(
            feedback_type=feedback_type,
            title=title,
            content=content,
            severity=severity,
            source=source,
            payload=payload,
            context=context,
            execution_summary=execution_summary,
            attachments=attachments,
            client_name="opscli-mcp",
            skill_name=skill_name,
            skill_version=skill_version,
            command_name=command_name,
            mcp_tool_name=mcp_tool_name,
        )
        return _ok(result.get("data", result))
    except Exception as exc:
        return _err(exc, auto_feedback=False)


async def feedback_detail(
    feedback_uuid: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """按 feedback_uuid 查询当前用户提交的反馈详情。

    Args:
        feedback_uuid: feedback_submit 返回的反馈 UUID
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt: 可选，已有 JWT（为空则自动加载本地缓存的）
    """
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"), auto_feedback=False)
    try:
        result = _feedback_manager(jwt=jw, session_id=sid).detail(feedback_uuid)
        return _ok(result.get("data", result))
    except Exception as exc:
        return _err(exc, auto_feedback=False)


def register(mcp) -> None:
    """注册 feedback MCP tools。"""
    for fn in (feedback_submit, feedback_detail):
        mcp.tool()(fn)
