"""卖家精灵 SQLite 任务队列仓储。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest


DEFAULT_QUEUE_DB_PATH = Path(CONFIG_DIR) / "seller_sprite" / "task_queue.sqlite3"


class SellerSpriteTaskQueueStore:
    """管理卖家精灵任务队列的本地 SQLite 仓储。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_QUEUE_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def enqueue(
        self,
        *,
        request: SellerSpriteScenarioRequest,
        queue_scope: str,
        root_dir: Path,
        session_id: str | None = None,
        jwt: str | None = None,
    ) -> dict[str, Any]:
        """写入一条排队任务并返回当前排队状态。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seller_sprite_task_queue (
                    job_id, queue_scope, status, request_json, root_dir,
                    created_at, started_at, finished_at, assigned_account,
                    worker_key, result_path, row_count, export_json, error_json,
                    session_id, jwt
                )
                VALUES (?, ?, 'queued', ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, ?, ?)
                """,
                (
                    request.job_id,
                    queue_scope,
                    json.dumps(request.to_dict(), ensure_ascii=False),
                    str(root_dir),
                    _now_iso(),
                    session_id,
                    jwt,
                ),
            )
        return self.get_status(str(request.job_id))

    def claim_next(
        self,
        *,
        queue_scope: str,
        worker_key: str,
        assigned_account: str,
    ) -> dict[str, Any] | None:
        """按 FIFO 取出下一条待执行任务并标记为运行中。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, *
                FROM seller_sprite_task_queue
                WHERE queue_scope = ? AND status = 'queued'
                ORDER BY id ASC
                LIMIT 1
                """,
                (queue_scope,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'running',
                    started_at = ?,
                    assigned_account = ?,
                    worker_key = ?
                WHERE id = ?
                """,
                (_now_iso(), assigned_account, worker_key, row["id"]),
            )
            conn.commit()
        return self.get_status(str(row["job_id"]))

    def finish_task(
        self,
        *,
        job_id: str,
        result_path: str,
        row_count: int,
        export_payload: dict[str, Any] | None,
    ) -> None:
        """标记任务成功完成。"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'succeeded',
                    finished_at = ?,
                    result_path = ?,
                    row_count = ?,
                    export_json = ?,
                    error_json = NULL
                WHERE job_id = ?
                """,
                (
                    _now_iso(),
                    result_path,
                    row_count,
                    json.dumps(export_payload, ensure_ascii=False) if export_payload is not None else None,
                    job_id,
                ),
            )

    def fail_task(self, *, job_id: str, error_payload: dict[str, Any]) -> None:
        """标记任务执行失败。"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'failed',
                    finished_at = ?,
                    error_json = ?
                WHERE job_id = ?
                """,
                (_now_iso(), json.dumps(error_payload, ensure_ascii=False), job_id),
            )

    def reset_running_tasks(self) -> int:
        """将异常中断留下的运行中任务重新放回队列。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    assigned_account = NULL,
                    worker_key = NULL
                WHERE status = 'running'
                """
            )
            return int(cursor.rowcount or 0)

    def get_status(self, job_id: str) -> dict[str, Any]:
        """读取任务当前状态。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, job_id, queue_scope, status, request_json, root_dir,
                       created_at, started_at, finished_at, assigned_account,
                       worker_key, result_path, row_count, export_json, error_json
                FROM seller_sprite_task_queue
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        return self._row_to_status(row)

    def get_request(self, job_id: str) -> SellerSpriteScenarioRequest:
        """读取任务原始请求。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT request_json FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        payload = json.loads(str(row["request_json"]))
        return SellerSpriteScenarioRequest(**payload)

    def get_task_context(self, job_id: str) -> dict[str, Any]:
        """读取任务执行所需的附加上下文。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, jwt FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        return {
            "session_id": row["session_id"],
            "jwt": row["jwt"],
        }

    def _ensure_schema(self) -> None:
        """初始化 SQLite 表结构。"""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    queue_scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    root_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT NULL,
                    finished_at TEXT NULL,
                    assigned_account TEXT NULL,
                    worker_key TEXT NULL,
                    result_path TEXT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    export_json TEXT NULL,
                    error_json TEXT NULL,
                    session_id TEXT NULL,
                    jwt TEXT NULL
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(seller_sprite_task_queue)")}
            if "session_id" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN session_id TEXT NULL")
            if "jwt" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN jwt TEXT NULL")

    def _connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接。"""
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _row_to_status(self, row: sqlite3.Row) -> dict[str, Any]:
        """将数据库记录转换为外部可读状态。"""
        status = str(row["status"])
        payload = json.loads(str(row["request_json"]))
        position = self._queue_position(int(row["id"])) if status == "queued" else None
        return {
            "job_id": str(row["job_id"]),
            "scenario": payload["scenario"],
            "site": payload["site"],
            "period": payload["period"],
            "state": status,
            "stage": _stage_for_status(status),
            "position": position,
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "root_dir": row["root_dir"],
            "assigned_account": row["assigned_account"],
            "worker_key": row["worker_key"],
            "result_path": row["result_path"],
            "row_count": int(row["row_count"] or 0),
            "export": json.loads(str(row["export_json"])) if row["export_json"] else None,
            "error": json.loads(str(row["error_json"])) if row["error_json"] else None,
        }

    def _queue_position(self, task_id: int) -> int:
        """计算某条排队任务在同一队列中的当前位置。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT queue_scope
                FROM seller_sprite_task_queue
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                return 0
            count_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM seller_sprite_task_queue
                WHERE queue_scope = ?
                  AND status = 'queued'
                  AND id <= ?
                """,
                (row["queue_scope"], task_id),
            ).fetchone()
        return int(count_row["cnt"] or 0)


def _stage_for_status(status: str) -> str:
    """将任务状态映射为对外阶段名。"""
    mapping = {
        "queued": "queued",
        "running": "running",
        "succeeded": "finished",
        "failed": "failed",
    }
    return mapping.get(status, status)


def _now_iso() -> str:
    """返回带时区的当前时间字符串。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
