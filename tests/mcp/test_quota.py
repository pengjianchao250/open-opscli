import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest

from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.quota import (
    QuotaIdentityResolver,
    QuotaLimiter,
    QuotaPolicy,
    SQLiteQuotaStore,
    QuotaUnavailableError,
    default_quota_policies,
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

    async def get_policy(self, tool_name):
        if self.unavailable:
            raise QuotaUnavailableError("sqlite down")
        if tool_name != "seller_sprite_run":
            return None
        return QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)

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


def test_identity_resolver_prefers_email_then_api_key_hash():
    token = mcp_request_ctx.set({
        "api_key": "raw-api-key",
        "user_id": "user-1",
        "email": "USER@example.com",
    })
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


def test_identity_resolver_falls_back_to_local_credential_email(monkeypatch):
    token = mcp_request_ctx.set({"api_key": "raw-api-key"})
    monkeypatch.setattr("opscli.mcp.quota._load_local_quota_email", lambda: "local@example.com", raising=False)
    try:
        assert QuotaIdentityResolver().resolve() == "email:local@example.com"
    finally:
        mcp_request_ctx.reset(token)


def test_limiter_allows_first_five_calls_and_blocks_sixth():
    store = MemoryQuotaStore()
    limiter = QuotaLimiter(
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


def test_default_quota_policies_only_limit_public_service_run_entries():
    policies = default_quota_policies()

    assert policies["seller_sprite_run"].service == "seller_sprite"
    assert policies["seller_sprite_listing_analysis_submit"].service == "seller_sprite"
    assert policies["keepa_run"].service == "keepa"
    assert "seller_sprite_start" not in policies
    assert "seller_sprite_listing_analysis_status" not in policies
    assert "seller_sprite_listing_analysis_result" not in policies
    assert "keepa_job_status" not in policies


def test_sqlite_quota_store_initializes_default_policy_table(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)

    policy = _run(store.get_policy("seller_sprite_run"))

    assert policy == QuotaPolicy(
        tool_name="seller_sprite_run",
        service="seller_sprite",
        daily_limit=5,
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT tool_name, service, daily_limit, enabled, timezone
            FROM mcp_quota_policy
            ORDER BY tool_name
            """
        ).fetchall()

    assert rows == [
        ("keepa_run", "keepa", 5, 1, "Asia/Shanghai"),
        ("seller_sprite_listing_analysis_submit", "seller_sprite", 5, 1, "Asia/Shanghai"),
        ("seller_sprite_run", "seller_sprite", 5, 1, "Asia/Shanghai"),
    ]


def test_sqlite_quota_store_does_not_overwrite_existing_policy_table(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE mcp_quota_policy (
                tool_name TEXT NOT NULL PRIMARY KEY,
                service TEXT NOT NULL,
                daily_limit INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO mcp_quota_policy (
                tool_name, service, daily_limit, enabled, timezone, created_at, updated_at
            )
            VALUES ('seller_sprite_run', 'seller_sprite', 100, 1, 'Asia/Shanghai', '2026-07-09T10:00:00+08:00', '2026-07-09T10:00:00+08:00')
            """
        )

    store = SQLiteQuotaStore(db_path)
    policy = _run(store.get_policy("seller_sprite_run"))

    assert policy == QuotaPolicy(
        tool_name="seller_sprite_run",
        service="seller_sprite",
        daily_limit=100,
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_name, daily_limit FROM mcp_quota_policy ORDER BY tool_name"
        ).fetchall()

    assert rows == [("seller_sprite_run", 100)]


def test_limiter_refunds_failed_call_and_records_failure():
    store = MemoryQuotaStore()
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "user:user-1",
    )

    decision = _run(limiter.before_call("seller_sprite_run"))
    response = _run(limiter.after_call(decision.ticket, {"success": False, "data": None, "error": {"code": "ValueError"}}))

    assert store.calls == 0
    assert store.failures == 1
    assert response["quota"]["used"] == 0
    assert response["quota"]["failures"] == 1


def test_limiter_reads_policy_from_sqlite_on_each_call(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )

    first = _run(limiter.before_call("seller_sprite_run"))
    assert first.allowed is True

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_quota_policy
            SET daily_limit = 1, updated_at = '2026-07-09T10:00:00+08:00'
            WHERE tool_name = 'seller_sprite_run'
            """
        )

    second = _run(limiter.before_call("seller_sprite_run"))

    assert second.allowed is False
    assert second.error_response["error"]["code"] == "MCP_QUOTA_EXCEEDED"
    assert second.error_response["quota"]["limit"] == 1
    assert second.error_response["quota"]["used"] == 1


def test_limiter_allows_disabled_policy_without_creating_daily_record(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )
    _run(store.get_policy("seller_sprite_run"))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_quota_policy
            SET enabled = 0, updated_at = '2026-07-09T10:00:00+08:00'
            WHERE tool_name = 'seller_sprite_run'
            """
        )

    decision = _run(limiter.before_call("seller_sprite_run"))

    assert decision.allowed is True
    assert decision.ticket is None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM mcp_quota_daily").fetchone()
    assert row[0] == 0


