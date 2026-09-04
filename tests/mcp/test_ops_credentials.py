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


def test_remote_binding_repairs_stale_session_when_jwt_fetch_is_rejected(
    monkeypatch,
    tmp_path,
):
    from opscli.auth.domain.exceptions import TokenFetchError
    from opscli.mcp import ops_credentials

    state = {
        "session_id": "stale-session",
        "jwt": None,
        "email": "user@example.com",
    }
    fetched_sessions = []
    invalidations = 0
    login_calls = 0

    class FakeCache:
        def is_authenticated(self):
            return bool(state["session_id"])

        def get_session_id(self):
            return state["session_id"]

        def get_jwt(self, system):
            assert system == "ops"
            return state["jwt"]

        def get_email(self):
            return state["email"]

    async def fake_fetch(session_id, credential_dir):
        assert credential_dir == tmp_path
        fetched_sessions.append(session_id)
        if session_id == "stale-session":
            raise TokenFetchError("获取 ops JWT 失败: 401", status_code=401)
        state["jwt"] = "fresh-jwt"
        return "fresh-jwt"

    def fake_invalidate(credential_dir):
        nonlocal invalidations
        assert credential_dir == tmp_path
        invalidations += 1
        state.update(session_id=None, jwt=None, email=None)

    async def fake_login():
        nonlocal login_calls
        login_calls += 1
        state.update(
            session_id="fresh-session",
            jwt=None,
            email="user@example.com",
        )
        return {"success": True, "data": {"saved_locally": True}, "error": None}

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
    monkeypatch.setattr(ops_credentials, "_fetch_and_store_ops_jwt", fake_fetch)
    monkeypatch.setattr(ops_credentials, "_invalidate_ops_credentials", fake_invalidate)
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", fake_login)

    binding = asyncio.run(ops_credentials.ensure_ops_credentials(require_jwt=True))

    assert binding.session_id == "fresh-session"
    assert binding.jwt == "fresh-jwt"
    assert binding.refreshed is True
    assert fetched_sessions == ["stale-session", "fresh-session"]
    assert invalidations == 1
    assert login_calls == 1


def test_remote_binding_repairs_concurrent_stale_requests_with_one_login(
    monkeypatch,
    tmp_path,
):
    from opscli.auth.domain.exceptions import TokenFetchError
    from opscli.mcp import ops_credentials

    state = {
        "session_id": "stale-session",
        "jwt": None,
        "email": "user@example.com",
    }
    login_calls = 0

    class FakeCache:
        def is_authenticated(self):
            return bool(state["session_id"])

        def get_session_id(self):
            return state["session_id"]

        def get_jwt(self, system):
            assert system == "ops"
            return state["jwt"]

        def get_email(self):
            return state["email"]

    async def fake_fetch(session_id, credential_dir):
        await asyncio.sleep(0)
        if session_id == "stale-session":
            raise TokenFetchError("获取 ops JWT 失败: 401", status_code=401)
        state["jwt"] = "fresh-jwt"
        return "fresh-jwt"

    def fake_invalidate(credential_dir):
        state.update(session_id=None, jwt=None, email=None)

    async def fake_login():
        nonlocal login_calls
        login_calls += 1
        await asyncio.sleep(0)
        state.update(
            session_id="fresh-session",
            jwt=None,
            email="user@example.com",
        )
        return {"success": True, "data": {"saved_locally": True}, "error": None}

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
    monkeypatch.setattr(ops_credentials, "_fetch_and_store_ops_jwt", fake_fetch)
    monkeypatch.setattr(ops_credentials, "_invalidate_ops_credentials", fake_invalidate)
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", fake_login)

    async def scenario():
        return await asyncio.gather(
            ops_credentials.ensure_ops_credentials(require_jwt=True),
            ops_credentials.ensure_ops_credentials(require_jwt=True),
        )

    first, second = asyncio.run(scenario())

    assert login_calls == 1
    assert first.jwt == "fresh-jwt"
    assert second.jwt == "fresh-jwt"
    assert {first.refreshed, second.refreshed} == {False, True}


def test_remote_binding_does_not_relogin_for_non_auth_jwt_failure(
    monkeypatch,
    tmp_path,
):
    import pytest

    from opscli.auth.domain.exceptions import TokenFetchError
    from opscli.mcp import ops_credentials

    class FakeCache:
        def is_authenticated(self):
            return True

        def get_session_id(self):
            return "current-session"

        def get_jwt(self, system):
            assert system == "ops"
            return None

        def get_email(self):
            return "user@example.com"

    async def failed_fetch(session_id, credential_dir):
        raise TokenFetchError("获取 ops JWT 失败: 503", status_code=503)

    async def unexpected_login():
        raise AssertionError("非认证错误不得触发重新登录")

    def unexpected_invalidation(credential_dir):
        raise AssertionError("非认证错误不得清除有效 Session")

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
    monkeypatch.setattr(ops_credentials, "_fetch_and_store_ops_jwt", failed_fetch)
    monkeypatch.setattr(
        ops_credentials,
        "_invalidate_ops_credentials",
        unexpected_invalidation,
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", unexpected_login)

    with pytest.raises(
        ops_credentials.OpsCredentialBindingError,
        match="503",
    ):
        asyncio.run(ops_credentials.ensure_ops_credentials(require_jwt=True))


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
