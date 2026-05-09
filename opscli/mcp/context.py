"""MCP 请求上下文管理。

基于 Python contextvars 实现，在 HTTP/SSE 中间件和 Tool 函数之间传递
当前请求的 API Key 和用户信息。

天然支持 async 并发隔离，每个请求拥有独立的上下文。

双重读取策略（解决 SSE 模式下 contextvar 传播不一致的问题）：
1. 优先从 mcp_request_ctx（自定义 contextvar，由 ApiKeyAuthMiddleware 设置）读取
2. 降级从 MCP 框架内置的 request_ctx（由 _handle_request 设置）中读取
   POST 请求的 scope，该 scope 已被中间件注入了 mcp_api_key/mcp_user_id/mcp_user_email

SSE 模式下 Tool 执行流程：
  GET /sse → 中间件设置 mcp_request_ctx → connect_sse → server.run()
  POST /messages → 中间件设置 scope["mcp_api_key"] → 消息入队 → 202 返回
  server.run() 内 start_soon → _handle_request 设置 request_ctx(含 POST Request) → 调用 Tool

由于 SSE 中 Tool 实际在 GET 长连接的子任务中执行，mcp_request_ctx 可能
因 contextvar 传播链路复杂而丢失。但 MCP 框架的 request_ctx 在 _handle_request
同一任务中设置，始终可靠——因此作为降级读取源。
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

_logger = logging.getLogger("opscli.mcp.context")

# 当前 MCP 请求的上下文变量（由 ApiKeyAuthMiddleware 设置）
mcp_request_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "mcp_request", default=None
)


def _get_scope_from_mcp_request_ctx() -> dict | None:
    """从 MCP 框架内置的 request_ctx 中获取 POST 请求的 ASGI scope。

    MCP 框架在 _handle_request 中通过 request_ctx.set(RequestContext(..., request=Request))
    将 POST 请求的 Request 对象传递给 Tool handler。该 Request 的 scope 中包含
    中间件注入的 mcp_api_key / mcp_user_id / mcp_user_email。

    Returns:
        POST 请求的 ASGI scope 字典，或 None（非 HTTP 模式或获取失败）
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
        rc = request_ctx.get()
        if rc and hasattr(rc, "request") and rc.request is not None:
            # rc.request 是 starlette.requests.Request，其 scope 包含中间件注入的字段
            return getattr(rc.request, "scope", None)
    except (LookupError, ImportError, AttributeError):
        pass
    return None


def get_current_api_key() -> str | None:
    """获取当前请求中的 API Key（明文）。

    双重读取策略：
    1. 优先从 mcp_request_ctx（自定义 contextvar）读取
    2. 降级从 MCP 框架 request_ctx 中 POST 请求的 scope["mcp_api_key"] 读取

    Returns:
        API Key 字符串，或 None（stdio 模式或无上下文）
    """
    # 优先路径：自定义 contextvar（中间件直接设置）
    ctx = mcp_request_ctx.get()
    if ctx:
        api_key = ctx.get("api_key")
        if api_key:
            return api_key

    # 降级路径：从 MCP 框架 request_ctx 中读取 POST 请求 scope
    scope = _get_scope_from_mcp_request_ctx()
    if scope:
        api_key = scope.get("mcp_api_key")
        if api_key:
            _logger.debug("API Key 从 MCP request_ctx 降级读取成功")
            return api_key

    return None


def get_current_user_id() -> str | None:
    """获取当前请求关联的用户 ID（来自 OPS 后端校验接口）。

    双重读取策略，同 get_current_api_key()。

    Returns:
        用户 ID 字符串，或 None
    """
    ctx = mcp_request_ctx.get()
    if ctx:
        user_id = ctx.get("user_id")
        if user_id:
            return user_id

    scope = _get_scope_from_mcp_request_ctx()
    if scope:
        return scope.get("mcp_user_id")

    return None


def get_current_user_email() -> str | None:
    """获取当前请求关联的用户邮箱（来自 OPS 后端校验接口）。

    双重读取策略，同 get_current_api_key()。

    Returns:
        邮箱字符串，或 None
    """
    ctx = mcp_request_ctx.get()
    if ctx:
        email = ctx.get("email")
        if email:
            return email

    scope = _get_scope_from_mcp_request_ctx()
    if scope:
        return scope.get("mcp_user_email")

    return None


def get_mcp_request_headers() -> dict[str, str]:
    """获取 MCP API Key 透传请求头（HTTP/SSE 模式下有效）。

    在 stdio 模式或无上下文时返回空字典，不干扰 CLI 命令执行。

    Returns:
        {"X-MCP-API-Key": <key>} 或 {}
    """
    try:
        api_key = get_current_api_key()
        if api_key:
            return {"X-MCP-API-Key": api_key}
    except Exception:
        pass
    return {}
