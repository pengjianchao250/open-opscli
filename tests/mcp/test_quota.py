import asyncio
import json
import sqlite3
from datetime import UTC, datetime

import pytest

from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.quota import (
    ENV_QUOTA_CONFIG_PATH,
    QuotaIdentityResolver,
    QuotaLimiter,
    QuotaPolicy,
    SQLiteQuotaStore,
    QuotaUnavailableError,
    load_quota_config,
    _beijing_day_key,
    _seconds_until_next_beijing_day,
)
from opscli.mcp.user_store import MCPUserStore


def _run(coro):
    return asyncio.run(coro)


class MemoryQuotaStore:
    def __init__(self, unavailable=False):
        self.unavailable = unavailable
        self.calls = 0
        self.failures = 0

    async def reserve(self, policy, identity):
        if self.unavailable:
            raise QuotaUnavailableError("sqlite down")
        if self.calls >= policy.daily_limit:
            return False, self._snapshot(policy)
        self.calls += 1
        return True, self._snapshot(policy)

    async def refund_failure(self, policy, identity):
        if self.unavailable:
            raise QuotaUnavailableError("sqlite down")
        self.calls = max(self.calls - 1, 0)
        self.failures += 1
        return self._snapshot(policy)

    def _snapshot(self, policy):
        return {
            "service": policy.service,
            "limit": policy.daily_limit,
            "used": self.calls,
            "remaining": max(policy.daily_limit - self.calls, 0),
            "failures": self.failures,
            "reset_at": "2026-06-16T00:00:00+08:00",
        }


def test_beijing_day_key_uses_beijing_timezone():
    moment = datetime(2026, 6, 15, 16, 30, tzinfo=UTC)

    assert _beijing_day_key(moment) == "20260616"


def test_seconds_until_next_beijing_day_is_positive_and_targets_next_midnight():
    moment = datetime(2026, 6, 15, 15, 59, 30, tzinfo=UTC)

    assert _seconds_until_next_beijing_day(moment) == 30


def test_identity_resolver_prefers_user_id_then_email_then_api_key_hash():
    token = mcp_request_ctx.set({
        "api_key": "raw-api-key",
        "user_id": "user-1",
        "email": "USER@example.com",
    })
    try:
        assert QuotaIdentityResolver().resolve() == "user:user-1"
    finally:
        mcp_request_ctx.reset(token)

    token = mcp_request_ctx.set({"api_key": "raw-api-key", "email": "USER@example.com"})
    try:
        assert QuotaIdentityResolver().resolve() == "email:user@example.com"
    finally:
        mcp_request_ctx.reset(token)

    token = mcp_request_ctx.set({"api_key": "raw-api-key"})
    try:
        identity = QuotaIdentityResolver().resolve()
    finally:
        mcp_request_ctx.reset(token)

    assert identity is not None
    assert identity == f"api_key:{MCPUserStore.hash_api_key('raw-api-key')}"
    assert "raw-api-key" not in identity


def test_limiter_allows_first_five_calls_and_blocks_sixth():
    store = MemoryQuotaStore()
    limiter = QuotaLimiter(
        policies={"seller_sprite_run": QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)},
        store=store,
        identity_resolver=lambda: "user:user-1",
    )

    results = [_run(limiter.before_call("seller_sprite_run")) for _ in range(5)]
    blocked = _run(limiter.before_call("seller_sprite_run"))

    assert [item.allowed for item in results] == [True, True, True, True, True]
    assert blocked.allowed is False
    assert blocked.error_response["error"]["code"] == "MCP_QUOTA_EXCEEDED"
    assert blocked.error_response["quota"]["used"] == 5
    assert blocked.error_response["quota"]["remaining"] == 0


def test_limiter_refunds_failed_call_and_records_failure():
    store = MemoryQuotaStore()
    limiter = QuotaLimiter(
        policies={"seller_sprite_run": QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)},
        store=store,
        identity_resolver=lambda: "user:user-1",
    )

    decision = _run(limiter.before_call("seller_sprite_run"))
    response = _run(limiter.after_call(decision.ticket, {"success": False, "data": None, "error": {"code": "ValueError"}}))

    assert store.calls == 0
    assert store.failures == 1
    assert response["quota"]["used"] == 0
    assert response["quota"]["failures"] == 1


def test_sqlite_quota_store_persists_calls_between_instances(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)

    first_store = SQLiteQuotaStore(db_path)
    for _ in range(5):
        allowed, snapshot = _run(first_store.reserve(policy, "email:user@example.com"))
        assert allowed is True

    second_store = SQLiteQuotaStore(db_path)
    allowed, blocked_snapshot = _run(second_store.reserve(policy, "email:user@example.com"))

    assert snapshot["used"] == 5
    assert allowed is False
    assert blocked_snapshot["used"] == 5
    assert blocked_snapshot["remaining"] == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT service, identity_type, identity_key, calls, failures, limit_count
            FROM mcp_quota_daily
            """
        ).fetchone()

    assert row == ("seller_sprite", "email", "user@example.com", 5, 0, 5)


def test_sqlite_quota_store_refunds_failed_call_and_records_failure(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    store = SQLiteQuotaStore(db_path)

    allowed, _ = _run(store.reserve(policy, "email:user@example.com"))
    snapshot = _run(store.refund_failure(policy, "email:user@example.com"))

    assert allowed is True
    assert snapshot["used"] == 0
    assert snapshot["failures"] == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT calls, failures, identity_key, identity_hash FROM mcp_quota_daily"
        ).fetchone()

    assert row[0] == 0
    assert row[1] == 1
    assert row[2] == "user@example.com"
    assert "user@example.com" not in row[3]


def test_sqlite_quota_store_migrates_existing_table_to_identity_key(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE mcp_quota_daily (
                service TEXT NOT NULL,
                day TEXT NOT NULL,
                identity_hash TEXT NOT NULL,
                identity_type TEXT NOT NULL,
                calls INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                limit_count INTEGER NOT NULL,
                reset_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, day, identity_hash)
            )
            """
        )

    store = SQLiteQuotaStore(db_path)
    allowed, snapshot = _run(store.reserve(policy, "user:user-1"))

    assert allowed is True
    assert snapshot["used"] == 1
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mcp_quota_daily)")}
        row = conn.execute("SELECT identity_type, identity_key FROM mcp_quota_daily").fetchone()

    assert "identity_key" in columns
    assert row == ("user", "user-1")


