"""MySQL 额度存储与默认后端选择的回归测试。"""

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


@pytest.mark.parametrize("backend", [None, "mysql"])
@pytest.mark.parametrize("settings_prefix", ["OPSCLI_RUNTIME", "OPSCLI_COLLECTION"])
def test_default_quota_store_selects_mysql(monkeypatch, tmp_path, backend, settings_prefix):
    """未指定后端时使用 MySQL，复用专用配置或采集连接配置。"""
    if backend is None:
        monkeypatch.delenv("OPSCLI_MCP_QUOTA_BACKEND", raising=False)
    else:
        monkeypatch.setenv("OPSCLI_MCP_QUOTA_BACKEND", backend)
    for name in ("HOST", "DATABASE", "USER", "PASSWORD"):
        monkeypatch.delenv(f"OPSCLI_RUNTIME_MYSQL_{name}", raising=False)
        monkeypatch.delenv(f"OPSCLI_COLLECTION_MYSQL_{name}", raising=False)
    # 遗留 SQLite 路径不能让未指定后端的进程继续读取本地额度。
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_SQLITE_PATH", str(tmp_path / "quota.sqlite3"))
    monkeypatch.setenv(f"{settings_prefix}_MYSQL_HOST", "mysql.internal")
    monkeypatch.setenv(f"{settings_prefix}_MYSQL_DATABASE", "ops")
    monkeypatch.setenv(f"{settings_prefix}_MYSQL_USER", "quota_writer")
    monkeypatch.setenv(f"{settings_prefix}_MYSQL_PASSWORD", "secret")

    store = quota_module._default_quota_store()

    assert isinstance(store, MySqlQuotaStore)
    assert store.settings.host == "mysql.internal"
    assert store.settings.database == "ops"
    assert store.settings.user == "quota_writer"
    assert not (tmp_path / "quota.sqlite3").exists()


def test_default_mysql_quota_blocks_when_settings_are_missing(monkeypatch, tmp_path):
    """默认 MySQL 配置缺失时阻断调用，不回退到 SQLite 放行。"""
    monkeypatch.delenv("OPSCLI_MCP_QUOTA_BACKEND", raising=False)
    for prefix in ("OPSCLI_RUNTIME", "OPSCLI_COLLECTION"):
        for name in ("HOST", "DATABASE", "USER", "PASSWORD"):
            monkeypatch.delenv(f"{prefix}_MYSQL_{name}", raising=False)
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_SQLITE_PATH", str(tmp_path / "quota.sqlite3"))
    limiter = quota_module.QuotaLimiter(
        store=quota_module._default_quota_store(),
        identity_resolver=lambda: "email:user@example.com",
        quota_enabled=lambda: True,
    )

    decision = asyncio.run(limiter.before_call("ext_xydc_openapi_call"))

    assert decision.allowed is False
    assert decision.error_response["error"]["code"] == "MCP_QUOTA_UNAVAILABLE"
    assert not (tmp_path / "quota.sqlite3").exists()


def test_mysql_quota_policy_changes_are_read_without_restarting():
    """同一存储实例每次读取策略，SQL 修改额度不需要重启。"""
    connections = [
        FakeConnection([
            {
                "tool_name": "ext_xydc_openapi_call",
                "service": "xiyou",
                "daily_limit": limit,
                "enabled": 1,
                "timezone": "Asia/Shanghai",
            }
        ])
        for limit in (10, 100)
    ]
    store = _store(connections[0])
    store._connect_factory = iter(connections).__next__

    first = asyncio.run(store.get_policy("ext_xydc_openapi_call"))
    second = asyncio.run(store.get_policy("ext_xydc_openapi_call"))

    assert first.daily_limit == 10
    assert second.daily_limit == 100
    assert all(connection.closed for connection in connections)


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


def test_default_quota_store_supports_explicit_sqlite(tmp_path, monkeypatch):
    """显式选择 SQLite 时继续使用指定的兼容数据库。"""
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_BACKEND", "sqlite")
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_SQLITE_PATH", str(tmp_path / "quota.sqlite3"))

    assert isinstance(quota_module._default_quota_store(), quota_module.SQLiteQuotaStore)


def test_default_quota_store_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_BACKEND", "unknown")

    with pytest.raises(ValueError, match="OPSCLI_MCP_QUOTA_BACKEND"):
        quota_module._default_quota_store()
