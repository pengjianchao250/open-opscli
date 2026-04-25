"""MCP 鉴权中间件。

无状态模式下服务器不保存用户 OAuth 凭证，但 SSE 连接层通过固定 API Key 进行
基础访问控制，防止未授权访问。

支持两种鉴权方式：
1. HTTP Header: `Authorization: Bearer <api_key>`
2. URL Query: `?api_key=<api_key>` (兼容部分仅支持 query 的客户端)

注意：由于 FastMCP AuthProvider 的中间件在 Starlette 中注册顺序较早，
无法通过注入 Header 的方式兼容 Query Param。因此统一在自定义中间件中完成
全部鉴权逻辑，不再使用 FastMCP 内置的 AuthProvider。
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Awaitable, Callable

# ASGI type aliases
Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class ApiKeyAuthMiddleware:
    """ASGI 中间件：统一校验 API Key（支持 Header 和 Query Param 两种方式）。

    优先检查 Query Param，未找到则检查 Authorization Header。
    校验失败返回 401，不继续向下传递请求。
    """

    def __init__(self, app: ASGIApp, api_key: str):
        self.app = app
        self._api_key = api_key

    def _extract_token(self, scope: Scope) -> str | None:
        """从 Query Param 或 Header 中提取 API Key。"""
        # 1. 先检查 query param
        query_string = scope.get("query_string", b"").decode("utf-8")
        if query_string:
            params = urllib.parse.parse_qs(query_string)
            api_keys = params.get("api_key", [])
            if api_keys:
                return api_keys[0]

        # 2. 再检查 Authorization header
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                auth = value.decode("utf-8", errors="replace")
                if auth.lower().startswith("bearer "):
                    return auth[7:].strip()
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = self._extract_token(scope)
        if token != self._api_key:
            try:
                await self._send_401(scope, send)
            except RuntimeError:
                # 服务关闭期间连接已断开，忽略发送 401 时的 ASGI 状态错误
                pass
            return

        # 追踪响应状态：SSE 是长连接流式响应，关闭时 fastmcp 内部会吞掉
        # CancelledError 后正常返回，但不会发送终止帧，导致 uvicorn 记录
        # "ASGI callable returned without completing response" 错误。
        # 通过包装 send 追踪状态，在 finally 中补发终止帧来消除该错误。
        response_started = False
        response_complete = False

        async def tracking_send(message: dict) -> None:
            nonlocal response_started, response_complete
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body":
                # more_body 缺省为 False 表示响应已结束
                if not message.get("more_body", False):
                    response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except RuntimeError as exc:
            # SSE 长连接在关闭时序中，starlette 错误处理器会尝试在已开始的
            # 流式响应上再次发送 http.response.start，uvicorn 状态机会拒绝并
            # 抛出此错误。这是正常关闭时序问题，不需要向上传播。
            if "Expected ASGI message" not in str(exc):
                raise
        finally:
            # fastmcp 吞掉 CancelledError 后正常返回时，SSE 流没有发终止帧。
            # 补发一个空的终止帧，让 uvicorn 状态机认为响应已正常完成，
            # 从而消除 "ASGI callable returned without completing response" 日志。
            if response_started and not response_complete:
                try:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                except BaseException:
                    # 连接已断开或事件循环正在关闭时，补发可能失败，忽略即可
                    pass

    async def _send_401(self, scope: Scope, send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="opscli-mcp"'),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"error":"Unauthorized","message":"Invalid or missing API Key"}',
        })


# 保留旧类名用于向后兼容（但实际不再使用 FastMCP AuthProvider）
class FixedApiKeyAuthProvider:
    """固定 API Key 鉴权提供者（已弃用，保留仅用于兼容旧导入）。

    所有连接 MCP 服务器的用户共享同一个 API Key，仅用于 SSE 连接层的基础
    访问控制，不涉及用户身份隔离。实际业务鉴权由调用方传入的 session_id/jwt
    在后端完成。
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def verify_token(self, token: str) -> Any:
        """校验 Bearer Token 是否与固定 API Key 匹配。"""
        if token != self._api_key:
            return None
        # 返回一个与 AccessToken 兼容的简单对象
        return type("AccessToken", (), {
            "token": token,
            "client_id": "default",
            "scopes": ["opscli:mcp"],
        })()
