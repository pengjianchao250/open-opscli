"""Collector Monitor 账号与当日额度只读仓储契约测试。"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from opscli.collector_monitor.account_repository import AccountMonitorRepository


NOW = datetime(2026, 8, 5, 4, 30, tzinfo=timezone.utc)


def _account_key(name: str, username: str) -> str:
    identity = f"seller_sprite:{name.casefold()}:{username.casefold()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _create_binding_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE seller_sprite_dedicated_accounts (
                account_id TEXT PRIMARY KEY,
                account_name TEXT NOT NULL,
                username TEXT NOT NULL,
                password_ciphertext BLOB NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE seller_sprite_user_account_bindings (
                user_email TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO seller_sprite_dedicated_accounts VALUES (?, ?, ?, ?, ?, ?)",
            (
                "raw-account-id-must-not-leak",
                "Dedicated A",
                "seller.account@example.com",
                b"encrypted-password-must-not-leak",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO seller_sprite_user_account_bindings VALUES (?, ?, ?, ?)",
            (
                "alice.smith@example.com",
                "raw-account-id-must-not-leak",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )


def _create_queue_db(path: Path, account_key: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE seller_sprite_task_queue (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                assigned_account TEXT,
                assigned_account_key TEXT,
                started_at TEXT,
                finished_at TEXT,
                last_error_code TEXT
            );
            CREATE TABLE seller_sprite_account_events (
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                account_key TEXT,
                account_name TEXT,
                masked_username TEXT,
                job_id TEXT,
                error_code TEXT
            );
            CREATE TABLE seller_sprite_account_quarantine (
                account_key TEXT NOT NULL,
                credential_version TEXT NOT NULL,
                reason TEXT NOT NULL,
                first_failed_at TEXT NOT NULL,
                last_failed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                failure_count INTEGER NOT NULL,
                last_error_code TEXT,
                PRIMARY KEY (account_key, credential_version)
            );
            """
        )
        conn.executemany(
            "INSERT INTO seller_sprite_task_queue VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "job-running",
                    "running",
                    "Dedicated A",
                    account_key,
                    "2026-08-05T04:00:00+00:00",
                    None,
                    None,
                ),
                (
                    "job-success",
                    "succeeded",
                    "Dedicated A",
                    account_key,
                    "2026-08-05T01:00:00+00:00",
                    "2026-08-05T02:00:00+00:00",
                    None,
                ),
                (
                    "job-failure",
                    "failed",
                    "Dedicated A",
                    account_key,
                    "2026-08-05T02:30:00+00:00",
                    "2026-08-05T03:00:00+00:00",
                    "AUTH_FAILED",
                ),
            ],
        )


def _create_quota_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE mcp_quota_daily (
                service TEXT NOT NULL,
                day TEXT NOT NULL,
                identity_hash TEXT NOT NULL,
                identity_type TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                calls INTEGER NOT NULL,
                failures INTEGER NOT NULL,
                limit_count INTEGER NOT NULL,
                reset_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, day, identity_hash)
            )
            """
        )
        conn.executemany(
            "INSERT INTO mcp_quota_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "seller_sprite",
                    "20260805",
                    "identity-hash-must-not-leak",
                    "email",
                    "alice.smith@example.com",
                    7,
                    2,
                    100,
                    "2026-08-06T00:00:00+08:00",
                    "2026-08-05T12:30:00+08:00",
                ),
                (
                    "seller_sprite",
                    "20260804",
                    "old-hash",
                    "email",
                    "old@example.com",
                    99,
                    1,
                    100,
                    "2026-08-05T00:00:00+08:00",
                    "2026-08-04T12:30:00+08:00",
                ),
            ],
        )


def test_accounts_returns_masked_health_binding_and_active_usage(tmp_path: Path) -> None:
    binding_db = tmp_path / "bindings.sqlite3"
    queue_db = tmp_path / "queue.sqlite3"
    quota_db = tmp_path / "quota.sqlite3"
    key = _account_key("Dedicated A", "seller.account@example.com")
    _create_binding_db(binding_db)
    _create_queue_db(queue_db, key)
    _create_quota_db(quota_db)
    repository = AccountMonitorRepository(
        queue_db_path=queue_db,
        binding_db_path=binding_db,
        quota_db_path=quota_db,
        clock=lambda: NOW,
    )

    payload = repository.accounts(limit=100)

    assert payload["source"] == {"ready": True, "error": None}
    assert payload["accounts"] == [
        {
            "identity": key[:12],
            "name": "Dedicated A",
            "username": "s***@example.com",
            "bound_users": ["a***@example.com"],
            "health": "unhealthy",
            "active_task_count": 1,
            "active_tasks": ["job-running"],
            "last_success": {
                "at": "2026-08-05T02:00:00+00:00",
                "job_id": "job-success",
            },
            "last_failure": {
                "at": "2026-08-05T03:00:00+00:00",
                "job_id": "job-failure",
                "code": "AUTH_FAILED",
            },
        }
    ]
    serialized = repr(payload)
    assert "raw-account-id" not in serialized
    assert "alice.smith@example.com" not in serialized
    assert "seller.account@example.com" not in serialized
    assert "encrypted-password" not in serialized


def test_usage_today_uses_shanghai_day_and_counts_refunded_failures(tmp_path: Path) -> None:
    binding_db = tmp_path / "bindings.sqlite3"
    queue_db = tmp_path / "queue.sqlite3"
    quota_db = tmp_path / "quota.sqlite3"
    _create_binding_db(binding_db)
    _create_queue_db(queue_db, _account_key("Dedicated A", "seller.account@example.com"))
    _create_quota_db(quota_db)
    repository = AccountMonitorRepository(
        queue_db_path=queue_db,
        binding_db_path=binding_db,
        quota_db_path=quota_db,
        clock=lambda: NOW,
    )

    payload = repository.usage_today(limit=100)

    assert payload == {
        "day": "20260805",
        "timezone": "Asia/Shanghai",
        "source": {"ready": True, "error": None},
        "usage": [
            {
                "service": "seller_sprite",
                "identity": "a***@example.com",
                "identity_type": "email",
                "calls": 7,
                "failures": 2,
                "total": 9,
                "daily_limit": 100,
                "remaining": 93,
                "reset_at": "2026-08-06T00:00:00+08:00",
            }
        ],
    }


def test_unavailable_sources_return_stable_errors_without_creating_sqlite_files(
    tmp_path: Path,
) -> None:
    queue_db = tmp_path / "missing-queue.sqlite3"
    binding_db = tmp_path / "missing-bindings.sqlite3"
    quota_db = tmp_path / "missing-quota.sqlite3"
    repository = AccountMonitorRepository(
        queue_db_path=queue_db,
        binding_db_path=binding_db,
        quota_db_path=quota_db,
        clock=lambda: NOW,
    )

    accounts = repository.accounts(limit=100)
    usage = repository.usage_today(limit=100)

    assert accounts == {
        "source": {
            "ready": False,
            "error": {
                "code": "account_source_unavailable",
                "message": "SellerSprite 账号监控数据源不可用",
            },
        },
        "accounts": [],
    }
    assert usage["source"] == {
        "ready": False,
        "error": {
            "code": "quota_source_unavailable",
            "message": "MCP 当日额度数据源不可用",
        },
    }
    assert usage["usage"] == []
    assert not queue_db.exists()
    assert not binding_db.exists()
    assert not quota_db.exists()
