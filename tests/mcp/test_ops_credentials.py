"""MCP OPS 凭证绑定模块测试。"""

import asyncio


def test_remote_binding_ignores_legacy_explicit_auth_and_reuses_isolated_credentials(
    monkeypatch,
    tmp_path,
):
    from opscli.mcp import ops_credentials

    class FakeCache:
        def is_authenticated(self):
            return True

        def get_session_id(self):
            return "isolated-session"

        def get_jwt(self, system):
            assert system == "ops"
            return "isolated-jwt"

        def get_email(self):
            return "user@example.com"

    async def unexpected_login():
        raise AssertionError("有效隔离凭证不应重复登录")

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials,
        "_get_isolated_credential_cache",
        lambda credential_dir: FakeCache(),
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_authenticated_user_email",
        lambda: "user@example.com",
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", unexpected_login)

    binding = asyncio.run(
        ops_credentials.ensure_ops_credentials(
            provided_session="legacy-session",
            provided_jwt="legacy-jwt",
        )
    )

    assert binding.credential_scope == str(tmp_path)
    assert binding.user_email == "user@example.com"
    assert binding.session_id == "isolated-session"
    assert binding.jwt == "isolated-jwt"
    assert binding.runtime_auth is None


def test_remote_binding_auto_logs_in_once_for_concurrent_requests(monkeypatch, tmp_path):
    from opscli.mcp import ops_credentials

    class FakeCache:
        authenticated = False

        def is_authenticated(self):
            return self.authenticated

        def get_session_id(self):
            return "auto-session" if self.authenticated else None

        def get_jwt(self, system):
            assert system == "ops"
            return "auto-jwt" if self.authenticated else None

        def get_email(self):
            return "user@example.com" if self.authenticated else None

    cache = FakeCache()
    login_calls = 0

    async def fake_login():
        nonlocal login_calls
        login_calls += 1
        await asyncio.sleep(0)
        cache.authenticated = True
        return {"success": True, "data": {"saved_locally": True}, "error": None}

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials,
        "_get_isolated_credential_cache",
        lambda credential_dir: cache,
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_authenticated_user_email",
        lambda: "user@example.com",
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", fake_login)

    async def scenario():
        return await asyncio.gather(
            ops_credentials.ensure_ops_credentials(),
            ops_credentials.ensure_ops_credentials(),
        )

    first, second = asyncio.run(scenario())

    assert login_calls == 1
    assert first.session_id == "auto-session"
    assert second.session_id == "auto-session"


def test_remote_binding_rejects_authenticated_user_mismatch(monkeypatch, tmp_path):
    import pytest

    from opscli.mcp import ops_credentials

    class FakeCache:
        def is_authenticated(self):
            return True

        def get_session_id(self):
            return "other-user-session"

        def get_jwt(self, system):
            return "other-user-jwt"

        def get_email(self):
            return "other-user@example.com"

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials,
        "_get_isolated_credential_cache",
        lambda credential_dir: FakeCache(),
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_authenticated_user_email",
        lambda: "request-user@example.com",
    )

    with pytest.raises(
        ops_credentials.OpsCredentialBindingError,
        match="OPS 隔离凭证用户不一致",
    ):
        asyncio.run(ops_credentials.ensure_ops_credentials())


def test_remote_binding_surfaces_auto_login_failure(monkeypatch, tmp_path):
    import pytest

    from opscli.mcp import ops_credentials

    class FakeCache:
        def is_authenticated(self):
            return False

    async def failed_login():
        return {
            "success": False,
            "data": None,
            "error": {"code": "AUTH_FAILED", "message": "API Key 用户不存在"},
        }

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials,
        "_get_isolated_credential_cache",
        lambda credential_dir: FakeCache(),
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", failed_login)

    with pytest.raises(
        ops_credentials.OpsCredentialBindingError,
        match="API Key 用户不存在",
    ):
        asyncio.run(ops_credentials.ensure_ops_credentials())


def test_stdio_binding_preserves_explicit_runtime_credentials(monkeypatch):
    from opscli.mcp import ops_credentials

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: None)
    monkeypatch.setattr(
        ops_credentials,
        "_get_auth_pair",
        lambda system, session_id, jwt: (session_id, jwt),
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_authenticated_user_email",
        lambda: "local-user@example.com",
    )

    binding = asyncio.run(
        ops_credentials.ensure_ops_credentials(
            provided_session="local-session",
            provided_jwt="local-jwt",
        )
    )

    assert binding.credential_scope == "default"
    assert binding.user_email == "local-user@example.com"
    assert binding.session_id == "local-session"
    assert binding.jwt == "local-jwt"
    assert binding.runtime_auth == ("local-session", "local-jwt")