def test_limiter_returns_unavailable_error_without_calling_service():
    limiter = QuotaLimiter(
        policies={"seller_sprite_run": QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)},
        store=MemoryQuotaStore(unavailable=True),
        identity_resolver=lambda: "user:user-1",
    )

    result = _run(limiter.before_call("seller_sprite_run"))

    assert result.allowed is False
    assert result.error_response["error"]["code"] == "MCP_QUOTA_UNAVAILABLE"


def test_load_quota_config_overrides_default_policy_limit(tmp_path):
    config_path = tmp_path / "mcp-quota.json"
    config_path.write_text(
        json.dumps(
            {
                "policies": {
                    "seller_sprite_run": {
                        "service": "seller_sprite",
                        "daily_limit": 8,
                        "enabled": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_quota_config(config_path)

    assert config.policies["seller_sprite_run"].daily_limit == 8


def test_load_quota_config_can_disable_policy(tmp_path):
    config_path = tmp_path / "mcp-quota.json"
    config_path.write_text(
        json.dumps({"policies": {"seller_sprite_run": {"enabled": False}}}),
        encoding="utf-8",
    )

    config = load_quota_config(config_path)

    assert "seller_sprite_run" not in config.policies


def test_load_quota_config_uses_env_path_before_default_user_config(tmp_path, monkeypatch):
    env_path = tmp_path / "env-quota.json"
    user_config_dir = tmp_path / "home-config"
    env_path.write_text(
        json.dumps({"policies": {"seller_sprite_run": {"daily_limit": 9}}}),
        encoding="utf-8",
    )
    (user_config_dir / "mcp_quota").mkdir(parents=True)
    (user_config_dir / "mcp_quota" / "config.json").write_text(
        json.dumps({"policies": {"seller_sprite_run": {"daily_limit": 3}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_QUOTA_CONFIG_PATH, str(env_path))
    monkeypatch.setattr("opscli.config.CONFIG_DIR", user_config_dir)

    config = load_quota_config()

    assert config.path == env_path
    assert config.policies["seller_sprite_run"].daily_limit == 9


def test_load_quota_config_uses_project_config_before_user_config(tmp_path, monkeypatch):
    project_config = tmp_path / "project" / "configs" / "mcp-quota.json"
    user_config_dir = tmp_path / "home-config"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(
        json.dumps({"policies": {"seller_sprite_run": {"daily_limit": 7}}}),
        encoding="utf-8",
    )
    (user_config_dir / "mcp_quota").mkdir(parents=True)
    (user_config_dir / "mcp_quota" / "config.json").write_text(
        json.dumps({"policies": {"seller_sprite_run": {"daily_limit": 3}}}),
        encoding="utf-8",
    )
    monkeypatch.delenv(ENV_QUOTA_CONFIG_PATH, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("opscli.config.CONFIG_DIR", user_config_dir)
    monkeypatch.setattr("opscli.mcp.quota._project_quota_config_path", lambda: project_config)

    config = load_quota_config()

    assert config.path == project_config
    assert config.policies["seller_sprite_run"].daily_limit == 7


def test_load_quota_config_uses_working_directory_config_for_packaged_deploy(tmp_path, monkeypatch):
    workdir_config = tmp_path / "deploy" / "configs" / "mcp-quota.json"
    user_config_dir = tmp_path / "home-config"
    workdir_config.parent.mkdir(parents=True)
    workdir_config.write_text(
        json.dumps({"policies": {"seller_sprite_run": {"daily_limit": 11}}}),
        encoding="utf-8",
    )
    (user_config_dir / "mcp_quota").mkdir(parents=True)
    (user_config_dir / "mcp_quota" / "config.json").write_text(
        json.dumps({"policies": {"seller_sprite_run": {"daily_limit": 3}}}),
        encoding="utf-8",
    )
    monkeypatch.delenv(ENV_QUOTA_CONFIG_PATH, raising=False)
    monkeypatch.chdir(tmp_path / "deploy")
    monkeypatch.setattr("opscli.config.CONFIG_DIR", user_config_dir)
    monkeypatch.setattr("opscli.mcp.quota._project_quota_config_path", lambda: tmp_path / "missing.json")

    config = load_quota_config()

    assert config.path == workdir_config
    assert config.policies["seller_sprite_run"].daily_limit == 11
