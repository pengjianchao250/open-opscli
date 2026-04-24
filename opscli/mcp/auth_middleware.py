"""MCP 多用户鉴权中间件。

FastMCP 的 stdio transport 没有 HTTP Bearer 概念，因此本中间件主要用于
SSE / HTTP 请求；stdio 场景由 `OPSCLI_MCP_API_KEY` 环境变量在 Tool 执行时兜底。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp.server.auth.auth import AccessToken, AuthProvider
from fastmcp.server.middleware import Middleware, MiddlewareContext

from opscli.mcp.context import get_credential_dir, is_multi_user_enabled
from opscli.mcp.user_store import MCPUserStore


class MCPApiKeyAuthProvider(AuthProvider):
    """将 opscli MCP API Key 作为 HTTP Bearer Token 校验。"""

    def __init__(self, *, base_dir: Path | None = None):
        super().__init__(required_scopes=["opscli:mcp"])
        self._base_dir = base_dir

    async def verify_token(self, token: str) -> AccessToken | None:
        """校验 Bearer Token，失败时返回 None 触发 HTTP 401。"""
        user = MCPUserStore(base_dir=self._base_dir).verify_api_key(token)
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id=user.user_id,
            scopes=["opscli:mcp"],
            claims={"credential_dir": str(user.credential_dir)},
        )


class MCPAuthMiddleware(Middleware):
    """在 Tool 调用前解析并缓存当前用户凭证目录。"""

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next):
        """Tool 调用前进行多用户鉴权预处理。"""
        if is_multi_user_enabled() and context.fastmcp_context is not None:
            # 这里不直接处理 401 响应，错误会交由 FastMCP 统一转换；
            # Tool 内部也会再次读取 state，保证测试和 stdio 场景一致。
            await get_credential_dir(context.fastmcp_context)
        return await call_next(context)
