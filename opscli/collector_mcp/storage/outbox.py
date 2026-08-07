"""Collector 采集结果 SQLite Outbox。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opscli.collector_mcp.storage.models import CollectionSubmission, OutboxRecord


class CollectionOutbox:
    """提供幂等提交、租约领取和完成确认。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def submit(self, submission: CollectionSubmission) -> int:
        """幂等写入一个成功采集任务并返回 Outbox ID。"""
        now = _utc_now_iso()
        payload_json = json.dumps(
            submission.to_dict(), ensure_ascii=False, separators=(",", ":")
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO collection_outbox (
                    source_system, source_job_id, data_environment, payload_json,
                    status, attempt_count, available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                ON CONFLICT(source_system, source_job_id, data_environment)
                DO NOTHING
                """,
                (
                    submission.source_system,
                    submission.source_job_id,
                    submission.data_environment,
                    payload_json,
                    now,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM collection_outbox
                WHERE source_system = ? AND source_job_id = ? AND data_environment = ?
                """,
                (
                    submission.source_system,
                    submission.source_job_id,
                    submission.data_environment,
                ),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Collection Outbox 幂等提交后未找到记录")
        return int(row["id"])

    def claim_next(
        self,
        *,
        owner: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> OutboxRecord | None:
        """领取下一条可执行记录，并恢复租约已经过期的执行记录。"""
        if not owner.strip():
            raise ValueError("Outbox 领取方不能为空")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        current_iso = current.isoformat(timespec="seconds")
        lease_expires_at = (
            current + timedelta(seconds=max(1.0, float(lease_seconds)))
        ).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE collection_outbox
                SET status = 'retrying', lease_owner = NULL, lease_expires_at = NULL,
                    available_at = ?, updated_at = ?
                WHERE status = 'processing' AND lease_expires_at <= ?
                """,
                (current_iso, current_iso, current_iso),
            )
            row = conn.execute(
                """
                SELECT * FROM collection_outbox
                WHERE status IN ('pending', 'retrying') AND available_at <= ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (current_iso,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                UPDATE collection_outbox
                SET status = 'processing', attempt_count = attempt_count + 1,
                    lease_owner = ?, lease_expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (owner, lease_expires_at, current_iso, row["id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM collection_outbox WHERE id = ?", (row["id"],)
            ).fetchone()
            conn.commit()
        return _row_to_record(claimed) if claimed is not None else None

    def complete(self, record_id: int, *, owner: str) -> bool:
        """仅允许当前租约持有者确认入库完成。"""
        now = _utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE collection_outbox
                SET status = 'completed', completed_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = NULL, last_error_message = NULL
                WHERE id = ? AND status = 'processing' AND lease_owner = ?
                """,
                (now, now, int(record_id), owner),
            )
        return int(cursor.rowcount or 0) == 1

    def retry(
        self,
        record_id: int,
        *,
        owner: str,
        error_code: str,
        error_message: str,
        delay_seconds: float,
    ) -> bool:
        """释放当前租约，并将临时失败记录延迟到下一次重试。"""
        now = datetime.now(timezone.utc)
        available_at = (
            now + timedelta(seconds=max(1.0, float(delay_seconds)))
        ).isoformat(timespec="seconds")
        now_iso = now.isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE collection_outbox
                SET status = 'retrying', available_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = ?, last_error_message = ?
                WHERE id = ? AND status = 'processing' AND lease_owner = ?
                """,
                (
                    available_at,
                    now_iso,
                    error_code[:128],
                    error_message[:1000],
                    int(record_id),
                    owner,
                ),
            )
        return int(cursor.rowcount or 0) == 1

    def fail(
        self,
        record_id: int,
        *,
        owner: str,
        error_code: str,
        error_message: str,
    ) -> bool:
        """将无法通过重试恢复的来源合同错误标记为永久失败。"""
        now = _utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE collection_outbox
                SET status = 'failed', updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = ?, last_error_message = ?
                WHERE id = ? AND status = 'processing' AND lease_owner = ?
                """,
                (
                    now,
                    error_code[:128],
                    error_message[:1000],
                    int(record_id),
                    owner,
                ),
            )
        return int(cursor.rowcount or 0) == 1

    def get(self, record_id: int) -> OutboxRecord:
        """读取一条 Outbox 记录。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM collection_outbox WHERE id = ?", (int(record_id),)
            ).fetchone()
        if row is None:
            raise ValueError(f"Collection Outbox 记录不存在：{record_id}")
        return _row_to_record(row)

    def contains(
        self,
        *,
        source_system: str,
        source_job_id: str,
        data_environment: str,
    ) -> bool:
        """判断来源任务是否已经进入 Outbox，不区分当前处理状态。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM collection_outbox
                WHERE source_system = ? AND source_job_id = ? AND data_environment = ?
                LIMIT 1
                """,
                (source_system, source_job_id, data_environment),
            ).fetchone()
        return row is not None

    def get_meta(self, key: str) -> str | None:
        """读取 Collector Outbox 生命周期元数据。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM collection_outbox_meta WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row is not None else None

    def status_counts(self) -> dict[str, int]:
        """返回脱敏健康检查使用的 Outbox 状态计数。"""
        counts = {
            "pending": 0,
            "processing": 0,
            "retrying": 0,
            "failed": 0,
            "completed": 0,
        }
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM collection_outbox GROUP BY status"
            ).fetchall()
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["count"] or 0)
        return counts

    def get_or_create_meta(self, key: str, value: str) -> str:
        """原子读取或初始化一个生命周期元数据值。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO collection_outbox_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
            row = conn.execute(
                "SELECT value FROM collection_outbox_meta WHERE key = ?", (key,)
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError(f"Collection Outbox 元数据初始化失败：{key}")
        return str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        """更新来源对账游标等生命周期元数据。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO collection_outbox_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_system TEXT NOT NULL,
                    source_job_id TEXT NOT NULL,
                    data_environment TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT NULL,
                    lease_expires_at TEXT NULL,
                    last_error_code TEXT NULL,
                    last_error_message TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    UNIQUE(source_system, source_job_id, data_environment)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_outbox_meta (
                    key TEXT NOT NULL PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_collection_outbox_claim
                ON collection_outbox(status, available_at, id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn


def _row_to_record(row: sqlite3.Row) -> OutboxRecord:
    payload = json.loads(str(row["payload_json"]))
    return OutboxRecord(
        id=int(row["id"]),
        submission=CollectionSubmission.from_dict(payload),
        status=str(row["status"]),
        attempt_count=int(row["attempt_count"] or 0),
        available_at=str(row["available_at"]),
        lease_owner=str(row["lease_owner"]) if row["lease_owner"] else None,
        lease_expires_at=(
            str(row["lease_expires_at"]) if row["lease_expires_at"] else None
        ),
        last_error_code=(
            str(row["last_error_code"]) if row["last_error_code"] else None
        ),
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
