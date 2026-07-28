"""显式凭证中间件测试。

覆盖三部分：
1. ExplicitCredentials 上下文的读写与按 alias 取 JWT
2. AuthClient 在显式凭证模式下的注入行为（get_token / get_session / is_authenticated）
3. AuthClient.get_me 调用 /api/v1/auth/me
遵循铁律8：base_dir=tmp_path 隔离本地存储，网络请求用 respx mock。
"""
from __future__ import annotations

import httpx
import pytest
import respx

from opscli.auth import AuthClient
from opscli.auth.context import (
    ExplicitCredentials,
    get_explicit_credentials,
    set_explicit_credentials,
)


@pytest.fixture(autouse=True)
def _clear_context():
    """每个用例前后都清空显式凭证上下文，避免污染其他用例。"""
    set_explicit_credentials(None)
    yield
    set_explicit_credentials(None)


# ── ExplicitCredentials 数据结构 ──────────────────────────


def test_jwt_for_maps_alias_to_token():
    """jwt_for 应按别名返回对应系统的 JWT，未知别名返回 None。"""
    creds = ExplicitCredentials(session_id="sid", ops_jwt="ops-jwt", polaris_jwt="pol-jwt")
    assert creds.jwt_for("ops") == "ops-jwt"
    assert creds.jwt_for("polaris") == "pol-jwt"
    assert creds.jwt_for("unknown") is None


def test_context_set_and_get():
    """set/get 应正确读写上下文变量。"""
    assert get_explicit_credentials() is None
    creds = ExplicitCredentials(session_id="sid")
    set_explicit_credentials(creds)
    assert get_explicit_credentials() is creds


# ── AuthClient 注入行为 ──────────────────────────────────


def test_get_token_uses_explicit_jwt_directly(tmp_path):
    """显式提供了对应系统 JWT 时，get_token 直接返回、不读本地存储、不发网络。"""
    set_explicit_credentials(
        ExplicitCredentials(session_id="sid", ops_jwt="explicit-ops", polaris_jwt="explicit-pol")
    )
    client = AuthClient(base_dir=tmp_path)
    assert client.get_token("ops") == "explicit-ops"
    assert client.get_token("polaris") == "explicit-pol"


@respx.mock
def test_get_token_exchanges_via_session_when_jwt_missing(tmp_path):
    """显式模式仅给 session_id、未给该系统 JWT 时，用 session 向后端换取 JWT。"""
    set_explicit_credentials(ExplicitCredentials(session_id="sid-only"))
    client = AuthClient(base_dir=tmp_path)
    # ops 内置系统的 token 端点（system_url + token_endpoint）
    route = respx.post(url__regex=r".*/api/v1/auth/cli-token$").mock(
        return_value=httpx.Response(200, json={"jwt": "session-exchanged-jwt"})
    )
    assert client.get_token("ops") == "session-exchanged-jwt"
    # 请求体应携带 session_id
    assert route.called
    sent = route.calls.last.request
    assert b"sid-only" in sent.content


def test_get_session_prefers_explicit_session(tmp_path):
    """显式模式下 get_session 返回显式 session_id，不读本地存储。"""
    set_explicit_credentials(ExplicitCredentials(session_id="explicit-sid"))
    client = AuthClient(base_dir=tmp_path)
    assert client.get_session("ops") == "explicit-sid"


def test_is_authenticated_true_in_explicit_mode(tmp_path):
    """显式凭证存在即视为已认证，无需本地登录态。"""
    set_explicit_credentials(ExplicitCredentials(session_id="explicit-sid"))
    client = AuthClient(base_dir=tmp_path)
    assert client.is_authenticated() is True


def test_no_explicit_falls_back_to_local(tmp_path):
    """未设置显式凭证时，行为回退到本地存储（未登录则 is_authenticated 为 False）。"""
    client = AuthClient(base_dir=tmp_path)
    assert get_explicit_credentials() is None
    assert client.is_authenticated() is False


# ── auth me ──────────────────────────────────────────────


@respx.mock
def test_get_me_calls_auth_me_endpoint(tmp_path):
    """get_me 应携带 ops 显式 JWT 调 /api/v1/auth/me 并返回响应体。"""
    set_explicit_credentials(ExplicitCredentials(session_id="sid", ops_jwt="ops-jwt"))
    client = AuthClient(base_dir=tmp_path)
    route = respx.get(url__regex=r".*/api/v1/auth/me$").mock(
        return_value=httpx.Response(200, json={"data": {"email": "u@example.com", "name": "U"}})
    )
    result = client.get_me()
    assert route.called
    # 请求头应携带显式 JWT
    assert route.calls.last.request.headers["Authorization"] == "Bearer ops-jwt"
    assert result["data"]["email"] == "u@example.com"


@respx.mock
def test_get_me_with_explicit_session_param(tmp_path):
    """get_me(session_id=, jwt=) 应走 build_request_auth_with_session（MCP 无状态路径）。"""
    # 不设置显式上下文：直接通过参数传入，验证无状态分支
    client = AuthClient(base_dir=tmp_path)
    route = respx.get(url__regex=r".*/api/v1/auth/me$").mock(
        return_value=httpx.Response(200, json={"data": {"email": "sess@example.com"}})
    )
    result = client.get_me(session_id="sid-x", jwt="jw-x")
    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer jw-x"
    # session_id 应作为 polarisUserToken cookie 携带
    assert "sid-x" in req.headers.get("cookie", "")
    assert result["data"]["email"] == "sess@example.com"


@respx.mock
def test_auth_me_cli_outputs_json(tmp_path, monkeypatch):
    """opscli auth me 命令在显式模式下应输出用户信息 JSON。"""
    import json as _json

    from typer.testing import CliRunner

    from opscli.auth.cli import app as auth_app

    # 显式凭证：仅需 ops_jwt + session_id，避免触碰本地 Keychain 与网络换取
    set_explicit_credentials(ExplicitCredentials(session_id="sid", ops_jwt="ops-jwt"))
    respx.get(url__regex=r".*/api/v1/auth/me$").mock(
        return_value=httpx.Response(200, json={"data": {"email": "cli@example.com"}})
    )

    result = CliRunner().invoke(auth_app, ["me"])
    assert result.exit_code == 0, result.output
    assert _json.loads(result.output)["data"]["email"] == "cli@example.com"
