"""卖家精灵 SQLite 任务队列仓储。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from opscli.seller_sprite.config import resolve_queue_db_path
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest


DEFAULT_MCP_RUN_MODE = "browser-route"
TASK_KIND_GENERIC = "generic"
TASK_KIND_LISTING_ANALYSIS = "listing_analysis"
ACCOUNT_ROUTE_SHARED_POOL = "shared_pool"
ACCOUNT_ROUTE_USER_BINDING = "user_binding"
# 版本 8 增加成功事件单调序号，保证数据沉淀对账不受任务乱序完成影响。
QUEUE_SCHEMA_VERSION = 8
TASK_PROGRESS_STAGES = {
    "claimed",
    "resolving",
    "requesting",
    "browser_wait",
    "remote_poll",
    "processing",
    "exporting",
    "uploading",
    "finalizing",
    "succeeded",
    "failed",
    "queued",
    "reassigned",
}
TASK_PROGRESS_METADATA_FIELDS = (
    "poll_attempt",
    "poll_total",
    "poll_status",
    "outcome",
)
TASK_PROGRESS_POLL_STATUSES = {
    "PENDING",
    "SUBMITTED",
    "RUNNING",
    "PROCESSING",
    "COMPLETED",
    "COMPLETE",
    "SUCCESS",
    "SUCCEEDED",
    "FINISHED",
    "DONE",
    "FAILED",
    "FAIL",
    "ERROR",
    "CANCELED",
    "CANCELLED",
    "EXPIRED",
}
TASK_PROGRESS_OUTCOMES = {
    "queued",
    "reassigned",
    "succeeded",
    "failed",
}


@dataclass(frozen=True)
class FailoverReassignmentResult:
    """描述故障接替 CAS 的明确结果，避免混淆账号冲突与旧代际。"""

    outcome: Literal["reassigned", "replacement_busy", "stale_attempt"]
    status: dict[str, Any] | None = None


class SellerSpriteTaskQueueStore:
    """管理卖家精灵任务队列的本地 SQLite 仓储。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else resolve_queue_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def enqueue(
        self,
        *,
        request: SellerSpriteScenarioRequest,
        queue_scope: str,
        root_dir: Path,
        credential_scope: str | None = None,
        runtime_auth_required: bool = False,
        expected_user_email: str | None = None,
        account_route: str = ACCOUNT_ROUTE_SHARED_POOL,
        requested_account_id: str | None = None,
        requested_account_key: str | None = None,
    ) -> dict[str, Any]:
        """写入一条排队任务并返回当前排队状态。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seller_sprite_task_queue (
                    job_id, queue_scope, task_kind, status, request_json, root_dir,
                    created_at, started_at, finished_at, assigned_account,
                    worker_key, result_path, row_count, export_json, error_json,
                    credential_scope, runtime_auth_required, expected_user_email,
                    account_route, requested_account_id, requested_account_key,
                    session_id, jwt, progress_stage, progress_at, progress_sequence
                )
                VALUES (?, ?, ?, 'queued', ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, ?, ?, ?, ?, ?, ?, NULL, NULL, 'queued', ?, 0)
                """,
                (
                    request.job_id,
                    queue_scope,
                    _task_kind_for_request(request),
                    json.dumps(request.to_dict(), ensure_ascii=False),
                    str(root_dir),
                    now,
                    credential_scope,
                    int(runtime_auth_required),
                    expected_user_email,
                    account_route,
                    requested_account_id,
                    requested_account_key,
                    now,
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
        credential_scope: str | None = None,
        expected_user_email: str | None = None,
        account_route: str = ACCOUNT_ROUTE_SHARED_POOL,
        requested_account_id: str | None = None,
        requested_account_key: str | None = None,
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
                    credential_scope, runtime_auth_required, expected_user_email,
                    account_route, requested_account_id, requested_account_key,
                    session_id, jwt, progress_stage, progress_at, progress_sequence
                )
                VALUES (?, ?, ?, 'queued', ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, ?, 0, ?, ?, ?, ?, NULL, NULL, 'queued', ?, 0)
                """,
                (
                    request.job_id,
                    queue_scope,
                    _task_kind_for_request(request),
                    json.dumps(request.to_dict(), ensure_ascii=False),
                    str(root_dir),
                    now,
                    credential_scope,
                    expected_user_email or user_email,
                    account_route,
                    requested_account_id,
                    requested_account_key,
                    now,
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

    def enqueue_cached_owned_mcp_run(
        self,
        *,
        request: SellerSpriteScenarioRequest,
        queue_scope: str,
        root_dir: Path,
        user_email: str,
        source_job_id: str,
        row_count: int,
        export_payload: dict[str, Any] | None,
        account_route: str = ACCOUNT_ROUTE_SHARED_POOL,
        requested_account_id: str | None = None,
        requested_account_key: str | None = None,
    ) -> dict[str, Any]:
        """原子创建当前用户拥有的缓存成功任务，不发布 Worker 成功事件。"""
        now = _now_iso()
        export_json = (
            json.dumps(export_payload, ensure_ascii=False)
            if export_payload is not None
            else None
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO seller_sprite_task_queue (
                    job_id, queue_scope, task_kind, status, request_json, root_dir,
                    created_at, started_at, finished_at, assigned_account,
                    worker_key, result_path, row_count, export_json, error_json,
                    credential_scope, runtime_auth_required, expected_user_email,
                    account_route, requested_account_id, requested_account_key,
                    session_id, jwt, progress_stage, progress_at, progress_sequence
                )
                VALUES (?, ?, ?, 'succeeded', ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?,
                        NULL, NULL, 0, NULL, ?, ?, ?, NULL, NULL, 'succeeded', ?, 1)
                """,
                (
                    request.job_id,
                    queue_scope,
                    _task_kind_for_request(request),
                    json.dumps(request.to_dict(), ensure_ascii=False),
                    str(root_dir),
                    now,
                    now,
                    now,
                    max(0, int(row_count)),
                    export_json,
                    account_route,
                    requested_account_id,
                    requested_account_key,
                    now,
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
                VALUES (?, ?, ?, 'cache', ?, 'succeeded', ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    request.job_id,
                    user_email,
                    request.scenario,
                    json.dumps(request.params, ensure_ascii=False),
                    max(0, int(row_count)),
                    (export_payload or {}).get("format"),
                    (export_payload or {}).get("filename"),
                    source_job_id,
                    now,
                    now,
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
        account_key: str | None = None,
        execution_owner: str | None = None,
        lease_seconds: float = 60.0,
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
                  AND queued.account_route = 'shared_pool'
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
                    assigned_account_key = ?,
                    worker_key = ?,
                    assignment_generation = assignment_generation + 1,
                    execution_owner = ?,
                    heartbeat_at = ?,
                    lease_expires_at = ?
                WHERE id = ?
                """,
                (
                    _now_iso(),
                    assigned_account,
                    account_key,
                    worker_key,
                    _claim_owner(execution_owner, worker_key),
                    _now_iso(),
                    _future_iso(lease_seconds),
                    row["id"],
                ),
            )
            self._record_claim_progress(conn, int(row["id"]))
            claimed = self._status_from_connection(conn, str(row["job_id"]))
            conn.commit()
        return claimed

    def claim_next_generic_for_account(
        self,
        *,
        queue_scope: str,
        account_key: str,
        assigned_account: str,
        worker_key: str,
        execution_owner: str | None = None,
        lease_seconds: float = 60.0,
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
                  AND queued.account_route = 'shared_pool'
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
                        assignment_generation = assignment_generation + 1,
                        execution_owner = ?,
                        heartbeat_at = ?,
                        lease_expires_at = ?
                    WHERE id = ?
                      AND status = 'queued'
                    """,
                    (
                        _now_iso(),
                        assigned_account,
                        account_key,
                        worker_key,
                        _claim_owner(execution_owner, worker_key),
                        _now_iso(),
                        _future_iso(lease_seconds),
                        row["id"],
                    ),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return None
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return None
            self._record_claim_progress(conn, int(row["id"]))
            claimed = self._status_from_connection(conn, str(row["job_id"]))
            conn.commit()
        return claimed

    def claim_next_listing_analysis(
        self,
        *,
        queue_scope: str,
        worker_key: str,
        assigned_account: str,
        account_key: str,
        execution_owner: str | None = None,
        lease_seconds: float = 60.0,
    ) -> dict[str, Any] | None:
        """使用明确账号领取最早的 Listing Analysis 任务。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT queued.id, queued.job_id
                FROM seller_sprite_task_queue AS queued
                WHERE queued.queue_scope = ?
                  AND queued.task_kind = ?
                  AND queued.status = 'queued'
                  AND queued.account_route = 'shared_pool'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS running
                      WHERE running.queue_scope = queued.queue_scope
                        AND running.task_kind = ?
                        AND running.status = 'running'
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS account_running
                      WHERE account_running.queue_scope = queued.queue_scope
                        AND account_running.status = 'running'
                        AND account_running.assigned_account_key = ?
                  )
                ORDER BY queued.id ASC
                LIMIT 1
                """,
                (
                    queue_scope,
                    TASK_KIND_LISTING_ANALYSIS,
                    TASK_KIND_LISTING_ANALYSIS,
                    account_key,
                ),
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
                    assigned_account_key = ?,
                    worker_key = ?,
                    assignment_generation = assignment_generation + 1,
                    execution_owner = ?,
                    heartbeat_at = ?,
                    lease_expires_at = ?
                WHERE id = ?
                  AND status = 'queued'
                """,
                (
                    _now_iso(),
                    assigned_account,
                    account_key,
                    worker_key,
                    _claim_owner(execution_owner, worker_key),
                    _now_iso(),
                    _future_iso(lease_seconds),
                    row["id"],
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return None
            self._record_claim_progress(conn, int(row["id"]))
            claimed = self._status_from_connection(conn, str(row["job_id"]))
            conn.commit()
        return claimed

    def next_user_binding_candidate(self, *, queue_scope: str) -> dict[str, Any] | None:
        """读取最早且其专属账号当前未被占用的待执行任务引用。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, task_kind, expected_user_email,
                       requested_account_id, requested_account_key
                FROM seller_sprite_task_queue AS queued
                WHERE queue_scope = ?
                  AND status = 'queued'
                  AND account_route = 'user_binding'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM seller_sprite_task_queue AS running
                      WHERE running.queue_scope = queued.queue_scope
                        AND running.status = 'running'
                        AND running.assigned_account_key = queued.requested_account_key
                  )
                ORDER BY id ASC
                LIMIT 1
                """,
                (queue_scope,),
            ).fetchone()
        return dict(row) if row is not None else None

    def claim_user_binding_task(
        self,
        *,
        job_id: str,
        account_id: str,
        account_key: str,
        assigned_account: str,
        worker_key: str,
        max_active_tasks: int = 3,
        execution_owner: str | None = None,
        lease_seconds: float = 60.0,
    ) -> dict[str, Any] | None:
        """按提交时账号引用原子领取一条专属账号任务。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    """
                    UPDATE seller_sprite_task_queue
                    SET status = 'running', started_at = ?,
                        assigned_account = ?, assigned_account_key = ?,
                        worker_key = ?, assignment_generation = assignment_generation + 1,
                        execution_owner = ?, heartbeat_at = ?, lease_expires_at = ?
                    WHERE job_id = ?
                      AND status = 'queued'
                      AND account_route = 'user_binding'
                      AND requested_account_id = ?
                      AND requested_account_key = ?
                      AND (
                          SELECT COUNT(*)
                          FROM seller_sprite_task_queue AS dedicated_running
                          WHERE dedicated_running.queue_scope = seller_sprite_task_queue.queue_scope
                            AND dedicated_running.status = 'running'
                            AND dedicated_running.account_route = 'user_binding'
                      ) < ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM seller_sprite_task_queue AS running
                          WHERE running.queue_scope = seller_sprite_task_queue.queue_scope
                            AND running.status = 'running'
                            AND running.assigned_account_key = ?
                      )
                    """,
                    (
                        _now_iso(),
                        assigned_account,
                        account_key,
                        worker_key,
                        _claim_owner(execution_owner, worker_key),
                        _now_iso(),
                        _future_iso(lease_seconds),
                        job_id,
                        account_id,
                        account_key,
                        max(1, int(max_active_tasks)),
                        account_key,
                    ),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return None
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return None
            row = conn.execute(
                "SELECT id FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            self._record_claim_progress(conn, int(row["id"]))
            claimed = self._status_from_connection(conn, job_id)
            conn.commit()
        return claimed

    def fail_queued_user_binding_task(
        self,
        *,
        job_id: str,
        reason: str,
    ) -> bool:
        """把无法恢复绑定的单条排队专属任务标记为失败。"""
        return self._fail_queued_user_binding_tasks(
            where="job_id = ?",
            params=[job_id],
            reason=reason,
        ) == 1

    def fail_queued_user_binding_tasks(
        self,
        *,
        user_email: str,
        reason: str,
    ) -> int:
        """解除绑定后失败该用户所有尚未领取的专属账号任务。"""
        return self._fail_queued_user_binding_tasks(
            where="LOWER(expected_user_email) = LOWER(?)",
            params=[user_email.strip()],
            reason=reason,
        )

    def _fail_queued_user_binding_tasks(
        self,
        *,
        where: str,
        params: list[Any],
        reason: str,
    ) -> int:
        """原子结束匹配的排队专属任务及 MCP 所有权记录。"""
        error_payload = {
            "code": "SELLER_SPRITE_DEDICATED_ACCOUNT_UNAVAILABLE",
            "message": reason,
        }
        error_json = json.dumps(error_payload, ensure_ascii=False)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"""
                SELECT job_id
                FROM seller_sprite_task_queue
                WHERE status = 'queued'
                  AND account_route = 'user_binding'
                  AND {where}
                """,
                params,
            ).fetchall()
            job_ids = [str(row["job_id"]) for row in rows]
            if not job_ids:
                conn.commit()
                return 0
            placeholders = ", ".join("?" for _ in job_ids)
            conn.execute(
                f"""
                UPDATE seller_sprite_task_queue
                SET status = 'failed', finished_at = ?, error_json = ?,
                    credential_scope = NULL, runtime_auth_required = 0,
                    expected_user_email = NULL, session_id = NULL, jwt = NULL,
                    progress_stage = 'failed', progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id IN ({placeholders})
                """,
                [now, error_json, now, *job_ids],
            )
            conn.execute(
                f"""
                UPDATE seller_sprite_mcp_runs
                SET result_state = 'failed', error_json = ?,
                    finished_at = ?, updated_at = ?
                WHERE job_id IN ({placeholders})
                """,
                [error_json, now, now, *job_ids],
            )
            for job_id in job_ids:
                self._append_current_progress_event(
                    conn,
                    job_id=job_id,
                    stage="failed",
                    progress_at=now,
                    metadata={"outcome": "failed"},
                )
            conn.commit()
        return len(job_ids)

    def finish_task(
        self,
        *,
        job_id: str,
        result_path: str,
        row_count: int,
        export_payload: dict[str, Any] | None,
    ) -> None:
        """标记任务成功完成，并原子追加脱敏终态时间线。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT status FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'succeeded',
                    finished_at = ?,
                    result_path = ?,
                    row_count = ?,
                    export_json = ?,
                    error_json = NULL,
                    credential_scope = NULL,
                    runtime_auth_required = 0,
                    expected_user_email = NULL,
                    session_id = NULL,
                    jwt = NULL,
                    execution_owner = NULL,
                    heartbeat_at = NULL,
                    lease_expires_at = NULL,
                    progress_stage = 'succeeded',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ?
                """,
                (
                    now,
                    result_path,
                    row_count,
                    json.dumps(export_payload, ensure_ascii=False) if export_payload is not None else None,
                    now,
                    job_id,
                ),
            )
            if int(cursor.rowcount or 0) == 1:
                if previous is not None and str(previous["status"]) != "succeeded":
                    self._append_collection_success_event(
                        conn,
                        job_id=job_id,
                        succeeded_at=now,
                    )
                self._append_current_progress_event(
                    conn,
                    job_id=job_id,
                    stage="succeeded",
                    progress_at=now,
                    metadata={"outcome": "succeeded"},
                )
            conn.commit()

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
        """仅允许当前账号和执行代际提交成功结果及终态时间线。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'succeeded',
                    finished_at = ?,
                    result_path = ?,
                    row_count = ?,
                    export_json = ?,
                    error_json = NULL,
                    credential_scope = NULL,
                    runtime_auth_required = 0,
                    expected_user_email = NULL,
                    session_id = NULL,
                    jwt = NULL,
                    execution_owner = NULL,
                    heartbeat_at = NULL,
                    lease_expires_at = NULL,
                    progress_stage = 'succeeded',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ?
                  AND status = 'running'
                  AND assigned_account_key = ?
                  AND assignment_generation = ?
                """,
                (
                    now,
                    result_path,
                    row_count,
                    json.dumps(export_payload, ensure_ascii=False) if export_payload is not None else None,
                    now,
                    job_id,
                    account_key,
                    assignment_generation,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return False
            self._append_collection_success_event(
                conn,
                job_id=job_id,
                succeeded_at=now,
            )
            self._append_current_progress_event(
                conn,
                job_id=job_id,
                stage="succeeded",
                progress_at=now,
                metadata={"outcome": "succeeded"},
            )
            conn.commit()
        return True

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
                    row_count = ?, export_json = ?, error_json = NULL,
                    credential_scope = NULL, runtime_auth_required = 0,
                    expected_user_email = NULL, session_id = NULL, jwt = NULL,
                    execution_owner = NULL, heartbeat_at = NULL,
                    lease_expires_at = NULL, progress_stage = 'succeeded',
                    progress_at = ?, progress_sequence = progress_sequence + 1
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
                    now,
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
            self._append_collection_success_event(
                conn,
                job_id=job_id,
                succeeded_at=now,
            )
            self._append_current_progress_event(
                conn,
                job_id=job_id,
                stage="succeeded",
                progress_at=now,
                metadata={"outcome": "succeeded"},
            )
            conn.commit()
        return True

    def fail_task(self, *, job_id: str, error_payload: dict[str, Any]) -> None:
        """标记任务执行失败，并原子追加脱敏终态时间线。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'failed',
                    finished_at = ?,
                    error_json = ?,
                    credential_scope = NULL,
                    runtime_auth_required = 0,
                    expected_user_email = NULL,
                    session_id = NULL,
                    jwt = NULL,
                    execution_owner = NULL,
                    heartbeat_at = NULL,
                    lease_expires_at = NULL,
                    progress_stage = 'failed',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ?
                """,
                (
                    now,
                    json.dumps(error_payload, ensure_ascii=False),
                    now,
                    job_id,
                ),
            )
            if int(cursor.rowcount or 0) == 1:
                self._append_current_progress_event(
                    conn,
                    job_id=job_id,
                    stage="failed",
                    progress_at=now,
                    metadata={"outcome": "failed"},
                )
            conn.commit()

    def fail_queued_task(
        self,
        *,
        job_id: str,
        error_payload: dict[str, Any],
    ) -> bool:
        """仅在任务仍排队时标记失败，避免覆盖并发领取结果。

        参数：
            job_id: 待关闭的任务 ID。
            error_payload: 已脱敏的结构化错误。

        返回：
            当前调用成功关闭排队任务时返回 ``True``；任务已被领取时返回 ``False``。
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'failed',
                    finished_at = ?,
                    error_json = ?,
                    credential_scope = NULL,
                    runtime_auth_required = 0,
                    expected_user_email = NULL,
                    session_id = NULL,
                    jwt = NULL,
                    execution_owner = NULL,
                    heartbeat_at = NULL,
                    lease_expires_at = NULL,
                    progress_stage = 'failed',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ? AND status = 'queued'
                """,
                (
                    now,
                    json.dumps(error_payload, ensure_ascii=False),
                    now,
                    job_id,
                ),
            )
            committed = int(cursor.rowcount or 0) == 1
            if committed:
                self._append_current_progress_event(
                    conn,
                    job_id=job_id,
                    stage="failed",
                    progress_at=now,
                    metadata={"outcome": "failed"},
                )
            conn.commit()
        return committed

    def fail_task_if_current(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        error_payload: dict[str, Any],
    ) -> bool:
        """仅允许当前账号和执行代际标记任务失败及终态时间线。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET status = 'failed',
                    finished_at = ?,
                    error_json = ?,
                    last_error_code = ?,
                    credential_scope = NULL,
                    runtime_auth_required = 0,
                    expected_user_email = NULL,
                    session_id = NULL,
                    jwt = NULL,
                    execution_owner = NULL,
                    heartbeat_at = NULL,
                    lease_expires_at = NULL,
                    progress_stage = 'failed',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ?
                  AND status = 'running'
                  AND assigned_account_key = ?
                  AND assignment_generation = ?
                """,
                (
                    now,
                    json.dumps(error_payload, ensure_ascii=False),
                    str(error_payload.get("code") or ""),
                    now,
                    job_id,
                    account_key,
                    assignment_generation,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return False
            self._append_current_progress_event(
                conn,
                job_id=job_id,
                stage="failed",
                progress_at=now,
                metadata={"outcome": "failed"},
            )
            conn.commit()
        return True

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
                    last_error_code = ?, credential_scope = NULL,
                    runtime_auth_required = 0, expected_user_email = NULL,
                    session_id = NULL, jwt = NULL, execution_owner = NULL,
                    heartbeat_at = NULL, lease_expires_at = NULL,
                    progress_stage = 'failed', progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ? AND status = 'running'
                  AND assigned_account_key = ? AND assignment_generation = ?
                """,
                (
                    now,
                    error_json,
                    str(error_payload.get("code") or ""),
                    now,
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
            self._append_current_progress_event(
                conn,
                job_id=job_id,
                stage="failed",
                progress_at=now,
                metadata={"outcome": "failed"},
            )
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
    ) -> FailoverReassignmentResult:
        """使用 CAS 改绑运行任务，并区分备用冲突和旧代际。"""
        now = _now_iso()
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
                return FailoverReassignmentResult("stale_attempt")
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
                return FailoverReassignmentResult("replacement_busy")
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
                    retry_reason = ?,
                    progress_stage = 'reassigned',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
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
                    now,
                    job_id,
                    current_account_key,
                    current_generation,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return FailoverReassignmentResult("stale_attempt")
            self._append_current_progress_event(
                conn,
                job_id=job_id,
                stage="reassigned",
                progress_at=now,
                metadata={"outcome": "reassigned"},
            )
            status = self._status_from_connection(conn, job_id)
            conn.commit()
        return FailoverReassignmentResult("reassigned", status=status)

    def update_task_progress(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        execution_owner: str,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """仅允许当前执行尝试推进进度，并追加一条脱敏时间线事件。"""
        normalized_stage = str(stage or "").strip().lower()
        if normalized_stage not in TASK_PROGRESS_STAGES:
            raise ValueError(f"不支持的卖家精灵任务进度阶段：{stage}")
        now = _now_iso()
        safe_metadata = _sanitize_task_progress_metadata(metadata)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET progress_stage = ?, progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id = ? AND status = 'running'
                  AND assigned_account_key = ?
                  AND assignment_generation = ?
                  AND execution_owner = ?
                """,
                (
                    normalized_stage,
                    now,
                    job_id,
                    account_key,
                    int(assignment_generation),
                    execution_owner,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                conn.rollback()
                return False
            row = conn.execute(
                """
                SELECT progress_sequence, assignment_generation
                FROM seller_sprite_task_queue
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO seller_sprite_task_progress_events (
                    job_id, progress_stage, progress_at, progress_sequence,
                    assignment_generation, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    normalized_stage,
                    now,
                    int(row["progress_sequence"]),
                    int(row["assignment_generation"]),
                    json.dumps(safe_metadata, ensure_ascii=False),
                ),
            )
            conn.commit()
        return True

    def list_task_progress_events(
        self,
        *,
        job_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按发生顺序返回单个任务的脱敏进度时间线。"""
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT job_id, progress_stage, progress_at, progress_sequence,
                       assignment_generation, metadata_json
                FROM seller_sprite_task_progress_events
                WHERE job_id = ?
                ORDER BY progress_sequence ASC, id ASC
                LIMIT ?
                """,
                (job_id, safe_limit),
            ).fetchall()
        return [_task_progress_event_to_dict(row) for row in rows]

    def renew_execution_leases(
        self,
        *,
        execution_owner: str,
        lease_seconds: float,
    ) -> int:
        """兼容旧调用，续期指定调度器当前持有的全部运行任务。"""
        now = _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET heartbeat_at = ?, lease_expires_at = ?
                WHERE status = 'running' AND execution_owner = ?
                """,
                (now, _future_iso(lease_seconds), execution_owner),
            )
        return int(cursor.rowcount or 0)

    def renew_active_execution_leases(
        self,
        *,
        execution_owner: str,
        attempts: list[dict[str, Any]],
        lease_seconds: float,
    ) -> int:
        """仅续期调度器内存中仍被主动跟踪的执行尝试。"""
        if not attempts:
            return 0
        now = _now_iso()
        lease_expires_at = _future_iso(lease_seconds)
        renewed = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for attempt in attempts:
                cursor = conn.execute(
                    """
                    UPDATE seller_sprite_task_queue
                    SET heartbeat_at = ?, lease_expires_at = ?
                    WHERE job_id = ? AND status = 'running'
                      AND assigned_account_key = ?
                      AND assignment_generation = ?
                      AND execution_owner = ?
                    """,
                    (
                        now,
                        lease_expires_at,
                        str(attempt.get("job_id") or ""),
                        str(attempt.get("account_key") or ""),
                        int(attempt.get("assignment_generation") or 0),
                        execution_owner,
                    ),
                )
                renewed += int(cursor.rowcount or 0)
            conn.commit()
        return renewed

    def running_account_keys(self, *, queue_scope: str) -> set[str]:
        """返回队列范围内所有调度器正在占用的账号键。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT assigned_account_key
                FROM seller_sprite_task_queue
                WHERE queue_scope = ? AND status = 'running'
                  AND assigned_account_key IS NOT NULL
                """,
                (queue_scope,),
            ).fetchall()
        return {
            str(row["assigned_account_key"])
            for row in rows
            if row["assigned_account_key"]
        }

    def publish_runtime_heartbeat(
        self,
        *,
        execution_owner: str,
        lifecycle_state: str,
        generic_workers_alive: int,
        listing_worker_alive: int,
        generic_available_capacity: int,
        listing_available_capacity: int,
        available_capacity: int,
        standby_capacity: int,
        last_claim_at: str | None,
        last_progress_at: str | None,
    ) -> dict[str, Any]:
        """发布调度器运行态快照，不记录账号、请求或文件信息。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seller_sprite_runtime_heartbeats (
                    execution_owner, lifecycle_state, heartbeat_at,
                    generic_workers_alive, listing_worker_alive,
                    generic_available_capacity, listing_available_capacity,
                    available_capacity, standby_capacity,
                    last_claim_at, last_progress_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_owner) DO UPDATE SET
                    lifecycle_state = excluded.lifecycle_state,
                    heartbeat_at = excluded.heartbeat_at,
                    generic_workers_alive = excluded.generic_workers_alive,
                    listing_worker_alive = excluded.listing_worker_alive,
                    generic_available_capacity = excluded.generic_available_capacity,
                    listing_available_capacity = excluded.listing_available_capacity,
                    available_capacity = excluded.available_capacity,
                    standby_capacity = excluded.standby_capacity,
                    last_claim_at = COALESCE(excluded.last_claim_at, last_claim_at),
                    last_progress_at = COALESCE(excluded.last_progress_at, last_progress_at)
                """,
                (
                    execution_owner,
                    str(lifecycle_state or "unknown"),
                    now,
                    max(0, int(generic_workers_alive)),
                    max(0, int(listing_worker_alive)),
                    max(0, int(generic_available_capacity)),
                    max(0, int(listing_available_capacity)),
                    max(0, int(available_capacity)),
                    max(0, int(standby_capacity)),
                    last_claim_at,
                    last_progress_at,
                ),
            )
        return self.get_runtime_heartbeat(execution_owner)

    def mark_runtime_stopped(self, *, execution_owner: str) -> bool:
        """将指定调度器心跳标记为已停止并清空活跃容量。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_runtime_heartbeats
                SET lifecycle_state = 'stopped', heartbeat_at = ?,
                    generic_workers_alive = 0, listing_worker_alive = 0,
                    generic_available_capacity = 0,
                    listing_available_capacity = 0, available_capacity = 0
                WHERE execution_owner = ?
                """,
                (_now_iso(), execution_owner),
            )
        return int(cursor.rowcount or 0) == 1

    def get_runtime_heartbeat(self, execution_owner: str) -> dict[str, Any]:
        """读取指定调度器的脱敏运行态心跳。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT execution_owner, lifecycle_state, heartbeat_at,
                       generic_workers_alive, listing_worker_alive,
                       generic_available_capacity, listing_available_capacity,
                       available_capacity, standby_capacity,
                       last_claim_at, last_progress_at
                FROM seller_sprite_runtime_heartbeats
                WHERE execution_owner = ?
                """,
                (execution_owner,),
            ).fetchone()
        if row is None:
            raise ValueError(f"卖家精灵调度器运行态不存在：{execution_owner}")
        return _runtime_heartbeat_to_dict(row)

    def recover_expired_running_tasks(self) -> int:
        """原子重排历史无租约或租约已过期的运行任务。"""
        now = _now_iso()
        return self._requeue_running_tasks(
            where=(
                "status = 'running' AND (execution_owner IS NULL "
                "OR lease_expires_at IS NULL OR lease_expires_at <= ?)"
            ),
            params=[now],
            retry_reason="lease_expired",
        )

    def release_running_tasks(self, *, execution_owner: str) -> int:
        """在优雅关闭时原子释放当前调度器持有的运行任务。"""
        return self._requeue_running_tasks(
            where="status = 'running' AND execution_owner = ?",
            params=[execution_owner],
            retry_reason="service_restart",
        )

    def reset_running_tasks(self, *, before_started_at: str | None = None) -> int:
        """将人工确认异常中断的运行任务重新放回队列。"""
        where = "status = 'running'"
        params: list[Any] = []
        if before_started_at:
            where += " AND started_at IS NOT NULL AND started_at <= ?"
            params.append(before_started_at)
        return self._requeue_running_tasks(
            where=where,
            params=params,
            retry_reason="manual_requeue",
        )

    def _requeue_running_tasks(
        self,
        *,
        where: str,
        params: list[Any],
        retry_reason: str,
    ) -> int:
        """重排匹配运行任务，并在同一事务中同步 MCP 调用状态。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT job_id FROM seller_sprite_task_queue WHERE {where}",
                params,
            ).fetchall()
            job_ids = [str(row["job_id"]) for row in rows]
            if not job_ids:
                conn.commit()
                return 0
            placeholders = ", ".join("?" for _ in job_ids)
            conn.execute(
                f"""
                UPDATE seller_sprite_task_queue
                SET status = 'queued', started_at = NULL, finished_at = NULL,
                    assigned_account = NULL, assigned_account_key = NULL,
                    worker_key = NULL,
                    assignment_generation = assignment_generation + 1,
                    last_error_code = NULL, last_failed_account_key = NULL,
                    retry_reason = ?, error_json = NULL,
                    execution_owner = NULL, heartbeat_at = NULL,
                    lease_expires_at = NULL, progress_stage = 'queued',
                    progress_at = ?, progress_sequence = progress_sequence + 1
                WHERE job_id IN ({placeholders}) AND status = 'running'
                """,
                [retry_reason, now, *job_ids],
            )
            conn.execute(
                f"""
                UPDATE seller_sprite_mcp_runs
                SET result_state = 'queued', started_at = NULL,
                    finished_at = NULL, error_json = NULL, updated_at = ?
                WHERE job_id IN ({placeholders})
                  AND result_state = 'running'
                """,
                [now, *job_ids],
            )
            for job_id in job_ids:
                self._append_current_progress_event(
                    conn,
                    job_id=job_id,
                    stage="queued",
                    progress_at=now,
                    metadata={"outcome": "queued"},
                )
            conn.commit()
        return len(job_ids)

    def save_listing_analysis_task_id(
        self,
        *,
        job_id: str,
        task_id: str,
        execution_owner: str,
        assignment_generation: int,
    ) -> bool:
        """仅为当前执行代际持久化 Listing Analysis 远端任务标识。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET remote_task_id = ?
                WHERE job_id = ? AND status = 'running'
                  AND execution_owner = ? AND assignment_generation = ?
                """,
                (task_id, job_id, execution_owner, assignment_generation),
            )
        return int(cursor.rowcount or 0) == 1

    def get_listing_analysis_task_id(self, job_id: str) -> str | None:
        """读取 Listing Analysis 已持久化的远端任务标识。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT remote_task_id FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        return str(row["remote_task_id"]) if row["remote_task_id"] else None

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
                       retry_reason, result_path, row_count, export_json, error_json,
                       execution_owner, heartbeat_at, lease_expires_at, remote_task_id,
                       progress_stage, progress_at, progress_sequence
                FROM seller_sprite_task_queue
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_status(row) for row in rows]

    def list_succeeded_for_collection_storage(
        self,
        *,
        cutover_at: str,
        cursor: int,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """按成功事件序号读取 live cutover 之后的成功任务，供 Collector 对账。"""
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT q.id, q.job_id, q.queue_scope, q.task_kind, q.status,
                       q.request_json, q.root_dir, q.created_at, q.started_at,
                       q.finished_at, q.assigned_account, q.assigned_account_key,
                       q.worker_key, q.assignment_generation, q.failover_count,
                       q.last_error_code, q.last_failed_account_key, q.retry_reason,
                       q.result_path, q.row_count, q.export_json, q.error_json,
                       q.execution_owner, q.heartbeat_at, q.lease_expires_at,
                       q.remote_task_id, q.progress_stage, q.progress_at,
                       q.progress_sequence, e.id AS collection_cursor
                FROM seller_sprite_collection_success_events AS e
                JOIN seller_sprite_task_queue AS q ON q.job_id = e.job_id
                WHERE q.status = 'succeeded'
                  AND e.id > ?
                  AND datetime(e.succeeded_at) >= datetime(?)
                ORDER BY e.id ASC
                LIMIT ?
                """,
                (max(0, int(cursor)), cutover_at, safe_limit),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            status = self._row_to_status(row)
            status["collection_cursor"] = int(row["collection_cursor"])
            results.append(status)
        return results

    def list_queued_shared_pool_job_ids(self) -> tuple[str, ...]:
        """列出全部排队中的公共账号池任务。

        返回：
            按入队顺序排列的任务 ID；不包含用户专属账号任务。
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT job_id
                FROM seller_sprite_task_queue
                WHERE status = 'queued' AND account_route = ?
                ORDER BY id ASC
                """,
                (ACCOUNT_ROUTE_SHARED_POOL,),
            ).fetchall()
        return tuple(str(row["job_id"]) for row in rows)

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
                    error_json = ?,
                    credential_scope = NULL,
                    runtime_auth_required = 0,
                    expected_user_email = NULL,
                    session_id = NULL,
                    jwt = NULL,
                    progress_stage = 'failed',
                    progress_at = ?,
                    progress_sequence = progress_sequence + 1
                WHERE job_id IN ({job_placeholders})
                """,
                [now, error_json, now, *matched_job_ids],
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
            for job_id in matched_job_ids:
                self._append_current_progress_event(
                    conn,
                    job_id=job_id,
                    stage="failed",
                    progress_at=now,
                    metadata={"outcome": "failed"},
                )
            conn.commit()
        return len(matched_job_ids)

    def get_status(self, job_id: str) -> dict[str, Any]:
        """读取任务当前状态。"""
        with self._connect() as conn:
            return self._status_from_connection(conn, job_id)

    def _status_from_connection(
        self,
        conn: sqlite3.Connection,
        job_id: str,
    ) -> dict[str, Any]:
        """在现有事务中构造任务状态，避免领取提交后重新读取失败。"""
        row = conn.execute(
            """
            SELECT id, job_id, queue_scope, task_kind, status, request_json, root_dir,
                   created_at, started_at, finished_at, assigned_account,
                   assigned_account_key, worker_key, assignment_generation,
                   failover_count, last_error_code, last_failed_account_key,
                   retry_reason, result_path, row_count, export_json, error_json,
                   execution_owner, heartbeat_at, lease_expires_at, remote_task_id,
                   progress_stage, progress_at, progress_sequence
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

    def get_task_account_binding(self, job_id: str) -> dict[str, str | None]:
        """读取任务执行时持久化的卖家精灵账号绑定。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT assigned_account, assigned_account_key, account_route, "
                "requested_account_id, requested_account_key "
                "FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        binding = {
            "assigned_account": row["assigned_account"],
            "assigned_account_key": row["assigned_account_key"],
        }
        if str(row["account_route"]) == ACCOUNT_ROUTE_USER_BINDING:
            binding.update(
                {
                    "account_route": ACCOUNT_ROUTE_USER_BINDING,
                    "requested_account_id": row["requested_account_id"],
                    "requested_account_key": row["requested_account_key"],
                }
            )
        return binding

    def get_task_context(self, job_id: str) -> dict[str, Any]:
        """读取任务执行所需的附加上下文。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT credential_scope, runtime_auth_required, expected_user_email, session_id, jwt "
                "FROM seller_sprite_task_queue WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        return {
            "credential_scope": row["credential_scope"],
            "runtime_auth_required": bool(row["runtime_auth_required"]),
            "expected_user_email": row["expected_user_email"],
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

    def quarantine_account(
        self,
        *,
        account_key: str,
        credential_version: str,
        reason: str,
        error_code: str,
        ttl_seconds: int,
    ) -> None:
        """在有限时间内隔离一个已确认认证失败的凭据版本。

        参数：
            account_key: 脱敏账号身份散列。
            credential_version: 凭据版本散列。
            reason: 隔离原因。
            error_code: 触发隔离的稳定错误码。
            ttl_seconds: 隔离有效秒数。

        返回：
            无。
        """
        now_at = datetime.now(timezone.utc)
        now = now_at.isoformat(timespec="seconds")
        expires_at = (
            now_at + timedelta(seconds=max(1, int(ttl_seconds)))
        ).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO seller_sprite_account_quarantine (
                    account_key, credential_version, reason, first_failed_at,
                    last_failed_at, expires_at, failure_count, last_error_code
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(account_key, credential_version) DO UPDATE SET
                    reason = excluded.reason,
                    last_failed_at = excluded.last_failed_at,
                    expires_at = excluded.expires_at,
                    failure_count = seller_sprite_account_quarantine.failure_count + 1,
                    last_error_code = excluded.last_error_code
                """,
                (
                    account_key,
                    credential_version,
                    reason,
                    now,
                    now,
                    expires_at,
                    error_code,
                ),
            )

    def is_account_quarantined(
        self,
        *,
        account_key: str,
        credential_version: str,
    ) -> bool:
        """判断账号当前凭据版本是否仍处于认证失败隔离期。

        参数：
            account_key: 脱敏账号身份散列。
            credential_version: 凭据版本散列。

        返回：
            仍处于有效隔离期时返回 ``True``。
        """
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM seller_sprite_account_quarantine WHERE expires_at <= ?",
                (now,),
            )
            row = conn.execute(
                """
                SELECT 1
                FROM seller_sprite_account_quarantine
                WHERE account_key = ? AND credential_version = ? AND expires_at > ?
                """,
                (account_key, credential_version, now),
            ).fetchone()
        return row is not None

    def list_active_account_quarantines(self) -> set[tuple[str, str]]:
        """返回仍有效的账号与凭据版本隔离键集合。

        返回：
            账号身份散列与凭据版本散列组成的集合。
        """
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM seller_sprite_account_quarantine WHERE expires_at <= ?",
                (now,),
            )
            rows = conn.execute(
                """
                SELECT account_key, credential_version
                FROM seller_sprite_account_quarantine
                WHERE expires_at > ?
                """,
                (now,),
            ).fetchall()
        return {
            (str(row["account_key"]), str(row["credential_version"]))
            for row in rows
        }

    def _record_claim_progress(self, conn: sqlite3.Connection, task_id: int) -> None:
        """在领取事务中初始化 claimed 进度并追加首条时间线。"""
        now = _now_iso()
        conn.execute(
            """
            UPDATE seller_sprite_task_queue
            SET progress_stage = 'claimed', progress_at = ?,
                progress_sequence = progress_sequence + 1
            WHERE id = ? AND status = 'running'
            """,
            (now, task_id),
        )
        row = conn.execute(
            """
            SELECT job_id, assignment_generation, progress_sequence
            FROM seller_sprite_task_queue
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO seller_sprite_task_progress_events (
                job_id, progress_stage, progress_at, progress_sequence,
                assignment_generation, metadata_json
            )
            VALUES (?, 'claimed', ?, ?, ?, '{}')
            """,
            (
                str(row["job_id"]),
                now,
                int(row["progress_sequence"]),
                int(row["assignment_generation"]),
            ),
        )

    def _append_current_progress_event(
        self,
        conn: sqlite3.Connection,
        *,
        job_id: str,
        stage: str,
        progress_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """在状态更新事务中追加当前代际的脱敏进度事件。"""
        row = conn.execute(
            """
            SELECT assignment_generation, progress_sequence
            FROM seller_sprite_task_queue
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{job_id}")
        conn.execute(
            """
            INSERT INTO seller_sprite_task_progress_events (
                job_id, progress_stage, progress_at, progress_sequence,
                assignment_generation, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                stage,
                progress_at,
                int(row["progress_sequence"]),
                int(row["assignment_generation"]),
                json.dumps(
                    _sanitize_task_progress_metadata(metadata),
                    ensure_ascii=False,
                ),
            ),
        )

    def _append_collection_success_event(
        self,
        conn: sqlite3.Connection,
        *,
        job_id: str,
        succeeded_at: str,
    ) -> None:
        """原子记录任务首次成功顺序，供数据沉淀使用单调游标补偿。"""
        conn.execute(
            """
            INSERT INTO seller_sprite_collection_success_events (job_id, succeeded_at)
            VALUES (?, ?)
            ON CONFLICT(job_id) DO NOTHING
            """,
            (job_id, succeeded_at),
        )

    def _ensure_schema(self) -> None:
        """在单个立即事务内初始化或升级 SQLite 表结构。"""
        with self._connect() as conn:
            # WAL 模式会持久化到数据库文件，只需在初始化阶段设置一次。
            conn.execute("PRAGMA journal_mode = WAL")
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
                    credential_scope TEXT NULL,
                    runtime_auth_required INTEGER NOT NULL DEFAULT 0,
                    expected_user_email TEXT NULL,
                    account_route TEXT NOT NULL DEFAULT 'shared_pool',
                    requested_account_id TEXT NULL,
                    requested_account_key TEXT NULL,
                    session_id TEXT NULL,
                    jwt TEXT NULL,
                    execution_owner TEXT NULL,
                    heartbeat_at TEXT NULL,
                    lease_expires_at TEXT NULL,
                    remote_task_id TEXT NULL,
                    progress_stage TEXT NOT NULL DEFAULT 'queued',
                    progress_at TEXT NULL,
                    progress_sequence INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # 成功事件只记录升级后的新完成任务，不回填历史 succeeded，保持 live cutover 边界。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_collection_success_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    succeeded_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES seller_sprite_task_queue(job_id)
                        ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_seller_sprite_collection_success_events
                ON seller_sprite_collection_success_events(succeeded_at, id)
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(seller_sprite_task_queue)")}
            if "credential_scope" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN credential_scope TEXT NULL")
            if "runtime_auth_required" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue "
                    "ADD COLUMN runtime_auth_required INTEGER NOT NULL DEFAULT 0"
                )
            if "expected_user_email" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN expected_user_email TEXT NULL"
                )
            if "account_route" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue "
                    "ADD COLUMN account_route TEXT NOT NULL DEFAULT 'shared_pool'"
                )
            if "requested_account_id" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN requested_account_id TEXT NULL"
                )
            if "requested_account_key" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN requested_account_key TEXT NULL"
                )
            if "session_id" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN session_id TEXT NULL")
            if "jwt" not in columns:
                conn.execute("ALTER TABLE seller_sprite_task_queue ADD COLUMN jwt TEXT NULL")
            if "execution_owner" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN execution_owner TEXT NULL"
                )
            if "heartbeat_at" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN heartbeat_at TEXT NULL"
                )
            if "lease_expires_at" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN lease_expires_at TEXT NULL"
                )
            if "remote_task_id" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN remote_task_id TEXT NULL"
                )
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
            if "progress_stage" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue "
                    "ADD COLUMN progress_stage TEXT NOT NULL DEFAULT 'queued'"
                )
            if "progress_at" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue ADD COLUMN progress_at TEXT NULL"
                )
            if "progress_sequence" not in columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_task_queue "
                    "ADD COLUMN progress_sequence INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                UPDATE seller_sprite_task_queue
                SET progress_stage = CASE status
                        WHEN 'queued' THEN 'queued'
                        WHEN 'running' THEN 'claimed'
                        WHEN 'succeeded' THEN 'finished'
                        WHEN 'failed' THEN 'failed'
                        ELSE status
                    END,
                    progress_at = COALESCE(
                        progress_at, finished_at, started_at, created_at
                    )
                WHERE progress_at IS NULL OR progress_stage IS NULL
                """
            )
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_account_quarantine (
                    account_key TEXT NOT NULL,
                    credential_version TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    first_failed_at TEXT NOT NULL,
                    last_failed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    failure_count INTEGER NOT NULL DEFAULT 1,
                    last_error_code TEXT NOT NULL,
                    PRIMARY KEY (account_key, credential_version)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_account_quarantine_expires_at "
                "ON seller_sprite_account_quarantine(expires_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_task_progress_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    progress_stage TEXT NOT NULL,
                    progress_at TEXT NOT NULL,
                    progress_sequence INTEGER NOT NULL,
                    assignment_generation INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_progress_job_sequence "
                "ON seller_sprite_task_progress_events(job_id, progress_sequence)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seller_sprite_runtime_heartbeats (
                    execution_owner TEXT NOT NULL PRIMARY KEY,
                    lifecycle_state TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    generic_workers_alive INTEGER NOT NULL DEFAULT 0,
                    listing_worker_alive INTEGER NOT NULL DEFAULT 0,
                    generic_available_capacity INTEGER NOT NULL DEFAULT 0,
                    listing_available_capacity INTEGER NOT NULL DEFAULT 0,
                    available_capacity INTEGER NOT NULL DEFAULT 0,
                    standby_capacity INTEGER NOT NULL DEFAULT 0,
                    last_claim_at TEXT NULL,
                    last_progress_at TEXT NULL
                )
                """
            )
            runtime_columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(seller_sprite_runtime_heartbeats)"
                )
            }
            if "generic_available_capacity" not in runtime_columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_runtime_heartbeats "
                    "ADD COLUMN generic_available_capacity INTEGER NOT NULL DEFAULT 0"
                )
            if "listing_available_capacity" not in runtime_columns:
                conn.execute(
                    "ALTER TABLE seller_sprite_runtime_heartbeats "
                    "ADD COLUMN listing_available_capacity INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_seller_sprite_runtime_heartbeat_at "
                "ON seller_sprite_runtime_heartbeats(heartbeat_at)"
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """创建并显式关闭 SQLite 连接，统一事务生命周期。"""
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            with conn:
                yield conn
        finally:
            # sqlite3.Connection.__exit__ 只处理事务，不负责关闭文件描述符。
            conn.close()

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
            "stage": (
                str(row["progress_stage"] or "running")
                if status == "running"
                else _stage_for_status(status)
            ),
            "progress_stage": str(row["progress_stage"] or _stage_for_status(status)),
            "progress_at": row["progress_at"],
            "progress_sequence": int(row["progress_sequence"] or 0),
            "position": position,
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "root_dir": row["root_dir"],
            "task_kind": row["task_kind"],
            "assigned_account": row["assigned_account"],
            "assigned_account_key": row["assigned_account_key"],
            "worker_key": row["worker_key"],
            "assignment_generation": int(row["assignment_generation"] or 0),
            "failover_count": int(row["failover_count"] or 0),
            "last_error_code": row["last_error_code"],
            "retry_reason": row["retry_reason"],
            "execution_owner": row["execution_owner"],
            "heartbeat_at": row["heartbeat_at"],
            "lease_expires_at": row["lease_expires_at"],
            "remote_task_id": row["remote_task_id"],
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


def _utc_now_iso() -> str:
    """返回适合数据库按字典序比较的 UTC ISO 时间。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seconds_ago_iso(seconds: int) -> str:
    """返回当前时间向前偏移指定秒数后的本地 ISO 字符串。"""
    return (datetime.now(timezone.utc).astimezone() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _future_iso(seconds: float) -> str:
    """返回当前时间向后偏移指定秒数的本地 ISO 字符串。"""
    return (
        datetime.now(timezone.utc).astimezone()
        + timedelta(seconds=max(0.01, float(seconds)))
    ).isoformat(timespec="seconds")


def _claim_owner(execution_owner: str | None, worker_key: str) -> str:
    """兼容直接调用 store 的领取方，并确保新领取任务始终拥有租约 owner。"""
    return execution_owner or f"worker:{worker_key}"


def _task_kind_for_request(request: SellerSpriteScenarioRequest) -> str:
    """根据规范化场景返回不可伪造的任务类型。"""
    return (
        TASK_KIND_LISTING_ANALYSIS
        if request.scenario.strip().lower() == "listing-analysis"
        else TASK_KIND_GENERIC
    )


def _sanitize_task_progress_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """仅保留监控所需的固定枚举与非负轮询计数。"""
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in TASK_PROGRESS_METADATA_FIELDS:
        value = metadata.get(key)
        if key in {"poll_attempt", "poll_total"}:
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                safe[key] = value
        elif key == "poll_status":
            normalized = str(value or "").strip().upper()
            if normalized in TASK_PROGRESS_POLL_STATUSES:
                safe[key] = normalized
        elif key == "outcome":
            normalized = str(value or "").strip().lower()
            if normalized in TASK_PROGRESS_OUTCOMES:
                safe[key] = normalized
    return safe


def _task_progress_event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """将进度事件行转换为固定的脱敏监控结构。"""
    return {
        "job_id": str(row["job_id"]),
        "stage": str(row["progress_stage"]),
        "progress_at": row["progress_at"],
        "sequence": int(row["progress_sequence"]),
        "assignment_generation": int(row["assignment_generation"]),
        "metadata": json.loads(str(row["metadata_json"] or "{}")),
    }


def _runtime_heartbeat_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """将运行态心跳行转换为不含账号与任务载荷的结构。"""
    return {
        "execution_owner": str(row["execution_owner"]),
        "lifecycle_state": str(row["lifecycle_state"]),
        "heartbeat_at": row["heartbeat_at"],
        "generic_workers_alive": int(row["generic_workers_alive"] or 0),
        "listing_worker_alive": int(row["listing_worker_alive"] or 0),
        "generic_available_capacity": int(
            row["generic_available_capacity"] or 0
        ),
        "listing_available_capacity": int(
            row["listing_available_capacity"] or 0
        ),
        "available_capacity": int(row["available_capacity"] or 0),
        "standby_capacity": int(row["standby_capacity"] or 0),
        "last_claim_at": row["last_claim_at"],
        "last_progress_at": row["last_progress_at"],
    }


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
