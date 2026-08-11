"""API 凭据池管理命令与 SQLite 迁移测试。"""

from types import SimpleNamespace

from typer.testing import CliRunner

from opscli.api_credentials import cli as credential_cli
from opscli.google_trends.api.key_store import SerpApiKeyStore


runner = CliRunner()


def _account(account_id=1, name="primary", status="active"):
    return SimpleNamespace(
        account_id=account_id,
        provider="serpapi",
        name=name,
        to_public_dict=lambda: {
            "account_id": account_id,
            "provider": "serpapi",
            "name": name,
            "api_key_masked": "secr****-key",
            "status": status,
        },
    )


def test_add_uses_confirmed_hidden_input_and_never_echoes_key(monkeypatch):
    calls = {}

    class FakeRepository:
        def upsert_account(self, **kwargs):
            calls.update(kwargs)
            return _account()

    monkeypatch.setattr(credential_cli, "_repository", lambda: FakeRepository())

    result = runner.invoke(
        credential_cli.app,
        ["add", "--provider", "serpapi", "--name", "primary"],
        input="secret-api-key\nsecret-api-key\n",
    )

    assert result.exit_code == 0
    assert calls["api_key"] == "secret-api-key"
    assert "secret-api-key" not in result.stdout
    assert '"api_key_masked": "secr****-key"' in result.stdout


def test_delete_logically_removes_account_and_keeps_audit_actor(monkeypatch):
    """删除命令应写 deleted 状态，而不是物理删除账号和审计。"""
    calls = []

    class FakeRepository:
        def get_account(self, account_id):
            status = "deleted" if calls else "active"
            return _account(account_id=account_id, status=status)

        def set_status(self, account_id, status, *, actor=None):
            calls.append((account_id, status, actor))

    monkeypatch.setattr(credential_cli, "_repository", lambda: FakeRepository())

    result = runner.invoke(
        credential_cli.app,
        ["delete", "--account-id", "9", "--actor", "admin@example.com", "--yes"],
    )

    assert result.exit_code == 0
    assert calls == [(9, "deleted", "admin@example.com")]
    assert '"status": "deleted"' in result.stdout


def test_migrate_serpapi_sqlite_preserves_account_state(monkeypatch, tmp_path):
    source_path = tmp_path / "serpapi.sqlite3"
    source = SerpApiKeyStore(source_path)
    record = source.add_key(name="backup-1", api_key="legacy-secret", remark="备用")
    source.update_account_snapshot(
        record.key_id,
        {
            "total_searches_left": 77,
            "this_month_usage": 23,
            "plan_name": "Developer",
            "plan_renewal_date": "2026-09-01",
        },
    )
    source.set_status(record.key_id, "disabled")
    calls = {"runtime": [], "status": []}

    class FakeRepository:
        def upsert_account(self, **kwargs):
            assert kwargs["api_key"] == "legacy-secret"
            assert kwargs["name"] == "backup-1"
            return _account(account_id=9, name="backup-1")

        def update_runtime(self, account_id, values):
            calls["runtime"].append((account_id, values))

        def set_status(self, account_id, status, *, actor=None):
            calls["status"].append((account_id, status, actor))

    monkeypatch.setattr(credential_cli, "_repository", lambda: FakeRepository())

    result = runner.invoke(
        credential_cli.app,
        [
            "migrate-serpapi-sqlite",
            "--sqlite-path",
            str(source_path),
            "--actor",
            "admin@example.com",
        ],
    )

    assert result.exit_code == 0
    assert '"migrated_accounts": 1' in result.stdout
    assert calls["runtime"][0][1]["remaining_quota"] == 77
    assert calls["runtime"][0][1]["provider_metadata"]["plan_name"] == "Developer"
    assert calls["status"] == [(9, "disabled", "admin@example.com")]
