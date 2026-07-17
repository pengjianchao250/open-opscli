"""MCP context.py 测试。

覆盖新版 context.py 中基于 contextvars 的上下文管理函数，
包括新增的 get_mcp_request_headers()。
"""
import pytest

from opscli.config import __version__
from opscli.mcp.context import (
    get_current_api_key,
    get_current_auth_mode,
    get_current_user_email,
    get_current_user_id,
    get_mcp_request_headers,
    mcp_request_ctx,
)


def test_initial_state_all_none():
    """初始状态：无上下文时所有读取函数返回 None/空。"""
    assert get_current_api_key() is None
    assert get_current_auth_mode() is None
    assert get_current_user_id() is None
    assert get_current_user_email() is None
    assert get_mcp_request_headers() == {"X-Opscli-Version": __version__}


def test_context_read_write():
    """模拟中间件设置上下文后，各函数正确读取。"""
    token = mcp_request_ctx.set({
        "api_key": "mcp_test_key_123",
        "auth_mode": "remote",
        "user_id": "101",
        "email": "test@example.com",
    })

    try:
        assert get_current_api_key() == "mcp_test_key_123"
        assert get_current_auth_mode() == "remote"
        assert get_current_user_id() == "101"
        assert get_current_user_email() == "test@example.com"
        assert get_mcp_request_headers() == {
            "X-MCP-API-Key": "mcp_test_key_123",
            "X-Opscli-Version": __version__,
        }
    finally:
        mcp_request_ctx.reset(token)


def test_context_reset():
    """重置上下文后恢复初始状态。"""
    token = mcp_request_ctx.set({
        "api_key": "mcp_test_key_123",
        "user_id": "101",
    })
    mcp_request_ctx.reset(token)

    assert get_current_api_key() is None
    assert get_current_auth_mode() is None
    assert get_current_user_id() is None
    assert get_mcp_request_headers() == {"X-Opscli-Version": __version__}


def test_get_mcp_request_headers_without_api_key():
    """上下文存在但不含 api_key 时返回空字典。"""
    token = mcp_request_ctx.set({
        "user_id": "101",
        "email": "test@example.com",
    })
    try:
        assert get_mcp_request_headers() == {"X-Opscli-Version": __version__}
    finally:
        mcp_request_ctx.reset(token)


def test_email_and_auth_mode_fall_back_to_asgi_scope(monkeypatch):
    """contextvar 缺值时应从 MCP request scope 读取 transport 身份。"""
    monkeypatch.setattr(
        "opscli.mcp.context._get_scope_from_mcp_request_ctx",
        lambda: {
            "mcp_user_email": "scope@example.com",
            "mcp_auth_mode": "fixed",
        },
    )

    assert get_current_user_email() == "scope@example.com"
    assert get_current_auth_mode() == "fixed"


def test_context_isolation_between_tasks():
    """contextvars 天然隔离：两个不同上下文互不影响。"""
    token_a = mcp_request_ctx.set({
        "api_key": "key_a",
        "user_id": "1",
    })

    try:
        assert get_current_api_key() == "key_a"

        # 嵌套设置新上下文（模拟并发请求）
        token_b = mcp_request_ctx.set({
            "api_key": "key_b",
            "user_id": "2",
        })
        try:
            assert get_current_api_key() == "key_b"
        finally:
            mcp_request_ctx.reset(token_b)

        # 恢复后应回到 A 的上下文
        assert get_current_api_key() == "key_a"
    finally:
        mcp_request_ctx.reset(token_a)
