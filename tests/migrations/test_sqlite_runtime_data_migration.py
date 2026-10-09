import sqlite3

import pytest

from opscli.migrations.sqlite_runtime import migrate_quota_snapshot


class FakeCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executions = []
        self.many_executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def executemany(self, sql, params):
        self.many_executions.append((sql, list(params)))

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


def test_quota_snapshot_dry_run_validates_counts_without_writing(tmp_path):
    sqlite_path = tmp_path / "quota.sqlite3"
    _create_quota_sqlite(sqlite_path)
    mysql = FakeConnection(
        [
            {"row_count": 0},
            {"row_count": 0},
            {"row_count": 0},
            {"row_count": 0},
            {"schema_version": 1},
        ]
    )

    report = migrate_quota_snapshot(
        sqlite_path=sqlite_path,
        mysql=mysql,
        apply=False,
    )

    assert report["mode"] == "dry_run"
    assert report["source_counts"] == {
        "mcp_quota_policy": 1,
        "mcp_quota_migrations": 1,
        "mcp_quota_daily": 1,
        "mcp_quota_bonus_daily": 1,
    }
    assert len(report["source_sha256"]) == 64
    assert mysql.cursor_instance.many_executions == []
    assert mysql.committed is False


def test_quota_snapshot_apply_writes_all_tables(tmp_path):
    sqlite_path = tmp_path / "quota.sqlite3"
    _create_quota_sqlite(sqlite_path)
    mysql = FakeConnection(
        [
            {"row_count": 0},
            {"row_count": 0},
            {"row_count": 0},
            {"row_count": 0},
            {"schema_version": 1},
        ]
    )

    report = migrate_quota_snapshot(
        sqlite_path=sqlite_path,
        mysql=mysql,
        apply=True,
    )

    assert report["mode"] == "apply"
    assert len(mysql.cursor_instance.many_executions) == 4
    daily_params = mysql.cursor_instance.many_executions[2][1][0]
    assert str(daily_params[1]) == "2026-09-20"
    assert mysql.committed is True


def test_migration_refuses_nonempty_target_by_default(tmp_path):
    sqlite_path = tmp_path / "quota.sqlite3"
    _create_quota_sqlite(sqlite_path)
    mysql = FakeConnection(
        [
            {"row_count": 1},
            {"row_count": 0},
            {"row_count": 0},
            {"row_count": 0},
        ]
    )

    with pytest.raises(RuntimeError, match="not empty"):
        migrate_quota_snapshot(
            sqlite_path=sqlite_path,
            mysql=mysql,
            apply=False,
        )


def _create_quota_sqlite(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE mcp_quota_policy (
                tool_name TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                daily_limit INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                timezone TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE mcp_quota_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
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
            );
            CREATE TABLE mcp_quota_bonus_daily (
                service TEXT NOT NULL,
                email TEXT NOT NULL,
                bonus_daily_limit INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, email)
            );
            """
        )
        connection.execute(
            "INSERT INTO mcp_quota_policy VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "seller_sprite_run",
                "seller_sprite",
                100,
                1,
                "Asia/Shanghai",
                "2026-09-20T08:00:00+08:00",
                "2026-09-20T08:00:00+08:00",
            ),
        )
        connection.execute(
            "INSERT INTO mcp_quota_migrations VALUES (?, ?)",
            ("migration-1", "2026-09-20T08:00:00+08:00"),
        )
        connection.execute(
            "INSERT INTO mcp_quota_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "seller_sprite",
                "20260920",
                "a" * 64,
                "email",
                "user@example.com",
                2,
                1,
                100,
                "2026-09-21T00:00:00+08:00",
                "2026-09-20T12:00:00+08:00",
            ),
        )
        connection.execute(
            "INSERT INTO mcp_quota_bonus_daily VALUES (?, ?, ?, ?, ?)",
            (
                "seller_sprite",
                "user@example.com",
                10,
                "2026-09-20T08:00:00+08:00",
                "2026-09-20T08:00:00+08:00",
            ),
        )
