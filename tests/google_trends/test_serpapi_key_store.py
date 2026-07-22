"""SerpApi API Key SQLite 仓储测试。"""

import sqlite3
from pathlib import Path

from opscli.google_trends.api.key_store import SerpApiKeyStore


def test_key_store_saves_plaintext_and_selects_oldest_active_key(tmp_path: Path):
    """仓储应按约定保存明文，并优先返回最久未使用的 active Key。"""
    db_path = tmp_path / "serpapi.sqlite3"
    store = SerpApiKeyStore(db_path)
    first = store.add_key(name="first", api_key="secret-first")
    second = store.add_key(name="second", api_key="secret-second")
    store.mark_used(first.key_id)

    selected = store.next_active_key()

    assert selected is not None
    assert selected.key_id == second.key_id
    with sqlite3.connect(db_path) as conn:
        saved = conn.execute(
            "SELECT api_key FROM google_trends_serpapi_keys WHERE key_id = ?",
            (first.key_id,),
        ).fetchone()[0]
    assert saved == "secret-first"


def test_key_store_gets_key_by_case_insensitive_name(tmp_path: Path):
    """仓储应支持按不区分大小写的账号名称查询。"""
    store = SerpApiKeyStore(tmp_path / "serpapi.sqlite3")
    created = store.add_key(name="Primary", api_key="secret-primary")

    found = store.get_by_name("primary")

    assert found is not None
    assert found.key_id == created.key_id
    assert store.get_by_name("missing") is None


def test_key_store_saves_and_updates_remark(tmp_path: Path):
    """新增和同名更新 API Key 时应保存备注。"""
    store = SerpApiKeyStore(tmp_path / "serpapi.sqlite3")

    created = store.add_key(
        name="primary",
        api_key="secret-primary",
        remark="主账号",
    )
    updated = store.add_key(
        name="primary",
        api_key="secret-replaced",
        remark="备用账号",
    )

    assert created.remark == "主账号"
    assert updated.key_id == created.key_id
    assert updated.remark == "备用账号"
    assert updated.to_public_dict()["remark"] == "备用账号"


def test_key_store_migrates_legacy_table_with_remark_column(tmp_path: Path):
    """初始化旧版数据库时应自动增加可空 remark 列。"""
    db_path = tmp_path / "serpapi.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE google_trends_serpapi_keys (
                key_id TEXT NOT NULL PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                api_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                total_searches_left INTEGER,
                this_month_usage INTEGER,
                plan_name TEXT,
                plan_renewal_date TEXT,
                last_checked_at TEXT,
                last_used_at TEXT,
                exhausted_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(status IN ('active', 'exhausted', 'disabled'))
            )
            """
        )

    store = SerpApiKeyStore(db_path)
    record = store.add_key(
        name="migrated",
        api_key="secret-migrated",
        remark="旧库迁移",
    )

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(google_trends_serpapi_keys)"
            ).fetchall()
        }
    assert "remark" in columns
    assert record.remark == "旧库迁移"


def test_exhausted_and_disabled_keys_are_never_selected(tmp_path: Path):
    """耗尽或人工禁用的 Key 不应被自动恢复或再次选择。"""
    store = SerpApiKeyStore(tmp_path / "serpapi.sqlite3")
    exhausted = store.add_key(name="exhausted", api_key="secret-exhausted")
    disabled = store.add_key(name="disabled", api_key="secret-disabled")
    store.mark_exhausted(exhausted.key_id, reason="额度为 0")
    store.set_status(disabled.key_id, "disabled")

    store.add_key(name="exhausted", api_key="secret-replaced")

    assert store.next_active_key() is None
    assert store.get(exhausted.key_id).status == "exhausted"
    assert store.get(exhausted.key_id).api_key == "secret-replaced"
    assert store.get(disabled.key_id).status == "disabled"


def test_public_key_summary_redacts_secret_from_error(tmp_path: Path):
    """公开 Key 摘要不能通过错误文本泄露明文 Key。"""
    store = SerpApiKeyStore(tmp_path / "serpapi.sqlite3")
    key = store.add_key(name="primary", api_key="secret-sensitive")
    store.record_error(key.key_id, reason="request failed for secret-sensitive")

    summary = store.get(key.key_id).to_public_dict()

    assert "secret-sensitive" not in str(summary)
    assert summary["last_error"] == "request failed for ***"


def test_account_snapshot_updates_quota_fields(tmp_path: Path):
    """Account API 快照应更新剩余额度和套餐字段。"""
    store = SerpApiKeyStore(tmp_path / "serpapi.sqlite3")
    key = store.add_key(name="primary", api_key="secret")

    updated = store.update_account_snapshot(
        key.key_id,
        {
            "total_searches_left": 42,
            "this_month_usage": 8,
            "plan_name": "Developer",
            "plan_renewal_date": "2026-08-01",
        },
    )

    assert updated.total_searches_left == 42
    assert updated.this_month_usage == 8
    assert updated.plan_name == "Developer"
    assert updated.plan_renewal_date == "2026-08-01"
