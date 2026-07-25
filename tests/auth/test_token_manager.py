import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from opscli.auth import AuthClient
from opscli.auth.core.token_manager import TokenManager
from opscli.auth.exceptions import NotAuthenticatedError
from opscli.config import __version__

BUILTINS = [
    {"alias": "ops", "system_key": "ops", "url": "https://ops.example.com",
     "token_endpoint": "/v1/auth/cli-token", "source": "builtin"},
]


@pytest.fixture
def store(tmp_path):
    from opscli.auth.storage.credential_store import CredentialStore
    s = CredentialStore(base_dir=tmp_path)
    s.save_session("uuid-1234", "user@example.com", "2099-01-01T00:00:00+00:00", "dc-abc")
    return s


@pytest.fixture
def reg(tmp_path):
    from opscli.auth.core.system_registry import SystemRegistry
    return SystemRegistry(base_dir=tmp_path, builtin_systems=BUILTINS)


def test_get_token_calls_fetch_when_missing(store, reg):
    tm = TokenManager(store=store, registry=reg)
    with patch.object(tm, "_fetch_token", return_value="new-jwt") as m:
        assert tm.get_token("ops") == "new-jwt"
    m.assert_called_once()


def test_get_token_returns_cached_valid(store, reg):
    store.save_token("ops", "cached-jwt", expires_in=3600)
    tm = TokenManager(store=store, registry=reg)
    with patch.object(tm, "_fetch_token") as m:
        assert tm.get_token("ops") == "cached-jwt"
    m.assert_not_called()


def test_get_token_refreshes_near_expiry(store, reg):
    store.save_token("ops", "old-jwt", expires_in=60)
    tm = TokenManager(store=store, registry=reg)
    with patch.object(tm, "_fetch_token", return_value="new-jwt"):
        assert tm.get_token("ops") == "new-jwt"


def test_get_token_refetches_after_session_switch(store, reg):
    store.save_token("ops", "cached-jwt", expires_in=3600)
    store.save_session("uuid-5678", "other@example.com", "2099-01-02T00:00:00+00:00", "dc-def")

    tm = TokenManager(store=store, registry=reg)
    with patch.object(tm, "_fetch_token", return_value="new-jwt") as m:
        assert tm.get_token("ops") == "new-jwt"

    m.assert_called_once()


def test_not_authenticated_raises(tmp_path, reg):
    from opscli.auth.storage.credential_store import CredentialStore
    tm = TokenManager(store=CredentialStore(base_dir=tmp_path), registry=reg)
    with pytest.raises(NotAuthenticatedError):
        tm.get_token("ops")


def test_check_token_valid(store, reg):
    store.save_token("ops", "jwt", expires_in=3600)
    result = TokenManager(store=store, registry=reg).check_token("ops")
    assert result["valid"] is True and result["expires_in"] > 0


def test_get_session_id_returns_saved_session(store, reg):
    tm = TokenManager(store=store, registry=reg)

    assert tm.get_session_id() == "uuid-1234"


def test_auth_client_get_session_returns_saved_session(tmp_path):
    client = AuthClient(base_dir=tmp_path)
    client._store.save_session("uuid-1234", "user@example.com", "2099-01-01T00:00:00+00:00", "dc-abc")

    assert client.get_session("ops") == "uuid-1234"


def test_auth_client_build_request_auth_includes_device_code_cookie(tmp_path):
    client = AuthClient(base_dir=tmp_path)
    client._store.save_session("uuid-1234", "user@example.com", "2099-01-01T00:00:00+00:00", "dc-abc")
    client._store.save_token("ops", "jwt-token", expires_in=3600)

    headers, cookies = client.build_request_auth("ops")

    assert headers["Authorization"] == "Bearer jwt-token"
    assert cookies["polarisUserToken"] == "uuid-1234"
    assert cookies["opscliDeviceCode"] == "dc-abc"


