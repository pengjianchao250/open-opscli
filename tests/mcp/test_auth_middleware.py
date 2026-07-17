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
def test_fixed_middleware_injects_auth_mode_into_scope_and_context():
    """fixed 模式必须同时注入 ASGI scope 与 contextvar。"""
    captured = {}

    async def app(scope, receive, send):
        from opscli.mcp.context import get_current_auth_mode

        captured["scope_mode"] = scope.get("mcp_auth_mode")
        captured["context_mode"] = get_current_auth_mode()

    middleware = ApiKeyAuthMiddleware(app, api_key="fixed-key")
    scope = {
        "type": "http",
        "path": "/sse",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer fixed-key")],
    }

    _run(middleware(scope, lambda: None, lambda message: None))

    assert captured == {"scope_mode": "fixed", "context_mode": "fixed"}


def test_remote_middleware_injects_auth_mode_into_scope_and_context(monkeypatch):
    """remote 模式必须把 verified email 与认证模式注入两个上下文通道。"""
    captured = {}

    async def app(scope, receive, send):
        from opscli.mcp.context import get_current_auth_mode, get_current_user_email

        captured["scope_mode"] = scope.get("mcp_auth_mode")
        captured["context_mode"] = get_current_auth_mode()
        captured["email"] = get_current_user_email()

    middleware = ApiKeyAuthMiddleware(
        app,
        auth_verify_url="https://ops.example.com/v1/mcp/verify-key",
    )

    async def verify_remote(api_key):
        assert api_key == "remote-key"
        return {"valid": True, "user_id": "u-1", "email": "remote@example.com"}

    monkeypatch.setattr(middleware, "_verify_remote", verify_remote)
    scope = {
        "type": "http",
        "path": "/sse",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer remote-key")],
    }

    _run(middleware(scope, lambda: None, lambda message: None))

    assert captured == {
        "scope_mode": "remote",
        "context_mode": "remote",
        "email": "remote@example.com",
    }


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
