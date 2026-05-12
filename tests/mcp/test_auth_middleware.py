"""MCP 鉴权中间件测试。"""

import asyncio

import httpx
import respx

from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware


def _run(coro):
    return asyncio.run(coro)


async def _empty_app(scope, receive, send):
    """占位 ASGI 应用，测试仅直接覆盖中间件内部校验逻辑。"""
    return None


@respx.mock
def test_remote_verify_uses_short_cache():
    """同一 API Key 的连续校验应命中短缓存，避免轮询时重复访问 OPS。"""
    middleware = ApiKeyAuthMiddleware(
        _empty_app,
        auth_verify_url="https://ops.example.com/v1/mcp/verify-key",
    )
    route = respx.get("https://ops.example.com/v1/mcp/verify-key").mock(
        return_value=httpx.Response(
            200,
            json={"valid": True, "user_id": "u-1", "email": "user@example.com"},
        )
    )

    first = _run(middleware._verify_remote("mcp_key_1"))
    second = _run(middleware._verify_remote("mcp_key_1"))

    assert first == second
    assert first["user_id"] == "u-1"
    assert route.calls.call_count == 1
