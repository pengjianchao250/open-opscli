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


def test_force_relogin_renews_session_even_when_locally_unexpired(monkeypatch, tmp_path):
    """force_relogin 必须无视 is_authenticated()，强制换一张新 Session。

    回归防护：is_authenticated() 只比对本地 session_expires_at，而服务端还会校验
    is_valid 与真实有效期。被登出/吊销的 Session 本地依然显示未过期，自动登录因此
    永远不触发，调用方恒拿 401（生产会话 5384 即此形态）。
    """
    from opscli.mcp import ops_credentials

    state = {"session": "stale-session", "logins": 0}

    class FakeCache:
        def is_authenticated(self):
            return True  # 本地看着没过期，但服务端已判无效

        def get_session_id(self):
            return state["session"]

        def get_jwt(self, system):
            return "fresh-jwt"

        def get_email(self):
            return "user@example.com"

    async def fake_login():
        state["logins"] += 1
        state["session"] = "fresh-session"
        return {"success": True}

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials, "_get_isolated_credential_cache", lambda credential_dir: FakeCache()
    )
    monkeypatch.setattr(
        ops_credentials, "_get_authenticated_user_email", lambda: "user@example.com"
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", fake_login)

    binding = asyncio.run(ops_credentials.ensure_ops_credentials(force_relogin=True))

    assert state["logins"] == 1
    assert binding.session_id == "fresh-session"


def test_force_relogin_skips_when_another_request_already_renewed(monkeypatch, tmp_path):
    """并发下别的请求已经换过新 Session 时不再重复登录。

    single-flight 的二次检查在 force 路径下必须以「session_id 是否换了新的」为判据：
    只看 is_authenticated() 会把并发前那张被服务端拒掉的旧 Session 当成有效。
    """
    from opscli.mcp import ops_credentials

    state = {"logins": 0}

    class FakeCache:
        def is_authenticated(self):
            return True

        def get_session_id(self):
            # 取锁前后返回不同值，模拟并发请求已完成重登
            state.setdefault("reads", 0)
            state["reads"] += 1
            return "stale-session" if state["reads"] == 1 else "renewed-by-peer"

        def get_jwt(self, system):
            return "peer-jwt"

        def get_email(self):
            return "user@example.com"

    async def fake_login():
        state["logins"] += 1
        return {"success": True}

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials, "_get_isolated_credential_cache", lambda credential_dir: FakeCache()
    )
    monkeypatch.setattr(
        ops_credentials, "_get_authenticated_user_email", lambda: "user@example.com"
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", fake_login)

    binding = asyncio.run(ops_credentials.ensure_ops_credentials(force_relogin=True))

    assert state["logins"] == 0
    assert binding.session_id == "renewed-by-peer"


def test_default_path_still_skips_login_for_valid_session(monkeypatch, tmp_path):
    """不传 force_relogin 时行为不变：本地有效即复用，不触发登录。"""
    from opscli.mcp import ops_credentials

    class FakeCache:
        def is_authenticated(self):
            return True

        def get_session_id(self):
            return "isolated-session"

        def get_jwt(self, system):
            return "isolated-jwt"

        def get_email(self):
            return "user@example.com"

    async def unexpected_login():
        raise AssertionError("默认路径不应重登")

    monkeypatch.setattr(ops_credentials, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(ops_credentials, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ops_credentials, "_get_isolated_credential_cache", lambda credential_dir: FakeCache()
    )
    monkeypatch.setattr(
        ops_credentials, "_get_authenticated_user_email", lambda: "user@example.com"
    )
    monkeypatch.setattr(ops_credentials, "auth_mcp_login", unexpected_login)

    binding = asyncio.run(ops_credentials.ensure_ops_credentials())

    assert binding.session_id == "isolated-session"
