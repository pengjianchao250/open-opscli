"""卖家精灵 SQLite 任务队列仓储。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest


DEFAULT_QUEUE_DB_PATH = Path(CONFIG_DIR) / "seller_sprite" / "task_queue.sqlite3"
DEFAULT_MCP_RUN_MODE = "browser-route"
TASK_KIND_GENERIC = "generic"
TASK_KIND_LISTING_ANALYSIS = "listing_analysis"
# 版本 2 引入账号级领取、执行代际、故障接替和账号事件审计。
QUEUE_SCHEMA_VERSION = 2


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
                    job_id, queue_scope, task_kind, status, request_json, root_dir,
                    created_at, started_at, finished_at, assigned_account,
                    worker_key, result_path, row_count, export_json, error_json,
                    session_id, jwt
                )
                VALUES (?, ?, ?, 'queued', ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, ?, ?)
                """,
                (
                    request.job_id,
                    queue_scope,
                    _task_kind_for_request(request),
                    json.dumps(request.to_dict(), ensure_ascii=False),
                    str(root_dir),
                    _now_iso(),
                    session_id,
                    jwt,
                ),
            )
        return self.get_status(str(request.job_id))

    def enqueue_owned_mcp_run(
        self,
        *,
        request: SellerSpriteScenarioRequest,
        queue_scope: str,
        root_dir: Path,
        user_email: str,
        session_id: str | None = None,
        jwt: str | None = None,
    ) -> dict[str, Any]:
        """在同一事务中写入队列任务及其 MCP 所有权记录。"""
        now = _now_iso()
        with self._connect() as conn:
            # 使用立即事务锁定写入顺序，任一唯一约束失败都会回滚两张表。
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO seller_sprite_task_queue (
                    job_id, queue_scope, task_kind, status, request_json, root_dir,
                    created_at, started_at, finished_at, assigned_account,
                    worker_key, result_path, row_count, export_json, error_json,
                    session_id, jwt
                )
                VALUES (?, ?, ?, 'queued', ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, ?, ?)
                """,
                (
                    request.job_id,
                    queue_scope,
                    _task_kind_for_request(request),
                    json.dumps(request.to_dict(), ensure_ascii=False),
                    str(root_dir),
                    now,
                    session_id,
                    jwt,
                ),
            )
            conn.execute(
                """
                INSERT INTO seller_sprite_mcp_runs (
                    job_id, user_email, scenario, mode, params_json,
                    result_state, result_row_count, result_export_format,
                    result_export_filename, result_export_job_id, error_json,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', 0, NULL, NULL, NULL, NULL, ?, NULL, NULL, ?)
                """,
                (
                    request.job_id,
                    user_email,
                    request.scenario,
                    DEFAULT_MCP_RUN_MODE,
                    json.dumps(request.params, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
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
                SELECT queued.id, queued.*
                FROM seller_sprite_task_queue AS queued
                WHERE queued.queue_scope = ?
                  AND queued.status = 'queued'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS running
                      WHERE running.queue_scope = queued.queue_scope
                        AND running.status = 'running'
                  )
                ORDER BY queued.id ASC
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

    def claim_next_generic_for_account(
        self,
        *,
        queue_scope: str,
        account_key: str,
        assigned_account: str,
        worker_key: str,
    ) -> dict[str, Any] | None:
        """为指定账号原子领取最早的通用任务。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT queued.id, queued.job_id
                FROM seller_sprite_task_queue AS queued
                WHERE queued.queue_scope = ?
                  AND queued.task_kind = ?
                  AND queued.status = 'queued'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS legacy_running
                      WHERE legacy_running.queue_scope = queued.queue_scope
                        AND legacy_running.task_kind = ?
                        AND legacy_running.status = 'running'
                        AND legacy_running.assigned_account_key IS NULL
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS running
                      WHERE running.queue_scope = queued.queue_scope
                        AND running.status = 'running'
                        AND running.assigned_account_key = ?
                  )
                ORDER BY queued.id ASC
                LIMIT 1
                """,
                (queue_scope, TASK_KIND_GENERIC, TASK_KIND_GENERIC, account_key),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            try:
                cursor = conn.execute(
                    """
                    UPDATE seller_sprite_task_queue
                    SET status = 'running',
                        started_at = ?,
                        assigned_account = ?,
                        assigned_account_key = ?,
                        worker_key = ?,
                        assignment_generation = assignment_generation + 1
                    WHERE id = ?
                      AND status = 'queued'
                    """,
                    (_now_iso(), assigned_account, account_key, worker_key, row["id"]),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return None
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return None
            conn.commit()
        return self.get_status(str(row["job_id"]))

    def claim_next_listing_analysis(
        self,
        *,
        queue_scope: str,
        worker_key: str,
        assigned_account: str,
    ) -> dict[str, Any] | None:
        """沿用单工作槽语义领取最早的 Listing Analysis 任务。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT queued.id, queued.job_id
                FROM seller_sprite_task_queue AS queued
                WHERE queued.queue_scope = ?
                  AND queued.task_kind = ?
                  AND queued.status = 'queued'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS running
                      WHERE running.queue_scope = queued.queue_scope
                        AND running.task_kind = ?
                        AND running.status = 'running'
                  )
                ORDER BY queued.id ASC
                LIMIT 1
                """,
                (queue_scope, TASK_KIND_LISTING_ANALYSIS, TASK_KIND_LISTING_ANALYSIS),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'running',
                    started_at = ?,
                    assigned_account = ?,
                    worker_key = ?,
                    assignment_generation = assignment_generation + 1
                WHERE id = ?
                  AND status = 'queued'
                """,
                (_now_iso(), assigned_account, worker_key, row["id"]),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return None
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

    def finish_task_if_current(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        result_path: str,
        row_count: int,
        export_payload: dict[str, Any] | None,
    ) -> bool:
        """仅允许当前账号和执行代际提交成功结果。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'succeeded',
                    finished_at = ?,
                    result_path = ?,
                    row_count = ?,
                    export_json = ?,
                    error_json = NULL
                WHERE job_id = ?
                  AND status = 'running'
                  AND assigned_account_key = ?
                  AND assignment_generation = ?
                """,
                (
                    _now_iso(),
                    result_path,
                    row_count,
                    json.dumps(export_payload, ensure_ascii=False) if export_payload is not None else None,
                    job_id,
                    account_key,
                    assignment_generation,
                ),
            )
        return int(cursor.rowcount or 0) == 1

    def finish_task_and_mcp_run_if_current(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        result_path: str,
        row_count: int,
        export_payload: dict[str, Any] | None,
        mcp_export_payload: dict[str, Any] | None,
    ) -> bool:
        """以账号和代际 CAS 原子提交队列成功态及可选 MCP 成功态。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'succeeded', finished_at = ?, result_path = ?,
                    row_count = ?, export_json = ?, error_json = NULL
                WHERE job_id = ? AND status = 'running'
                  AND assigned_account_key = ? AND assignment_generation = ?
                """,
                (
                    now,
                    result_path,
                    row_count,
                    json.dumps(export_payload, ensure_ascii=False)
                    if export_payload is not None
                    else None,
                    job_id,
                    account_key,
                    assignment_generation,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return False
            if mcp_export_payload is not None:
                mcp_cursor = conn.execute(
                    """
                    UPDATE seller_sprite_mcp_runs
                    SET result_state = 'succeeded', result_row_count = ?,
                        result_export_format = ?, result_export_filename = ?,
                        result_export_job_id = ?, error_json = NULL,
                        finished_at = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        row_count,
                        mcp_export_payload.get("format"),
                        mcp_export_payload.get("filename"),
                        job_id,
                        now,
                        now,
                        job_id,
                    ),
                )
                if int(mcp_cursor.rowcount or 0) != 1:
                    conn.rollback()
                    raise ValueError(f"MCP 调用记录不存在：{job_id}")
            conn.commit()
        return True

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

    def fail_task_if_current(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        error_payload: dict[str, Any],
    ) -> bool:
        """仅允许当前账号和执行代际标记任务失败。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'failed',
                    finished_at = ?,
                    error_json = ?,
                    last_error_code = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND assigned_account_key = ?
                  AND assignment_generation = ?
                """,
                (
                    _now_iso(),
                    json.dumps(error_payload, ensure_ascii=False),
                    str(error_payload.get("code") or ""),
                    job_id,
                    account_key,
                    assignment_generation,
                ),
            )
        return int(cursor.rowcount or 0) == 1

    def fail_task_and_mcp_run_if_current(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        error_payload: dict[str, Any],
        update_mcp_run: bool,
    ) -> bool:
        """以账号和代际 CAS 原子提交队列失败态及可选 MCP 失败态。"""
        now = _now_iso()
        error_json = json.dumps(error_payload, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'failed', finished_at = ?, error_json = ?,
                    last_error_code = ?
                WHERE job_id = ? AND status = 'running'
                  AND assigned_account_key = ? AND assignment_generation = ?
                """,
                (
                    now,
                    error_json,
                    str(error_payload.get("code") or ""),
                    job_id,
                    account_key,
                    assignment_generation,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return False
            if update_mcp_run:
                mcp_cursor = conn.execute(
                    """
                    UPDATE seller_sprite_mcp_runs
                    SET result_state = 'failed', error_json = ?,
                        finished_at = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (error_json, now, now, job_id),
                )
                if int(mcp_cursor.rowcount or 0) != 1:
                    conn.rollback()
                    raise ValueError(f"MCP 调用记录不存在：{job_id}")
            conn.commit()
        return True

    def reassign_task_for_failover(
        self,
        *,
        job_id: str,
        current_account_key: str,
        current_generation: int,
        replacement_account_key: str,
        replacement_account: str,
        worker_key: str,
        error_code: str,
        retry_reason: str,
    ) -> dict[str, Any] | None:
        """使用 CAS 将运行任务改绑到尚未占用的备用账号。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """
                SELECT queue_scope, task_kind
                FROM seller_sprite_task_queue
                WHERE job_id = ?
                  AND status = 'running'
                  AND assigned_account_key = ?
                  AND assignment_generation = ?
                """,
                (job_id, current_account_key, current_generation),
            ).fetchone()
            if current is None:
                conn.commit()
                return None
            occupied = conn.execute(
                """
                SELECT 1
                FROM seller_sprite_task_queue
                WHERE queue_scope = ?
                  AND status = 'running'
                  AND assigned_account_key = ?
                  AND job_id <> ?
                LIMIT 1
                """,
                (current["queue_scope"], replacement_account_key, job_id),
            ).fetchone()
            if occupied is not None:
                conn.commit()
                return None
            try:
                cursor = conn.execute(
                    """
                    UPDATE seller_sprite_task_queue
                    SET assigned_account = ?,
                        assigned_account_key = ?,
                        worker_key = ?,
                        assignment_generation = assignment_generation + 1,
                        failover_count = failover_count + 1,
                        last_error_code = ?,
                        last_failed_account_key = ?,
                        retry_reason = ?
                    WHERE job_id = ?
                      AND status = 'running'
                      AND assigned_account_key = ?
                      AND assignment_generation = ?
                    """,
                    (
                        replacement_account,
                        replacement_account_key,
                        worker_key,
                        error_code,
                        current_account_key,
                        retry_reason,
                        job_id,
                        current_account_key,
                        current_generation,
                    ),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return None
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return None
            conn.commit()
        return self.get_status(job_id)

    def reset_running_tasks(self, *, before_started_at: str | None = None) -> int:
        """将异常中断留下的运行中任务重新放回队列。"""
        where = "status = 'running'"
        params: list[Any] = []
        if before_started_at:
            where += " AND started_at IS NOT NULL AND started_at <= ?"
            params.append(before_started_at)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE seller_sprite_task_queue
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    assigned_account = NULL,
                    assigned_account_key = NULL,
                    worker_key = NULL,
                    assignment_generation = assignment_generation + 1,
                    last_error_code = NULL,
                    last_failed_account_key = NULL,
                    retry_reason = NULL
                WHERE {where}
                """,
                params,
            )
            return int(cursor.rowcount or 0)

    def list_tasks(self, *, state: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """按状态列出最近任务，用于队列运维排查。"""
        safe_limit = max(1, min(int(limit), 500))
        params: list[Any] = []
        where = ""
        if state:
            where = "WHERE status = ?"
            params.append(state)
        params.append(safe_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, job_id, queue_scope, task_kind, status, request_json, root_dir,
                       created_at, started_at, finished_at, assigned_account,
                       assigned_account_key, worker_key, assignment_generation,
                       failover_count, last_error_code, last_failed_account_key,
                       retry_reason, result_path, row_count, export_json, error_json
                FROM seller_sprite_task_queue
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_status(row) for row in rows]

    def queue_status(self, *, stale_running_seconds: int = 1800) -> dict[str, Any]:
        """返回队列状态摘要，辅助判断 queued 是否堆积。"""
        stale_cutoff = _seconds_ago_iso(max(0, int(stale_running_seconds)))
        with self._connect() as conn:
            count_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM seller_sprite_task_queue
                GROUP BY status
                """
            ).fetchall()
            oldest_queued = conn.execute(
                """
                SELECT MIN(created_at) AS value
                FROM seller_sprite_task_queue
                WHERE status = 'queued'
                """
            ).fetchone()
            oldest_running = conn.execute(
                """
                SELECT MIN(started_at) AS value
                FROM seller_sprite_task_queue
                WHERE status = 'running'
                """
            ).fetchone()
            stale_running = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM seller_sprite_task_queue
                WHERE status = 'running'
                  AND started_at IS NOT NULL
                  AND started_at <= ?
                """,
                (stale_cutoff,),
            ).fetchone()
        by_state = {str(row["status"]): int(row["cnt"] or 0) for row in count_rows}
        return {
            "db_path": str(self.db_path),
            "total": sum(by_state.values()),
            "by_state": by_state,
            "oldest_queued_at": oldest_queued["value"] if oldest_queued else None,
            "oldest_running_started_at": oldest_running["value"] if oldest_running else None,
            "stale_running_count": int(stale_running["cnt"] or 0) if stale_running else 0,
            "stale_running_cutoff": stale_cutoff,
        }

    def fail_tasks(
        self,
        *,
        state: str = "queued",
        job_ids: list[str] | None = None,
        before: str | None = None,
        reason: str = "人工终止队列任务",
    ) -> int:
        """将匹配任务批量标记为 failed，并同步 MCP 调用记录。"""
        where = ["status = ?"]
        params: list[Any] = [state]
        if before:
            where.append("created_at <= ?")
            params.append(before)
        if job_ids:
            placeholders = ", ".join("?" for _ in job_ids)
            where.append(f"job_id IN ({placeholders})")
            params.extend(job_ids)

        error_payload = {
            "code": "SELLER_SPRITE_QUEUE_ABORTED",
            "message": reason,
        }
        error_json = json.dumps(error_payload, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"""
                SELECT job_id
                FROM seller_sprite_task_queue
                WHERE {' AND '.join(where)}
                """,
                params,
            ).fetchall()
            matched_job_ids = [str(row["job_id"]) for row in rows]
            if not matched_job_ids:
                conn.commit()
                return 0

            job_placeholders = ", ".join("?" for _ in matched_job_ids)
            now = _now_iso()
            conn.execute(
                f"""
                UPDATE seller_sprite_task_queue
                SET status = 'failed',
                    finished_at = ?,
                    error_json = ?
                WHERE job_id IN ({job_placeholders})
                """,
                [now, error_json, *matched_job_ids],
            )
            conn.execute(
                f"""
                UPDATE seller_sprite_mcp_runs
                SET result_state = 'failed',
                    error_json = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE job_id IN ({job_placeholders})
                """,
                [error_json, now, now, *matched_job_ids],
            )
            conn.commit()
        return len(matched_job_ids)

    def get_status(self, job_id: str) -> dict[str, Any]:
        """读取任务当前状态。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, job_id, queue_scope, task_kind, status, request_json, root_dir,
                       created_at, started_at, finished_at, assigned_account,
                       assigned_account_key, worker_key, assignment_generation,
                       failover_count, last_error_code, last_failed_account_key,
                       retry_reason, result_path, row_count, export_json, error_json
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

    def create_mcp_run(
        self,
        request: SellerSpriteScenarioRequest,
        user_email: str,
    ) -> dict[str, Any]:
        """创建一条 MCP 调用记录并返回初始状态。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seller_sprite_mcp_runs (
                    job_id, user_email, scenario, mode, params_json,
                    result_state, result_row_count, result_export_format,
                    result_export_filename, result_export_job_id, error_json,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', 0, NULL, NULL, NULL, NULL, ?, NULL, NULL, ?)
                """,
                (
                    request.job_id,
                    user_email,
                    request.scenario,
                    DEFAULT_MCP_RUN_MODE,
                    json.dumps(request.params, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_mcp_run(str(request.job_id))

    def get_mcp_run(self, job_id: str) -> dict[str, Any]:
        """读取 MCP 调用记录。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, user_email, scenario, mode, params_json,
                       result_state, result_row_count, result_export_format,
                       result_export_filename, result_export_job_id, error_json,
                       created_at, started_at, finished_at, updated_at
                FROM seller_sprite_mcp_runs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"MCP 调用记录不存在：{job_id}")
        return self._row_to_mcp_run(row)

    def mark_mcp_run_running(self, job_id: str) -> None:
        """将 MCP 调用记录标记为运行中。"""
        now = _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_mcp_runs
                SET result_state = 'running',
                    started_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (now, now, job_id),
            )
        if int(cursor.rowcount or 0) != 1:
            raise ValueError(f"MCP 调用记录不存在：{job_id}")

    def finish_mcp_run_success(
        self,
        job_id: str,
        row_count: int,
        export_payload: dict[str, Any],
    ) -> None:
        """将 MCP 调用记录标记为成功完成。"""
        now = _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_mcp_runs
                SET result_state = 'succeeded',
                    result_row_count = ?,
                    result_export_format = ?,
                    result_export_filename = ?,
                    result_export_job_id = ?,
                    error_json = NULL,
                    finished_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    row_count,
                    export_payload.get("format"),
                    export_payload.get("filename"),
                    job_id,
                    now,
                    now,
                    job_id,
                ),
            )
        if int(cursor.rowcount or 0) != 1:
            raise ValueError(f"MCP 调用记录不存在：{job_id}")

    def finish_mcp_run_failed(self, job_id: str, error_payload: dict[str, Any]) -> None:
        """将 MCP 调用记录标记为失败。"""
        now = _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_mcp_runs
                SET result_state = 'failed',
                    error_json = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    json.dumps(error_payload, ensure_ascii=False),
                    now,
                    now,
                    job_id,
                ),
            )
        if int(cursor.rowcount or 0) != 1:
            raise ValueError(f"MCP 调用记录不存在：{job_id}")

    def record_account_event(
        self,
        *,
        event_type: str,
        account_key: str | None,
        account_name: str | None,
        masked_username: str | None,
        job_id: str | None,
        worker_key: str | None,
        assignment_generation: int | None,
        execution_mode: str | None,
        login_stage: str | None,
        error_code: str | None,
        error_summary: str | None,
        replacement_account_key: str | None,
        duration_ms: int | None,
        failover_count: int | None,
        next_action: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        """写入一条脱敏账号登录或故障审计事件。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seller_sprite_account_events (
                    created_at, event_type, account_key, account_name,
                    masked_username, job_id, worker_key, assignment_generation,
                    execution_mode, login_stage, error_code, error_summary,
                    replacement_account_key, duration_ms, failover_count,
                    next_action, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    event_type,
                    account_key,
                    account_name,
                    masked_username,
                    job_id,
                    worker_key,
                    assignment_generation,
                    execution_mode,
                    login_stage,
                    error_code,
                    error_summary,
                    replacement_account_key,
                    duration_ms,
                    failover_count,
                    next_action,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )

    def list_account_events(self, *, job_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """按时间倒序查询脱敏账号事件。"""
        safe_limit = max(1, min(int(limit), 500))
        where = "WHERE job_id = ?" if job_id else ""
        params: list[Any] = [job_id] if job_id else []
        params.append(safe_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT created_at, event_type, account_key, account_name,
                       masked_username, job_id, worker_key, assignment_generation,
                       execution_mode, login_stage, error_code, error_summary,
                       replacement_account_key, duration_ms, failover_count,
                       next_action, metadata_json
                FROM seller_sprite_account_events
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_account_event_to_dict(row) for row in rows]

    def _ensure_schema(self) -> None:
        """在单个立即事务内初始化或升级 SQLite 表结构。"""
        with self._connect() as conn:
            # DDL、历史数据回填和索引发布必须同成同败，避免并发启动看到半迁移结构。
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    queue_scope TEXT NOT NULL,
                    task_kind TEXT NOT NULL DEFAULT 'generic',
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    root_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT NULL,
                    finished_at TEXT NULL,
                    assigned_account TEXT NULL,
                    assigned_account_key TEXT NULL,
                    worker_key TEXT NULL,
                    assignment_generation INTEGER NOT NULL DEFAULT 0,
                    failover_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT NULL,
                    last_failed_account_key TEXT NULL,
                    retry_reason TEXT NULL,
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
            if "task_kind" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN task_kind TEXT NOT NULL DEFAULT 'generic'"
                )
            if "assigned_account_key" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN assigned_account_key TEXT NULL")
            if "assignment_generation" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN assignment_generation INTEGER NOT NULL DEFAULT 0"
                )
            if "failover_count" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN failover_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_error_code" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN last_error_code TEXT NULL")
            if "last_failed_account_key" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN last_failed_account_key TEXT NULL")
            if "retry_reason" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN retry_reason TEXT NULL")
            self._backfill_task_kinds(conn)
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_seller_sprite_running_account
                ON seller_sprite_task_queue(queue_scope, assigned_account_key)
                WHERE status = 'running' AND assigned_account_key IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_mcp_runs (
                    job_id TEXT NOT NULL PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    result_state TEXT NOT NULL,
                    result_row_count INTEGER NOT NULL DEFAULT 0,
                    result_export_format TEXT NULL,
                    result_export_filename TEXT NULL,
                    result_export_job_id TEXT NULL,
                    error_json TEXT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT NULL,
                    finished_at TEXT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            mcp_columns = {row[1] for row in conn.execute("PRAGMA table_info(seller_sprite_mcp_runs)")}
            if "result_row_count" not in mcp_columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_mcp_runs ADD COLUMN result_row_count INTEGER NOT NULL DEFAULT 0"
                )
            if "result_export_format" not in mcp_columns:
                conn.execute("ALTER TABLE seller_sprite_mcp_runs ADD COLUMN result_export_format TEXT NULL")
            if "result_export_filename" not in mcp_columns:
                conn.execute("ALTER TABLE seller_sprite_mcp_runs ADD COLUMN result_export_filename TEXT NULL")
            if "result_export_job_id" not in mcp_columns:
                conn.execute("ALTER TABLE seller_sprite_mcp_runs ADD COLUMN result_export_job_id TEXT NULL")
            if "error_json" not in mcp_columns:
                conn.execute("ALTER TABLE seller_sprite_mcp_runs ADD COLUMN error_json TEXT NULL")
            if "started_at" not in mcp_columns:
                conn.execute("ALTER TABLE seller_sprite_mcp_runs ADD COLUMN started_at TEXT NULL")
            if "finished_at" not in mcp_columns:
                conn.execute("ALTER TABLE seller_sprite_mcp_runs ADD COLUMN finished_at TEXT NULL")
            if "updated_at" not in mcp_columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_mcp_runs ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_account_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    account_key TEXT NULL,
                    account_name TEXT NULL,
                    masked_username TEXT NULL,
                    job_id TEXT NULL,
                    worker_key TEXT NULL,
                    assignment_generation INTEGER NULL,
                    execution_mode TEXT NULL,
                    login_stage TEXT NULL,
                    error_code TEXT NULL,
                    error_summary TEXT NULL,
                    replacement_account_key TEXT NULL,
                    duration_ms INTEGER NULL,
                    failover_count INTEGER NULL,
                    next_action TEXT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_account_events_created_at "
                "ON seller_sprite_account_events(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_account_events_job_id "
                "ON seller_sprite_account_events(job_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_account_events_account_key "
                "ON seller_sprite_account_events(account_key, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_account_events_event_type "
                "ON seller_sprite_account_events(event_type, created_at)"
            )
            conn.execute(f"PRAGMA user_version = {QUEUE_SCHEMA_VERSION}")
            conn.commit()

    def _backfill_task_kinds(self, conn: sqlite3.Connection) -> None:
        """根据历史请求内容回填任务类型，并隔离无法解析的排队行。"""
        rows = conn.execute(
            "SELECT id, status, request_json FROM seller_sprite_task_queue"
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["request_json"]))
                scenario = str(payload.get("scenario") or "").strip().lower()
            except (json.JSONDecodeError, AttributeError):
                if str(row["status"]) == "queued":
                    error = {
                        "code": "SELLER_SPRITE_QUEUE_MIGRATION_ERROR",
                        "message": "历史任务 request_json 无法解析，不能安全迁移任务类型",
                    }
                    conn.execute(
                        "UPDATE seller_sprite_task_queue SET status = 'failed', finished_at = ?, error_json = ? WHERE id = ?",
                        (_now_iso(), json.dumps(error, ensure_ascii=False), row["id"]),
                    )
                continue
            task_kind = (
                TASK_KIND_LISTING_ANALYSIS
                if scenario == "listing-analysis"
                else TASK_KIND_GENERIC
            )
            conn.execute(
                "UPDATE seller_sprite_task_queue SET task_kind = ? WHERE id = ?",
                (task_kind, row["id"]),
            )

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
            "task_kind": row["task_kind"],
            "assigned_account": row["assigned_account"],
            "worker_key": row["worker_key"],
            "assignment_generation": int(row["assignment_generation"] or 0),
            "failover_count": int(row["failover_count"] or 0),
            "last_error_code": row["last_error_code"],
            "retry_reason": row["retry_reason"],
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
                SELECT queue_scope, task_kind
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
                  AND task_kind = ?
                  AND status = 'queued'
                  AND id <= ?
                """,
                (row["queue_scope"], row["task_kind"], task_id),
            ).fetchone()
        return int(count_row["cnt"] or 0)

    def _row_to_mcp_run(self, row: sqlite3.Row) -> dict[str, Any]:
        """将 MCP 运行记录转换为外部可读结构。"""
        return {
            "job_id": str(row["job_id"]),
            "user_email": str(row["user_email"]),
            "scenario": str(row["scenario"]),
            "mode": row["mode"],
            "params_json": json.loads(str(row["params_json"])),
            "result_state": str(row["result_state"]),
            "result_row_count": int(row["result_row_count"] or 0),
            "result_export_format": row["result_export_format"],
            "result_export_filename": row["result_export_filename"],
            "result_export_job_id": row["result_export_job_id"],
            "error_json": json.loads(str(row["error_json"])) if row["error_json"] else None,
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "updated_at": row["updated_at"],
        }


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


def _seconds_ago_iso(seconds: int) -> str:
    """返回当前时间向前偏移指定秒数后的本地 ISO 字符串。"""
    return (datetime.now(timezone.utc).astimezone() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _task_kind_for_request(request: SellerSpriteScenarioRequest) -> str:
    """根据规范化场景返回不可伪造的任务类型。"""
    return (
        TASK_KIND_LISTING_ANALYSIS
        if request.scenario.strip().lower() == "listing-analysis"
        else TASK_KIND_GENERIC
    )


def _account_event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """将账号审计行转换为可查询的脱敏结构。"""
    return {
        "created_at": row["created_at"],
        "event_type": row["event_type"],
        "account_key": row["account_key"],
        "account_name": row["account_name"],
        "masked_username": row["masked_username"],
        "job_id": row["job_id"],
        "worker_key": row["worker_key"],
        "assignment_generation": row["assignment_generation"],
        "execution_mode": row["execution_mode"],
        "login_stage": row["login_stage"],
        "error_code": row["error_code"],
        "error_summary": row["error_summary"],
        "replacement_account_key": row["replacement_account_key"],
        "duration_ms": row["duration_ms"],
        "failover_count": row["failover_count"],
        "next_action": row["next_action"],
        "metadata": json.loads(str(row["metadata_json"] or "{}")),
    }
