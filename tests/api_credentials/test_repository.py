"""API 凭据 MySQL 仓储与多账号选择测试。"""

import base64
from datetime import datetime

from opscli.api_credentials.config import ApiCredentialMySqlSettings
from opscli.api_credentials.crypto import ApiKeyCipher
from opscli.api_credentials.repository import MySqlApiCredentialRepository
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


def _cipher():
    return ApiKeyCipher(base64.b64encode(b"r" * 32).decode("ascii"))


def _row(cipher, account_id, name, secret, priority):
    encrypted = cipher.encrypt(secret, account_id=account_id, version=1)
    return {
        "account_id": account_id,
        "provider": "serpapi",
        "account_name": name,
        "status": "active",
        "priority": priority,
        "remark": None,
        "secret_ciphertext": encrypted.ciphertext,
        "secret_nonce": encrypted.nonce,
        "encrypted_dek": encrypted.encrypted_dek,
        "dek_nonce": encrypted.dek_nonce,
        "secret_masked": encrypted.masked,
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


def _repository(cipher, factory):
    return MySqlApiCredentialRepository(
        settings=ApiCredentialMySqlSettings(
            host="mysql.internal",
            database="ops",
            user="runtime",
            password="secret",
        ),
        cipher=cipher,
        connect_factory=factory,
    )


def test_schema_models_provider_accounts_credentials_runtime_and_audit():
    sql = "\n".join(SCHEMA_STATEMENTS)

    assert "api_provider_accounts" in sql
    assert "api_account_credentials" in sql
    assert "api_account_runtime" in sql
    assert "api_credential_audit_logs" in sql
    assert "UNIQUE KEY uq_api_provider_account (provider, account_name)" in sql
    assert "encrypted_dek" in sql


def test_list_accounts_decrypts_multiple_accounts_but_public_output_is_masked():
    cipher = _cipher()
    connection = FakeConnection(
        fetchall=[
            _row(cipher, 1, "primary", "primary-secret-key", 10),
            _row(cipher, 2, "backup", "backup-secret-key", 20),
        ]
    )
    repository = _repository(cipher, lambda: connection)

    accounts = repository.list_accounts("serpapi")

    assert [account.name for account in accounts] == ["primary", "backup"]
    assert accounts[0].api_key == "primary-secret-key"
    assert accounts[1].api_key == "backup-secret-key"
    assert "primary-secret-key" not in str(accounts[0].to_public_dict())
    assert accounts[0].provider_metadata == {"plan_name": "Developer"}


def test_acquire_uses_locked_priority_lru_selection_and_marks_selected():
    cipher = _cipher()
    row = _row(cipher, 2, "backup", "backup-secret-key", 20)
    select_connection = FakeConnection(fetchone=row)
    reread_connection = FakeConnection(fetchone=row)
    connections = iter([select_connection, reread_connection])
    repository = _repository(cipher, lambda: next(connections))

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
