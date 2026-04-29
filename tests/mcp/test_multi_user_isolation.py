"""MCP 多用户隔离测试。

验证 MCPUserStore 的用户凭证隔离能力：
不同 API Key 对应不同凭证目录，互不干扰。
"""
import asyncio
from pathlib import Path

from opscli.auth import AuthClient
from opscli.mcp.user_store import MCPUserStore


def test_two_api_keys_use_different_credential_directories(tmp_path: Path):
    """验证不同用户拥有独立凭证目录，数据互不干扰。"""
    store = MCPUserStore(base_dir=tmp_path)
    user_a = store.add_user(description="A")
    user_b = store.add_user(description="B")

    # 不同用户应有不同的凭证目录
    dir_a = store.credential_dir(user_a["user_id"])
    dir_b = store.credential_dir(user_b["user_id"])
    assert dir_a != dir_b

    # 在各自目录保存不同 session，数据隔离
    AuthClient(base_dir=dir_a)._store.save_session("session-a", "a@example.com", "2099-01-01T00:00:00+00:00")
    AuthClient(base_dir=dir_b)._store.save_session("session-b", "b@example.com", "2099-01-01T00:00:00+00:00")

    assert AuthClient(base_dir=dir_a)._store.load()["session_id"] == "session-a"
    assert AuthClient(base_dir=dir_b)._store.load()["session_id"] == "session-b"


def test_verify_api_key_returns_correct_user(tmp_path: Path):
    """验证 API Key 校验能正确路由到对应用户。"""
    store = MCPUserStore(base_dir=tmp_path)
    user_a = store.add_user(description="用户A")

    # 校验 API Key 返回正确用户
    result = store.verify_api_key(user_a["api_key"])
    assert result is not None
    assert result.user_id == user_a["user_id"]

    # 错误的 API Key 返回 None
    result = store.verify_api_key("opscli-mcp-invalid-key")
    assert result is None