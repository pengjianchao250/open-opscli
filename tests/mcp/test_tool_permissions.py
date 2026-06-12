"""MCP 工具权限中间件测试。

覆盖三种运行模式的权限解析与中间件过滤/拦截行为：
- HTTP/SSE 远程校验模式（contextvar 含 allowed_tools）
- HTTP/SSE 固定 Key 模式 / 旧后端（allowed_tools 为 None → 全量放行）
- stdio 模式（本地 session 查询后端 + 404/401/网络异常三种兜底）
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
import respx

from opscli.mcp import permissions
from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.permissions import (
    BASE_AUTH_TOOLS,
    ToolPermissionMiddleware,
    _resolve_allowed_tools,
    invalidate_stdio_cache,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_stdio_cache():
    """每个测试前后清空 stdio 权限缓存，避免用例间相互污染。"""
    invalidate_stdio_cache()
    yield
    invalidate_stdio_cache()


def _set_http_ctx(allowed_tools):
    """模拟 HTTP/SSE 模式下 ApiKeyAuthMiddleware 注入的请求上下文。"""
    mcp_request_ctx.set({
        "api_key": "mcp_test_key",
        "user_id": 1,
        "email": "user@example.com",
        "allowed_tools": allowed_tools,
    })


# ── HTTP/SSE 模式 ──────────────────────────────────────────────────


def test_http_mode_with_allowed_tools_filters():
    """远程校验模式：白名单之外的工具被过滤，且自动并入基础 auth 工具。"""
    _set_http_ctx(["query_simple"])

    allowed = _run(_resolve_allowed_tools())

    assert "query_simple" in allowed
    assert "keepa_run" not in allowed
    # 基础 auth 工具始终可用
    assert BASE_AUTH_TOOLS <= allowed


def test_http_mode_without_allowed_tools_allows_all():
    """固定 Key 模式 / 旧后端：allowed_tools 为 None 时全量放行。"""
    _set_http_ctx(None)

    assert _run(_resolve_allowed_tools()) is None


def test_http_mode_empty_allowed_tools_keeps_base_auth():
    """后端返回空白名单时仍保留基础 auth 工具（保证可登录）。"""
    _set_http_ctx([])

    assert _run(_resolve_allowed_tools()) == BASE_AUTH_TOOLS


# ── 中间件过滤与拦截 ────────────────────────────────────────────────


def test_middleware_filters_list_tools():
    """on_list_tools 只保留白名单内的工具。"""
    _set_http_ctx(["query_simple"])
    middleware = ToolPermissionMiddleware()

    tools = [
        SimpleNamespace(name="query_simple"),
        SimpleNamespace(name="keepa_run"),
        SimpleNamespace(name="auth_login_start"),
    ]

    async def call_next(_context):
        return tools

    result = _run(middleware.on_list_tools(None, call_next))

    assert [t.name for t in result] == ["query_simple", "auth_login_start"]


def test_middleware_blocks_unauthorized_call():
    """on_call_tool 拦截白名单之外的工具调用。"""
    from fastmcp.exceptions import ToolError

    _set_http_ctx(["query_simple"])
    middleware = ToolPermissionMiddleware()
    context = SimpleNamespace(message=SimpleNamespace(name="keepa_run"))

    async def call_next(_context):
        return "should-not-reach"

    with pytest.raises(ToolError, match="无权限"):
        _run(middleware.on_call_tool(context, call_next))


def test_middleware_passes_authorized_call():
    """on_call_tool 放行白名单内的工具调用。"""
    _set_http_ctx(["query_simple"])
    middleware = ToolPermissionMiddleware()
    context = SimpleNamespace(message=SimpleNamespace(name="query_simple"))

    async def call_next(_context):
        return "ok"

    assert _run(middleware.on_call_tool(context, call_next)) == "ok"


def test_middleware_allows_all_in_fixed_key_mode():
    """固定 Key 模式：列表不过滤、调用不拦截。"""
    _set_http_ctx(None)
    middleware = ToolPermissionMiddleware()

    tools = [SimpleNamespace(name="keepa_run")]

    async def list_next(_context):
        return tools

    async def call_next(_context):
        return "ok"

    assert _run(middleware.on_list_tools(None, list_next)) == tools
    context = SimpleNamespace(message=SimpleNamespace(name="keepa_run"))
    assert _run(middleware.on_call_tool(context, call_next)) == "ok"


# ── stdio 模式 ─────────────────────────────────────────────────────


@pytest.fixture
def stdio_env(monkeypatch):
    """stdio 模式环境：无 HTTP 上下文 + 固定 session_id + 固定 ops 地址。"""
    mcp_request_ctx.set(None)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_session_id", lambda: "session-test-1"
    )
    monkeypatch.setattr(
        "opscli.auth.config.get_ops_url", lambda: "https://ops.example.com/api"
    )


@respx.mock
def test_stdio_mode_fetches_allowed_tools(stdio_env):
    """stdio 模式：成功响应解析白名单并缓存（第二次不再请求网络）。"""
    route = respx.get("https://ops.example.com/api/v1/mcp/allowed-tools").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "allowed_tools": ["query_simple"]},
        )
    )

    first = _run(_resolve_allowed_tools())
    second = _run(_resolve_allowed_tools())

    assert "query_simple" in first
    assert BASE_AUTH_TOOLS <= first
    assert first == second
    assert route.calls.call_count == 1


@respx.mock
def test_stdio_mode_404_allows_all(stdio_env):
    """stdio 模式：旧后端未部署端点（404）→ 全量放行。"""
    respx.get("https://ops.example.com/api/v1/mcp/allowed-tools").mock(
        return_value=httpx.Response(404)
    )

    assert _run(_resolve_allowed_tools()) is None


@respx.mock
def test_stdio_mode_401_falls_back_to_base(stdio_env):
    """stdio 模式：session 失效（401）→ 仅基础 auth 工具。"""
    respx.get("https://ops.example.com/api/v1/mcp/allowed-tools").mock(
        return_value=httpx.Response(401, json={"success": False})
    )

    assert _run(_resolve_allowed_tools()) == BASE_AUTH_TOOLS


@respx.mock
def test_stdio_mode_network_error_without_cache(stdio_env):
    """stdio 模式：网络异常且从未成功 → fail-closed 仅基础 auth 工具。"""
    respx.get("https://ops.example.com/api/v1/mcp/allowed-tools").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    assert _run(_resolve_allowed_tools()) == BASE_AUTH_TOOLS


@respx.mock
def test_stdio_mode_network_error_uses_stale_cache(stdio_env, monkeypatch):
    """stdio 模式：网络异常但有过期旧缓存 → 沿用旧值（stale-while-error）。"""
    route = respx.get("https://ops.example.com/api/v1/mcp/allowed-tools")
    route.mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "allowed_tools": ["query_simple"]},
        )
    )
    first = _run(_resolve_allowed_tools())
    assert "query_simple" in first

    # 让缓存过期，并模拟网络故障
    expired = (0.0, permissions._stdio_cache[1])
    monkeypatch.setattr(permissions, "_stdio_cache", expired)
    route.mock(side_effect=httpx.ConnectError("connection refused"))

    assert _run(_resolve_allowed_tools()) == first


def test_stdio_mode_without_login_returns_base(monkeypatch):
    """stdio 模式：本地无登录态 → 仅基础 auth 工具（不发起网络请求）。"""
    mcp_request_ctx.set(None)
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_session_id", lambda: None)

    assert _run(_resolve_allowed_tools()) == BASE_AUTH_TOOLS


def test_invalidate_stdio_cache(stdio_env):
    """登录/登出后清空缓存，下次解析重新拉取。"""
    with respx.mock:
        route = respx.get("https://ops.example.com/api/v1/mcp/allowed-tools").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "allowed_tools": ["query_simple"]},
            )
        )
        _run(_resolve_allowed_tools())
        invalidate_stdio_cache()
        _run(_resolve_allowed_tools())
        assert route.calls.call_count == 2


# ── 服务器注册 ─────────────────────────────────────────────────────


def test_middleware_registered_on_server():
    """MCP Server 启动配置中已注册权限中间件。"""
    from opscli.mcp.server import mcp

    assert any(
        isinstance(m, ToolPermissionMiddleware) for m in mcp.middleware
    )
