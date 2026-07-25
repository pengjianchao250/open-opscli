"""asin_data MCP 工具显式 polaris_jwt 单测。

验证 _build_auth_client 生成的 _ProvidedAuthClient 按 alias 选对应系统的显式 JWT：
- alias=="ops"     → 用 jwt
- alias=="polaris" → 用 polaris_jwt（不再强制 session 换取）
遵循铁律8：不触发真实网络（直接传显式 JWT 时不发请求）。
"""
from __future__ import annotations

from opscli.mcp.tools.asin_data import _build_auth_client


def test_provided_auth_client_routes_jwt_per_alias():
    """显式提供 ops+polaris 两个 JWT 时，build_request_auth 按 alias 各自返回。"""
    client = _build_auth_client(session_id="sid", jwt="ops-jwt", polaris_jwt="pol-jwt")

    ops_headers, ops_cookies = client.build_request_auth("ops")
    assert ops_headers["Authorization"] == "Bearer ops-jwt"
    assert ops_cookies.get("polarisUserToken") == "sid"

    pol_headers, pol_cookies = client.build_request_auth("polaris")
    assert pol_headers["Authorization"] == "Bearer pol-jwt"
    assert pol_cookies.get("polarisUserToken") == "sid"


def test_build_auth_client_returns_base_when_nothing_provided():
    """三者都不传时返回原生 AuthClient（不进入 _ProvidedAuthClient 分支）。"""
    from opscli.auth import AuthClient

    client = _build_auth_client()
    assert isinstance(client, AuthClient)