def test_limiter_allows_deleted_policy_without_creating_daily_record(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )
    _run(store.get_policy("seller_sprite_run"))
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM mcp_quota_policy WHERE tool_name = 'seller_sprite_run'")

    decision = _run(limiter.before_call("seller_sprite_run"))

    assert decision.allowed is True
    assert decision.ticket is None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM mcp_quota_daily").fetchone()
    assert row[0] == 0


def test_limiter_blocks_invalid_sqlite_policy_without_calling_service(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )
    _run(store.get_policy("seller_sprite_run"))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_quota_policy
            SET daily_limit = 0, updated_at = '2026-07-09T10:00:00+08:00'
            WHERE tool_name = 'seller_sprite_run'
            """
        )

    decision = _run(limiter.before_call("seller_sprite_run"))

    assert decision.allowed is False
    assert decision.error_response["error"]["code"] == "MCP_QUOTA_UNAVAILABLE"
    assert decision.error_response["quota"]["service"] == "seller_sprite_run"


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


def test_sqlite_quota_store_applies_bonus_daily_limit(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    store = SQLiteQuotaStore(db_path)

    _run(store.upsert_bonus_daily_limit("seller_sprite", "User@example.com", 3))

    for _ in range(8):
        allowed, snapshot = _run(store.reserve(policy, "email:user@example.com"))
        assert allowed is True

    blocked, blocked_snapshot = _run(store.reserve(policy, "email:user@example.com"))

    assert snapshot["limit"] == 8
    assert blocked is False
    assert blocked_snapshot["used"] == 8
    assert blocked_snapshot["remaining"] == 0

    with sqlite3.connect(db_path) as conn:
        bonus_row = conn.execute(
            "SELECT service, email, bonus_daily_limit FROM mcp_quota_bonus_daily"
        ).fetchone()
        daily_row = conn.execute(
            "SELECT identity_key, calls, limit_count FROM mcp_quota_daily"
        ).fetchone()

    assert bonus_row == ("seller_sprite", "user@example.com", 3)
    assert daily_row == ("user@example.com", 8, 8)


def test_sqlite_quota_store_snapshot_reads_current_usage_without_consuming(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    store = SQLiteQuotaStore(db_path)

    allowed, _ = _run(store.reserve(policy, "email:user@example.com"))
    snapshot = _run(store.snapshot(policy, "email:user@example.com"))

    assert allowed is True
    assert snapshot["limit"] == 5
    assert snapshot["used"] == 1
    assert snapshot["remaining"] == 4

    allowed_again, second_snapshot = _run(store.reserve(policy, "email:user@example.com"))

    assert allowed_again is True
    assert second_snapshot["used"] == 2


def test_sqlite_quota_store_snapshot_applies_bonus_daily_limit(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    store = SQLiteQuotaStore(db_path)

    _run(store.upsert_bonus_daily_limit("seller_sprite", "User@example.com", 3))
    snapshot = _run(store.snapshot(policy, "email:user@example.com"))

    assert snapshot["limit"] == 8
    assert snapshot["used"] == 0
    assert snapshot["remaining"] == 8


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
    class UnavailablePolicyStore:
        async def get_policy(self, tool_name):
            raise QuotaUnavailableError("sqlite down")

        async def reserve(self, policy, identity):
            raise AssertionError("reserve must not be called when policy loading fails")

        async def refund_failure(self, policy, identity):
            raise AssertionError("refund must not be called when policy loading fails")

        async def snapshot(self, policy, identity):
            raise AssertionError("snapshot must not be called when policy loading fails")

    limiter = QuotaLimiter(
        store=UnavailablePolicyStore(),
        identity_resolver=lambda: "user:user-1",
    )

    result = _run(limiter.before_call("seller_sprite_run"))

    assert result.allowed is False
    assert result.error_response["error"]["code"] == "MCP_QUOTA_UNAVAILABLE"


def test_quota_module_no_longer_exposes_json_config_loader():
    import opscli.mcp.quota as quota_module

    removed_names = [
        "ENV_QUOTA" + "_CONFIG_PATH",
        "Quota" + "Config",
        "load_quota" + "_config",
        "_find_quota" + "_config_path",
    ]
    for name in removed_names:
        assert not hasattr(quota_module, name)
