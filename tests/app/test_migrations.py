from __future__ import annotations

import sqlite3
from pathlib import Path

from opscli.app.services.migrations import run_migrations


def test_migrations_are_ordered_and_idempotent(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_init.sql").write_text("CREATE TABLE notes(id INTEGER PRIMARY KEY);", encoding="utf-8")
    (migrations / "002_seed.sql").write_text("INSERT INTO notes(id) VALUES (1);", encoding="utf-8")
    database = tmp_path / "data" / "app.db"

    first = run_migrations(tmp_path, db_path=database)
    second = run_migrations(tmp_path, db_path=database)

    assert first["applied"] == ["001_init.sql", "002_seed.sql"]
    assert second["applied"] == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0] == 2


def test_migrations_skip_without_database(tmp_path: Path) -> None:
    result = run_migrations(tmp_path, db_path=None)
    assert result["skipped"] is True