def test_auth_client_build_session_headers_returns_x_session_id(tmp_path):
    client = AuthClient(base_dir=tmp_path)
    client._store.save_session("uuid-1234", "user@example.com", "2099-01-01T00:00:00+00:00", "dc-abc")

    headers = client.build_session_headers("ops")

    assert headers == {"X-Session-Id": "uuid-1234", "X-Opscli-Version": __version__}


def test_auth_client_get_session_raises_when_not_authenticated(tmp_path):
    client = AuthClient(base_dir=tmp_path)

    with pytest.raises(NotAuthenticatedError):
        client.get_session("ops")


def test_auth_client_get_session_uses_public_token_manager_api(tmp_path):
    client = AuthClient(base_dir=tmp_path)

    with patch.object(client._tm, "get_session_id", return_value="uuid-public") as mocked:
        assert client.get_session("ops") == "uuid-public"

    mocked.assert_called_once()


def test_fetch_token_joins_base_url_and_endpoint_without_double_slash(store, reg, monkeypatch):
    """系统 URL 带尾斜杠时，请求地址不应出现双斜杠路径。"""
    import httpx

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"jwt": "jwt-normal", "expires_in": 7200}, request=req)

    monkeypatch.setattr("opscli.auth.core.token_manager.httpx.post", fake_post)
    tm = TokenManager(store=store, registry=reg)

    assert tm._fetch_token("polaris", "https://biapi.qa.aukeyit.com/", "/api/auth/cli-token") == "jwt-normal"
    assert captured["url"] == "https://biapi.qa.aukeyit.com/api/auth/cli-token"


def test_fetch_token_forwards_mcp_api_key_when_context_present(store, reg, monkeypatch):
    """MCP 上下文存在时，_fetch_token 应透传 X-MCP-API-Key。"""
    from opscli.mcp.context import mcp_request_ctx
    import httpx

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"jwt": "jwt-from-mcp", "expires_in": 7200}, request=req)

    monkeypatch.setattr("opscli.auth.core.token_manager.httpx.post", fake_post)
    tm = TokenManager(store=store, registry=reg)

    token = mcp_request_ctx.set({"api_key": "mcp_key_token"})
    try:
        result = tm._fetch_token("ops", "https://ops.example.com", "/v1/auth/cli-token")
        assert result == "jwt-from-mcp"
        assert captured["headers"] is not None
        assert captured["headers"]["X-MCP-API-Key"] == "mcp_key_token"
    finally:
        mcp_request_ctx.reset(token)


def test_fetch_token_no_mcp_header_when_context_absent(store, reg, monkeypatch):
    """无 MCP 上下文时，_fetch_token 不应附加 X-MCP-API-Key。"""
    import httpx

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"jwt": "jwt-normal", "expires_in": 7200}, request=req)

    monkeypatch.setattr("opscli.auth.core.token_manager.httpx.post", fake_post)
    tm = TokenManager(store=store, registry=reg)

    result = tm._fetch_token("ops", "https://ops.example.com", "/v1/auth/cli-token")
    assert result == "jwt-normal"
    # headers or None 会传入 None
    assert captured["headers"] is None or "X-MCP-API-Key" not in captured["headers"]


def test_get_token_by_session_forwards_mcp_api_key(store, reg, monkeypatch):
    """get_token_by_session 应透传 X-MCP-API-Key。"""
    from opscli.mcp.context import mcp_request_ctx
    import httpx

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"jwt": "jwt-by-session", "expires_in": 7200}, request=req)

    monkeypatch.setattr("opscli.auth.core.token_manager.httpx.post", fake_post)
    tm = TokenManager(store=store, registry=reg)

    token = mcp_request_ctx.set({"api_key": "mcp_key_session"})
    try:
        result = tm.get_token_by_session("session-abc", "ops")
        assert result == "jwt-by-session"
        assert captured["headers"]["X-MCP-API-Key"] == "mcp_key_session"
    finally:
        mcp_request_ctx.reset(token)
