"""MCP 请求上下文管理。

基于 Python contextvars 实现，在 HTTP/SSE 中间件和 Tool 函数之间传递
当前请求的 API Key 和用户信息。

天然支持 async 并发隔离，每个请求拥有独立的上下文。
"""

from __future__ import annotations

import contextvars
from typing import Any

# 当前 MCP 请求的上下文变量
mcp_request_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "mcp_request", default=None
)


def get_current_api_key() -> str | None:
    """获取当前请求中的 API Key（明文）。

    Returns:
        API Key 字符串，或 None（stdio 模式或无上下文）
    """
    ctx = mcp_request_ctx.get()
    return ctx.get("api_key") if ctx else None


def get_current_user_id() -> str | None:
    """获取当前请求关联的用户 ID（来自 OPS 后端校验接口）。

    Returns:
        用户 ID 字符串，或 None
    """
    ctx = mcp_request_ctx.get()
    return ctx.get("user_id") if ctx else None


def get_current_user_email() -> str | None:
    """获取当前请求关联的用户邮箱（来自 OPS 后端校验接口）。

    Returns:
        邮箱字符串，或 None
    """
    ctx = mcp_request_ctx.get()
    return ctx.get("email") if ctx else None
