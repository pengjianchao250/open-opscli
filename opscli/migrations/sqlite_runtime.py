"""Migrate the quota SQLite snapshot into MySQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from opscli.shared.runtime_mysql import load_runtime_mysql_settings


QUOTA_TABLES = (
    "mcp_quota_policy",
    "mcp_quota_migrations",
    "mcp_quota_daily",
    "mcp_quota_bonus_daily",
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    settings = load_runtime_mysql_settings()
    if not settings.configured:
        parser.error(
            "MySQL settings are incomplete; configure OPSCLI_RUNTIME_MYSQL_* "
            "or OPSCLI_COLLECTION_MYSQL_*"
        )

    source_path = Path(args.sqlite).expanduser().resolve()
    if not source_path.is_file():
        parser.error(f"SQLite snapshot does not exist: {source_path}")

    mysql = _connect_mysql(settings)
    try:
        report = migrate_quota_snapshot(
            sqlite_path=source_path,
            mysql=mysql,
            apply=args.apply,
            allow_nonempty=args.allow_nonempty,
        )
    finally:
        mysql.close()

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def migrate_quota_snapshot(
    *,
    sqlite_path: Path,
    mysql: Any,
    apply: bool,
    allow_nonempty: bool = False,
) -> dict[str, Any]:
    with closing(_connect_sqlite_readonly(sqlite_path)) as source:
        _check_sqlite(source, QUOTA_TABLES)
        rows = {table: _read_rows(source, table) for table in QUOTA_TABLES}

    target_counts = _target_counts(mysql, QUOTA_TABLES)
    _require_empty_targets(target_counts, allow_nonempty=allow_nonempty)
    schema_version = _schema_version(
        mysql,
        table="mcp_quota_schema_versions",
        module="mcp_quota",
    )
    if schema_version != 1:
        raise RuntimeError(
            f"MySQL quota schema version mismatch: expected 1, got {schema_version}"
        )

    if apply:
        try:
            with mysql.cursor() as cursor:
                _write_quota_rows(cursor, rows)
            mysql.commit()
        except Exception:
            mysql.rollback()
            raise

    return _report(
        module="quota",
        sqlite_path=sqlite_path,
        rows=rows,
        target_counts=target_counts,
        applied=apply,
    )


def _write_quota_rows(cursor: Any, rows: dict[str, list[dict[str, Any]]]) -> None:
    cursor.executemany(
        """
        INSERT INTO mcp_quota_policy (
            tool_name, service, daily_limit, enabled, timezone,
            created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            service = VALUES(service),
            daily_limit = VALUES(daily_limit),
            enabled = VALUES(enabled),
            timezone = VALUES(timezone),
            updated_at = VALUES(updated_at)
        """,
        [
            (
                row["tool_name"],
                row["service"],
                int(row["daily_limit"]),
                int(row["enabled"]),
                row["timezone"],
                _mysql_datetime(row["created_at"]),
                _mysql_datetime(row["updated_at"]),
            )
            for row in rows["mcp_quota_policy"]
        ],
    )
    cursor.executemany(
        """
        INSERT INTO mcp_quota_migrations (migration_id, applied_at)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE applied_at = VALUES(applied_at)
        """,
        [
            (row["migration_id"], _mysql_datetime(row["applied_at"]))
            for row in rows["mcp_quota_migrations"]
        ],
    )
    cursor.executemany(
        """
        INSERT INTO mcp_quota_daily (
            service, quota_day, identity_hash, identity_type, identity_key,
            calls, failures, limit_count, reset_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            identity_type = VALUES(identity_type),
            identity_key = VALUES(identity_key),
            calls = VALUES(calls),
            failures = VALUES(failures),
            limit_count = VALUES(limit_count),
            reset_at = VALUES(reset_at),
            updated_at = VALUES(updated_at)
        """,
        [
            (
                row["service"],
                _quota_day(row["day"]),
                row["identity_hash"],
                row["identity_type"],
                row.get("identity_key") or "",
                int(row["calls"]),
                int(row["failures"]),
                int(row["limit_count"]),
                _mysql_datetime(row["reset_at"]),
                _mysql_datetime(row["updated_at"]),
            )
            for row in rows["mcp_quota_daily"]
        ],
    )
    cursor.executemany(
        """
        INSERT INTO mcp_quota_bonus_daily (
            service, email, bonus_daily_limit, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            bonus_daily_limit = VALUES(bonus_daily_limit),
            updated_at = VALUES(updated_at)
        """,
        [
            (
                row["service"],
                str(row["email"]).strip().lower(),
                int(row["bonus_daily_limit"]),
                _mysql_datetime(row["created_at"]),
                _mysql_datetime(row["updated_at"]),
            )
            for row in rows["mcp_quota_bonus_daily"]
        ],
    )


def _connect_sqlite_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _check_sqlite(connection: sqlite3.Connection, required_tables: tuple[str, ...]) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or str(integrity[0]).lower() != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = sorted(set(required_tables) - existing)
    if missing:
        raise RuntimeError(f"SQLite snapshot is missing tables: {', '.join(missing)}")


def _read_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"').fetchall()]


def _target_counts(mysql: Any, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with mysql.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) AS row_count FROM `{table}`")
            row = cursor.fetchone()
            counts[table] = int(row.get("row_count") or 0)
    return counts


def _require_empty_targets(
    target_counts: dict[str, int],
    *,
    allow_nonempty: bool,
) -> None:
    nonempty = {table: count for table, count in target_counts.items() if count}
    if nonempty and not allow_nonempty:
        raise RuntimeError(
            "MySQL target tables are not empty; rerun only after review with "
            f"--allow-nonempty: {nonempty}"
        )


def _schema_version(mysql: Any, *, table: str, module: str) -> int:
    with mysql.cursor() as cursor:
        cursor.execute(
            f"SELECT schema_version FROM `{table}` WHERE module_name = %s",
            (module,),
        )
        row = cursor.fetchone()
    return int(row.get("schema_version") or 0) if row else 0


def _report(
    *,
    module: str,
    sqlite_path: Path,
    rows: dict[str, list[dict[str, Any]]],
    target_counts: dict[str, int],
    applied: bool,
) -> dict[str, Any]:
    return {
        "success": True,
        "module": module,
        "mode": "apply" if applied else "dry_run",
        "source_sha256": _sha256(sqlite_path),
        "source_counts": {table: len(items) for table, items in rows.items()},
        "target_counts_before": target_counts,
    }


def _quota_day(value: Any) -> date:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid quota day: {text}")


def _mysql_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Datetime value cannot be empty")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_mysql(settings: Any) -> Any:
    try:
        import pymysql
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMySQL is required for SQLite runtime migration") from exc
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=60,
        write_timeout=60,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        ssl_ca=settings.ssl_ca or None,
        ssl_verify_cert=bool(settings.ssl_ca),
        ssl_verify_identity=bool(settings.ssl_ca),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate a read-only SQLite snapshot into runtime MySQL tables."
    )
    subparsers = parser.add_subparsers(dest="module", required=True)

    quota = subparsers.add_parser("quota")
    _common_arguments(quota)

    return parser


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sqlite", required=True, help="SQLite snapshot path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write MySQL data; without this flag only validation runs",
    )
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="Allow idempotent upsert into reviewed non-empty target tables",
    )


if __name__ == "__main__":
    raise SystemExit(main())
