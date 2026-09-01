"""AppHub SQLite migrations 运行器。"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from opscli.app.domain.exceptions import AppProjectError


def run_migrations(
    project_dir: str | Path = ".",
    *,
    db_path: str | Path | None = None,
) -> dict:
    """按文件名顺序幂等执行 migrations/*.sql。"""
    root = Path(project_dir).expanduser().resolve()
    configured = str(db_path or os.getenv("APP_DB_PATH") or "").strip()
    if not configured:
        return {"applied": [], "skipped": True, "reason": "APP_DB_PATH 未配置"}

    migrations_dir = root / "migrations"
    if not migrations_dir.is_dir():
        return {"applied": [], "skipped": True, "reason": "migrations 目录不存在"}

    database = Path(configured).expanduser()
    if not database.is_absolute():
        database = (root / database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    migration_files = sorted(migrations_dir.glob("*.sql"))
    applied: list[str] = []

    try:
        connection = sqlite3.connect(database, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        existing = {row[0] for row in connection.execute("SELECT name FROM _migrations")}
        for path in migration_files:
            if path.name in existing:
                continue
            sql = path.read_text(encoding="utf-8-sig")
            with connection:
                connection.executescript(sql)
                connection.execute(
                    "INSERT INTO _migrations(name, applied_at) VALUES (?, ?)",
                    (path.name, datetime.now(timezone.utc).isoformat()),
                )
            applied.append(path.name)
    except (OSError, UnicodeError, sqlite3.Error) as exc:
        raise AppProjectError(
            "DB-MIGRATE",
            f"SQLite migration 执行失败：{exc}",
            fix_hint="检查 migrations SQL 与 APP_DB_PATH 后重试。",
        ) from exc
    finally:
        if "connection" in locals():
            connection.close()

    return {"applied": applied, "skipped": False, "database": str(database)}
