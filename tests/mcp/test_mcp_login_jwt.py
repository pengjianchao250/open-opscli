"""MCP 一步登录顺带签发 JWT 的客户端落盘测试。

背景：MCP 模式的认证是两段式——`/v1/mcp/auth/login` 只产出 session，客户端随后还要打一次
`/v1/auth/cli-token` 才能拿到业务请求用的 Bearer JWT。后端 2026-09-05 起在登录响应里顺带
签发一张，客户端把它落进隔离凭证目录即可省掉登录后第一次调用的那一跳。

本文件钉住三件事：票要落盘、**明文票绝不能回给 AI Agent**、旧后端（无该字段）不受影响。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from opscli.auth.storage.credential_store import CredentialStore
from opscli.mcp.tools import auth as auth_tools


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _login(monkeypatch, tmp_path, payload: dict) -> dict:
    """跑一次 auth_mcp_login，后端响应用 payload 顶掉，凭证落到 tmp_path。"""
    store = CredentialStore(base_dir=tmp_path)

    monkeypatch.setattr(auth_tools, "_get_mcp_request_headers", lambda: {"X-MCP-API-Key": "k"})
    monkeypatch.setattr(auth_tools, "_get_isolated_store", lambda: store)
    monkeypatch.setattr(auth_tools, "_get_credential_dir", lambda: tmp_path)

    class _FakeFlow:
        def __init__(self, **kwargs) -> None:
            pass

        def request_device_code(self) -> dict:
            return {"device_code": "dc-1", "user_code": "UC-1"}

    monkeypatch.setattr("opscli.auth.core.device_flow.DeviceFlow", _FakeFlow)
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResponse(payload))

    with patch("opscli.query.services.metadata_cache.invalidate_metadata_cache"), patch(
        "opscli.mcp.permissions.invalidate_stdio_cache"
    ):
        return asyncio.run(auth_tools.auth_mcp_login())


_BASE_PAYLOAD = {
    "status": "authorized",
    "session_id": "sess-new",
    "email": "u@example.com",
    "expires_at": "2099-01-01T00:00:00+00:00",
    "agent_name": "Claude Code",
}


def test_issued_jwt_is_persisted_to_isolated_store(monkeypatch, tmp_path):
    """后端顺带签发的票要落进隔离凭证目录，后续调用才能免掉换票那一跳。"""
    payload = {**_BASE_PAYLOAD, "jwt": "jwt-from-login", "expires_in": 86400}

    result = _login(monkeypatch, tmp_path, payload)

    assert result["success"] is True
    assert result["data"]["jwt_saved"] is True
    saved = CredentialStore(base_dir=tmp_path).load()
    assert saved["tokens"]["ops"]["jwt"] == "jwt-from-login"


def test_plaintext_jwt_never_returned_to_agent(monkeypatch, tmp_path):
    """【勿删】响应里不得出现 jwt 明文。

    auth_mcp_login 的返回会原样回给 AI Agent，进入模型上下文并落进 dm_message_events。
    明文凭证一旦走这条路就等于公开了——票只能落本地，对外只留布尔标记。
    """
    payload = {**_BASE_PAYLOAD, "jwt": "jwt-from-login", "expires_in": 86400}

    result = _login(monkeypatch, tmp_path, payload)

    assert "jwt" not in result["data"]
    assert "expires_in" not in result["data"]
    assert "jwt-from-login" not in str(result)


def test_old_backend_without_jwt_field_still_works(monkeypatch, tmp_path):
    """旧后端不返回 jwt 字段时行为完全不变，不写票、不加标记。"""
    result = _login(monkeypatch, tmp_path, dict(_BASE_PAYLOAD))

    assert result["data"]["saved_locally"] is True
    assert "jwt_saved" not in result["data"]
    assert not (CredentialStore(base_dir=tmp_path).load() or {}).get("tokens")


@pytest.mark.parametrize(
    "extra",
    [
        {"jwt": "", "expires_in": 86400},
        {"jwt": "jwt-x", "expires_in": 0},
        {"jwt": "jwt-x"},
        {"expires_in": 86400},
    ],
    ids=["空票", "零有效期", "缺有效期", "缺票"],
)
def test_incomplete_jwt_payload_is_ignored(monkeypatch, tmp_path, extra):
    """票或有效期不完整时不写：宁可多换一次票，也不存一张说不清有效期的票。"""
    result = _login(monkeypatch, tmp_path, {**_BASE_PAYLOAD, **extra})

    assert "jwt_saved" not in result["data"]
    assert not (CredentialStore(base_dir=tmp_path).load() or {}).get("tokens")


def test_session_switch_does_not_wipe_the_new_token(monkeypatch, tmp_path):
    """先存 session 再存票的顺序不能颠倒。

    save_session 在 session 变化时会清空旧 JWT（防串号）；若先存票再存 session，
    刚拿到的票会被一起清掉，等于白签一张。
    """
    store = CredentialStore(base_dir=tmp_path)
    store.save_session("sess-old", "old@example.com", "2099-01-01T00:00:00+00:00")
    store.save_token("ops", "jwt-old", 86400)

    payload = {**_BASE_PAYLOAD, "jwt": "jwt-new", "expires_in": 86400}
    _login(monkeypatch, tmp_path, payload)

    saved = CredentialStore(base_dir=tmp_path).load()
    assert saved["session_id"] == "sess-new"
    assert saved["tokens"]["ops"]["jwt"] == "jwt-new"
