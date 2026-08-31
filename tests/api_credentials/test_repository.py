"""API 凭据 MySQL 仓储与多账号选择测试。"""

from datetime import datetime

import pytest

from opscli.api_credentials.config import ApiCredentialMySqlSettings
from opscli.api_credentials.models import ACCOUNT_STATUSES
from opscli.api_credentials.repository import (
    ApiCredentialSchemaError,
    MySqlApiCredentialRepository,
)
from opscli.api_credentials.schema import SCHEMA_STATEMENTS


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.lastrowid = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.executions.append((" ".join(sql.split()), params))
        return 1

    def fetchone(self):
        if isinstance(self.connection.fetchone_value, list):
            return self.connection.fetchone_value.pop(0)
        return self.connection.fetchone_value

    def fetchall(self):
        return self.connection.fetchall_value


class FakeConnection:
    def __init__(self, *, fetchone=None, fetchall=None):
        self.fetchone_value = fetchone
        self.fetchall_value = fetchall or []
        self.executions = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _row(account_id, name, secret, priority):
    return {
        "account_id": account_id,
        "provider": "serpapi",
        "account_name": name,
        "status": "active",
        "priority": priority,
        "remark": None,
        "secret_value": secret,
        "secret_masked": f"{secret[:4]}****{secret[-4:]}",
        "secret_version": 1,
        "remaining_quota": 100,
        "current_usage": 2,
        "quota_reset_at": None,
        "last_selected_at": None,
        "last_used_at": None,
        "last_verified_at": datetime(2026, 8, 11, 10, 0),
        "cooldown_until": None,
        "consecutive_failures": 0,
        "last_error_code": None,
        "last_error_message": None,
        "provider_metadata": '{"plan_name":"Developer"}',
    }


def _repository(factory):
    return MySqlApiCredentialRepository(
        settings=ApiCredentialMySqlSettings(
            host="mysql.internal",
            database="ops",
            user="runtime",
            password="secret",
        ),
        connect_factory=factory,
    )


def test_schema_models_provider_accounts_credentials_runtime_and_audit():
    sql = "\n".join(SCHEMA_STATEMENTS)

    assert "api_provider_accounts" in sql
    assert "api_account_credentials" in sql
    assert "api_account_runtime" in sql
    assert "api_credential_audit_logs" in sql
    assert "UNIQUE KEY uq_api_provider_account (provider, account_name)" in sql
    assert "secret_value TEXT NOT NULL" in sql
    assert "secret_ciphertext" not in sql


def test_list_accounts_reads_multiple_plaintext_accounts_but_public_output_is_masked():
    connection = FakeConnection(
        fetchall=[
            _row(1, "primary", "primary-secret-key", 10),
            _row(2, "backup", "backup-secret-key", 20),
        ]
    )
    repository = _repository(lambda: connection)

    accounts = repository.list_accounts("serpapi")

    assert [account.name for account in accounts] == ["primary", "backup"]
    assert accounts[0].api_key == "primary-secret-key"
    assert accounts[1].api_key == "backup-secret-key"
    assert "primary-secret-key" not in str(accounts[0].to_public_dict())
    assert accounts[0].provider_metadata == {"plan_name": "Developer"}


def test_rotate_key_writes_plaintext_and_derived_metadata():
    connection = FakeConnection(fetchone=None)
    repository = _repository(lambda: connection)

    with connection.cursor() as cursor:
        rotated = repository._rotate_key(
            cursor,
            account_id=7,
            api_key="plaintext-api-key",
        )

    assert rotated is True
    insert = next(
        (sql, params)
        for sql, params in connection.executions
        if sql.startswith("INSERT INTO api_account_credentials")
    )
    assert "secret_value" in insert[0]
    assert insert[1][1] == "plaintext-api-key"
    assert insert[1][2] == "plai****-key"
    assert insert[1][3] != "plaintext-api-key"


def test_acquire_uses_locked_priority_lru_selection_and_marks_selected():
    row = _row(2, "backup", "backup-secret-key", 20)
    select_connection = FakeConnection(fetchone=row)
    reread_connection = FakeConnection(fetchone=row)
    connections = iter([select_connection, reread_connection])
    repository = _repository(lambda: next(connections))

    selected = repository.acquire("serpapi", exclude_account_ids={1})

    assert selected is not None
    assert selected.account_id == 2
    selection_sql = select_connection.executions[0][0]
    assert "ORDER BY a.priority" in selection_sql
    assert "FOR UPDATE SKIP LOCKED" in selection_sql
    assert "a.id NOT IN (%s)" in selection_sql
    assert select_connection.executions[0][1] == ("serpapi", 1)
    assert any(
        sql.startswith("UPDATE api_account_runtime SET last_selected_at")
        for sql, _params in select_connection.executions
    )
    assert select_connection.committed is True


def test_repository_accepts_logical_deleted_status_and_audits_change():
    """逻辑删除只更新账号状态并写审计，不执行物理 DELETE。"""
    connection = FakeConnection()
    repository = _repository(lambda: connection)

    repository.set_status(8, "deleted", actor="admin@example.com")

    assert "deleted" in ACCOUNT_STATUSES
    assert connection.executions[0][0].startswith("UPDATE api_provider_accounts SET status")
    assert connection.executions[0][1] == ("deleted", 8)
    assert connection.executions[1][0].startswith("INSERT INTO api_credential_audit_logs")
    assert connection.executions[1][1][1] == "account_deleted"
    assert connection.committed is True


def test_create_schema_migrates_empty_v1_table_to_plaintext_v2():
    connection = FakeConnection(
        fetchone=[
            {"schema_version": 1},
            {"credential_count": 0},
            {"schema_version": 2},
        ]
    )
    repository = _repository(lambda: connection)

    repository.create_schema()

    sql = "\n".join(statement for statement, _params in connection.executions)
    assert "ALTER TABLE api_account_credentials" in sql
    assert "ADD COLUMN secret_value TEXT NOT NULL" in sql
    assert "DROP COLUMN secret_ciphertext" in sql
    assert connection.committed is True


def test_create_schema_creates_plaintext_v2_tables_for_fresh_database():
    connection = FakeConnection(
        fetchone=[
            None,
            {"schema_version": 2},
        ]
    )
    repository = _repository(lambda: connection)

    repository.create_schema()

    sql = "\n".join(statement for statement, _params in connection.executions)
    assert "CREATE TABLE IF NOT EXISTS api_account_credentials" in sql
    assert "secret_value TEXT NOT NULL" in sql
    assert "ALTER TABLE api_account_credentials" not in sql
    assert connection.committed is True


def test_create_schema_refuses_v1_migration_when_encrypted_rows_exist():
    connection = FakeConnection(
        fetchone=[
            {"schema_version": 1},
            {"credential_count": 2},
        ]
    )
    repository = _repository(lambda: connection)

    with pytest.raises(ApiCredentialSchemaError, match="已有加密数据"):
        repository.create_schema()

    assert not any(
        "ALTER TABLE api_account_credentials" in sql
        for sql, _params in connection.executions
    )
    assert connection.rolled_back is True
