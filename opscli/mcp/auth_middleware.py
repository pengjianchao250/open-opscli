"""MCP 鉴权中间件。

无状态模式下服务器不保存用户 OAuth 凭证，但 SSE 连接层通过固定 API Key 进行
基础访问控制，防止未授权访问。
"""

from __future__ import annotations

from fastmcp.server.auth.auth import AccessToken, AuthProvider


class FixedApiKeyAuthProvider(AuthProvider):
    """固定 API Key 鉴权提供者。

    所有连接 MCP 服务器的用户共享同一个 API Key，仅用于 SSE 连接层的基础
    访问控制，不涉及用户身份隔离。实际业务鉴权由调用方传入的 session_id/jwt
    在后端完成。
    """

    def __init__(self, api_key: str):
        super().__init__(required_scopes=["opscli:mcp"])
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        """校验 Bearer Token 是否与固定 API Key 匹配。"""
        if token != self._api_key:
            return None
        return AccessToken(
            token=token,
            client_id="default",
            scopes=["opscli:mcp"],
        )
