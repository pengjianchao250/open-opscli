import asyncio

import pytest

from opscli.mcp import quota as quota_module
from opscli.mcp.quota import QuotaPolicy, QuotaUnavailableError
from opscli.mcp.quota_mysql import MySqlQuotaStore
from opscli.shared.collection_storage.config import MySqlSettings


class FakeCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchone(self):
        return self.responses.pop(0) if self.responses else None


class FakeConnection:
    def __init__(self, responses):
        self.cursor_instance = FakeCursor(responses)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _store(connection):
    return MySqlQuotaStore(
        settings=MySqlSettings(
            host="mysql.internal",
            database="ops",
            user="quota_writer",
            password="secret",
        ),
        connect_factory=lambda: connection,
    )


def test_mysql_quota_reserve_locks_and_updates_daily_record():
    connection = FakeConnection([None, {"calls": 0, "failures": 0}])
    store = _store(connection)

    allowed, snapshot = asyncio.run(
        store.reserve(
            QuotaPolicy("seller_sprite_run", "seller_sprite", 5),
            "email:user@example.com",
        )
    )

    sql = "\n".join(statement for statement, _ in connection.cursor_instance.executions)
    assert allowed is True
    assert snapshot["used"] == 1
    assert snapshot["remaining"] == 4
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "FOR UPDATE" in sql
    assert "UPDATE mcp_quota_daily" in sql
    assert connection.committed is True
    assert connection.closed is True


def test_mysql_quota_reserve_rejects_at_limit_without_increment():
    connection = FakeConnection([None, {"calls": 5, "failures": 2}])
    store = _store(connection)

    allowed, snapshot = asyncio.run(
        store.reserve(
            QuotaPolicy("seller_sprite_run", "seller_sprite", 5),
            "email:user@example.com",
        )
    )

    update_statements = [
        sql
        for sql, _ in connection.cursor_instance.executions
        if "UPDATE mcp_quota_daily\n" in sql
    ]
    assert allowed is False
    assert snapshot["used"] == 5
    assert snapshot["remaining"] == 0
    assert update_statements == []
    assert connection.committed is True


def test_mysql_quota_refund_failure_decrements_and_records_failure():
    connection = FakeConnection([None, {"calls": 2, "failures": 1}])
    store = _store(connection)

    snapshot = asyncio.run(
        store.refund_failure(
            QuotaPolicy("seller_sprite_run", "seller_sprite", 5),
            "email:user@example.com",
        )
    )

    update_params = next(
        params
        for sql, params in connection.cursor_instance.executions
        if "UPDATE mcp_quota_daily\n" in sql
    )
    assert snapshot["used"] == 1
    assert snapshot["failures"] == 2
    assert update_params[1:3] == (1, 2)


def test_mysql_quota_schema_version_is_required():
    connection = FakeConnection([{"schema_version": 2}])
    store = _store(connection)

    with pytest.raises(QuotaUnavailableError, match="version mismatch"):
        store.check_schema()


def test_mysql_quota_reads_enabled_policy():
    connection = FakeConnection(
        [
            {
                "tool_name": "keepa_run",
                "service": "keepa",
                "daily_limit": 200,
                "enabled": 1,
                "timezone": "Asia/Shanghai",
            }
        ]
    )
    store = _store(connection)

    policy = asyncio.run(store.get_policy("keepa_run"))

    assert policy == QuotaPolicy("keepa_run", "keepa", 200)


def test_default_quota_store_selects_mysql_only_when_explicit(monkeypatch):
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_BACKEND", "mysql")
    monkeypatch.setenv("OPSCLI_RUNTIME_MYSQL_HOST", "mysql.internal")
    monkeypatch.setenv("OPSCLI_RUNTIME_MYSQL_DATABASE", "ops")
    monkeypatch.setenv("OPSCLI_RUNTIME_MYSQL_USER", "quota_writer")
    monkeypatch.setenv("OPSCLI_RUNTIME_MYSQL_PASSWORD", "secret")

    store = quota_module._default_quota_store()

    assert isinstance(store, MySqlQuotaStore)


@pytest.mark.parametrize("dedicated", [False, True])
def test_default_access_resolver_keeps_sqlite_account_bindings(
    tmp_path, monkeypatch, dedicated
):
    from opscli.seller_sprite.services import account_bindings

    monkeypatch.setattr(
        account_bindings, "DEFAULT_BINDING_DB_PATH", tmp_path / "bindings.sqlite3"
    )
    binding = None
    if dedicated:
        binding = account_bindings.SellerSpriteAccountBindingStore().bind(
            user_email="user@example.com",
            account_name="test-account",
            username="test-login",
            password="test-password",
        )

    access = quota_module._resolve_service_access(
        "seller_sprite_run", "email:user@example.com"
    )

    assert access.user_email == "user@example.com"
    assert access.mode == ("unlimited" if dedicated else "metered")
    if dedicated:
        assert access.account_id == binding.account.account_id
        assert access.account_key == binding.account_key


def test_default_quota_store_preserves_sqlite_default(tmp_path, monkeypatch):
    monkeypatch.delenv("OPSCLI_MCP_QUOTA_BACKEND", raising=False)
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_SQLITE_PATH", str(tmp_path / "quota.sqlite3"))

    assert isinstance(quota_module._default_quota_store(), quota_module.SQLiteQuotaStore)


def test_default_quota_store_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_BACKEND", "unknown")

    with pytest.raises(ValueError, match="OPSCLI_MCP_QUOTA_BACKEND"):
        quota_module._default_quota_store()
