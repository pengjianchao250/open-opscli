"""MCP 鉴权中间件。

无状态模式下服务器不保存用户 OAuth 凭证，但 SSE 连接层通过 API Key 进行
基础访问控制，防止未授权访问。

支持两种工作模式：
1. 固定 API Key 模式（单用户/向后兼容）：直接比对本地存储的 API Key
2. 远程校验模式（多用户）：通过 --auth-verify-url 调用 OPS 后端校验 API Key

鉴权方式：
1. HTTP Header: `Authorization: Bearer <api_key>`
2. URL Query: `?api_key=<api_key>` (兼容部分仅支持 query 的客户端)

注意：由于 FastMCP AuthProvider 的中间件在 Starlette 中注册顺序较早，
无法通过注入 Header 的方式兼容 Query Param。因此统一在自定义中间件中完成
全部鉴权逻辑，不再使用 FastMCP 内置的 AuthProvider。
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any

from opscli.config import __version__

# 直接使用 Starlette 官方类型，消除中间件接口与 Starlette 的类型不兼容问题
from starlette.types import ASGIApp, Receive, Scope, Send

_logger = logging.getLogger("opscli.mcp")

# 客户端断连异常类型集合：SSE 场景下客户端断连属于正常行为，需统一捕获避免日志噪音
try:
    from starlette.requests import ClientDisconnect as _StarletteClientDisconnect
    _CLIENT_DISCONNECT_ERRORS: tuple[type[BaseException], ...] = (_StarletteClientDisconnect,)
except ImportError:
    _CLIENT_DISCONNECT_ERRORS = ()

# 远程 API Key 校验缓存时间：缩短轮询链路耗时，同时保留较快的吊销生效窗口。
_VERIFY_CACHE_TTL_SECONDS = 60

# API Key 校验请求超时：不能接近 ChatGPT 外层 MCP 调用超时，否则工具尚未执行就会失败。
_VERIFY_REQUEST_TIMEOUT_SECONDS = 3


class ApiKeyAuthMiddleware:
    """ASGI 中间件：统一校验 API Key（支持 Header 和 Query Param 两种方式）。

    支持两种工作模式：
    - 固定 API Key 模式：直接比对本地 api_key 参数
    - 远程校验模式：通过 auth_verify_url 调用 OPS 后端校验

    优先检查 Query Param，未找到则检查 Authorization Header。
    校验失败返回 401，不继续向下传递请求。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_key: str | None = None,
        auth_verify_url: str | None = None,
    ):
        """
        Args:
            app: ASGI 应用
            api_key: 固定 API Key（单用户模式，向后兼容）
            auth_verify_url: OPS 后端校验地址（多用户模式），
                             如 https://ops.example.com/v1/mcp/verify-key
        """
        self.app = app
        self._api_key = api_key
        self._auth_verify_url = auth_verify_url
        self._verify_cache: dict[str, tuple[float, dict]] = {}

        if auth_verify_url:
            _logger.info("MCP Server 运行在远程校验模式，校验地址: %s", auth_verify_url)
        elif api_key:
            _logger.info("MCP Server 运行在固定 API Key 模式")
        else:
            _logger.warning("MCP Server 未配置任何 API Key 鉴权！")

    def _extract_token(self, scope: Scope) -> str | None:
        """从 Query Param 或 Header 中提取 API Key。

        支持以下提取顺序：
        1. Query Param: ?api_key=<key>
        2. Authorization Header: Authorization: Bearer <key>
        3. X-MCP-Proxy-Auth Header: X-MCP-Proxy-Auth: Bearer <key>（MCP Inspector 代理使用）
        """
        # 1. 先检查 query param
        query_string = scope.get("query_string", b"").decode("utf-8")
        if query_string:
            params = urllib.parse.parse_qs(query_string)
            api_keys = params.get("api_key", [])
            if api_keys:
                return api_keys[0]

        # 2. 检查 Authorization header
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                auth = value.decode("utf-8", errors="replace")
                if auth.lower().startswith("bearer "):
                    return auth[7:].strip()

        # 3. 检查 X-MCP-Proxy-Auth header（MCP Inspector 通过代理时使用）
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-mcp-proxy-auth":
                auth = value.decode("utf-8", errors="replace")
                if auth.lower().startswith("bearer "):
                    return auth[7:].strip()

        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # SSE 消息投递路径（/messages/）跳过 API Key 鉴权：
        # session_id 由 GET /sse 连接建立时服务端生成并返回，只有已通过鉴权的客户端才持有，
        # 因此 session_id 本身就是认证凭证，不需要额外 API Key。
        path = scope.get("path", "")
        if path.startswith("/messages/"):
            try:
                await self.app(scope, receive, send)
            except _CLIENT_DISCONNECT_ERRORS:
                # SSE 场景下客户端断连是正常行为，静默处理避免日志噪音
                _logger.debug("客户端在 POST /messages/ 时断开连接，已忽略")
            return

        token = self._extract_token(scope)

        # ── 校验逻辑 ────────────────────────────────────────────────
        if self._auth_verify_url:
            # 远程校验模式
            user_info = await self._verify_remote(token)
            if not user_info:
                await self._send_401(scope, send, reason="invalid_api_key")
                return
            # 将用户信息和已验证认证模式注入 scope，供后续 Tool 函数读取。
            scope["mcp_api_key"] = token
            scope["mcp_auth_mode"] = "remote"
            scope["mcp_user_id"] = user_info.get("user_id")
            scope["mcp_user_email"] = user_info.get("email")
            # 工具权限白名单：新后端 verify-key 返回 allowed_tools 字段；
            # 旧后端无此字段时为 None，权限中间件视为全量放行（向后兼容）
            scope["mcp_allowed_tools"] = user_info.get("allowed_tools")
            # 权限管控开关：后端显式返回 False 时全量放行；旧后端无此字段为 None，
            # 维持按 allowed_tools 过滤的原有行为
            scope["mcp_permission_enabled"] = user_info.get("permission_enabled")
        elif self._api_key and token == self._api_key:
            # 固定 API Key 模式（向后兼容）
            scope["mcp_api_key"] = token
            scope["mcp_auth_mode"] = "fixed"
        else:
            await self._send_401(scope, send, reason="invalid_api_key")
            return

        # ── 请求上下文注入（关键：将 API Key 注入 contextvar）────────
        from opscli.mcp.context import mcp_request_ctx

        ctx_token = mcp_request_ctx.set({
            "api_key": token,
            "auth_mode": scope.get("mcp_auth_mode"),
            "user_id": scope.get("mcp_user_id"),
            "email": scope.get("mcp_user_email"),
            # None=固定 Key 模式/旧后端（全量放行）；list=按白名单过滤
            "allowed_tools": scope.get("mcp_allowed_tools"),
            # False=后端关闭权限管控（全量放行）；None=旧后端（按 allowed_tools 过滤）
            "permission_enabled": scope.get("mcp_permission_enabled"),
        })

        # ── SSE 响应追踪（消除 uvicorn 错误日志）──────────────────────
        response_started = False
        response_complete = False

        async def tracking_send(message: Any) -> None:
            nonlocal response_started, response_complete
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body":
                if not message.get("more_body", False):
                    response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except _CLIENT_DISCONNECT_ERRORS:
            # SSE 长连接场景下客户端断连是正常行为，静默处理
            _logger.debug("客户端断开连接: %s", path)
        except RuntimeError as exc:
            if "Expected ASGI message" not in str(exc):
                raise
        finally:
            # 重置 contextvar，避免污染其他请求
            mcp_request_ctx.reset(ctx_token)

            if response_started and not response_complete:
                try:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                except BaseException:
                    pass

    async def _verify_remote(self, api_key: str | None) -> dict | None:
        """调用 OPS 后端远程校验 API Key。

        将 API Key 同时作为 query param 和 header 传参，
        兼容后端不同接入方式。

        Args:
            api_key: 待校验的明文 API Key

        Returns:
            校验通过时返回 OPS 后端响应的 user 信息 dict
            校验失败时返回 None
        """
        if not api_key or not self._auth_verify_url:
            return None
        now = time.time()
        cached = self._verify_cache.get(api_key)
        if cached and cached[0] > now:
            # 同一 API Key 在短时间内会连续轮询，直接复用校验结果降低整体延迟。
            return cached[1]
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self._auth_verify_url,
                    params={"api_key": api_key},
                    headers={"X-MCP-API-Key": api_key, "X-Opscli-Version": __version__},
                    timeout=_VERIFY_REQUEST_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("valid"):
                        self._verify_cache[api_key] = (
                            now + _VERIFY_CACHE_TTL_SECONDS,
                            data,
                        )
                        return data
        except Exception as exc:
            _logger.warning("远程校验 API Key 失败: %s", exc)
        return None

    async def _send_401(self, _scope: Scope, send: Send, reason: str = "invalid_api_key") -> None:
        body = f'{{"error":"Unauthorized","message":"Invalid or missing API Key","reason":"{reason}"}}'
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
            "body": body.encode("utf-8"),
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
