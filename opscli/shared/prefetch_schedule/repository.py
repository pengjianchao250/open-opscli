"""预取计划和执行队列的 MySQL 仓储。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.prefetch_schedule.models import PrefetchRunClaim
from opscli.shared.prefetch_schedule.validation import next_daily_run


class PrefetchScheduleRepository:
    """以共享 MySQL 保存用户计划，并用行锁协调多宿主执行。"""

    def __init__(
        self,
        *,
        settings: MySqlSettings,
        connect_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._connect_factory = connect_factory or self._connect

    def create_schedule(
        self,
        *,
        schedule_name: str,
        source_system: str,
        scenario: str,
        request: dict[str, Any],
        run_time: str,
        timezone_name: str,
        enabled: bool,
        next_run_at: datetime,
        created_by: str,
    ) -> dict[str, Any]:
        """创建一条每日预取计划并返回公开记录。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO collection_prefetch_schedules (
                        schedule_name, source_system, scenario, request_json,
                        cadence, run_time, timezone, enabled, next_run_at, created_by
                    ) VALUES (%s, %s, %s, %s, 'daily', %s, %s, %s, %s, %s)
                    """,
                    (
                        schedule_name,
                        source_system,
                        scenario,
                        _json_dump(request),
                        run_time,
                        timezone_name,
                        int(enabled),
                        _mysql_datetime(next_run_at),
                        created_by,
                    ),
                )
                schedule_id = int(cursor.lastrowid or 0)
                if schedule_id <= 0:
                    raise RuntimeError("MySQL 未返回预取计划 ID")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_schedule(schedule_id=schedule_id, created_by=created_by)

    def get_schedule(
        self,
        *,
        schedule_id: int,
        created_by: str,
    ) -> dict[str, Any]:
        """读取当前用户拥有的一条预取计划。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, schedule_name, source_system, scenario, request_json,
                           cadence, run_time, timezone, enabled, next_run_at,
                           created_by, created_at, updated_at
                    FROM collection_prefetch_schedules
                    WHERE id = %s AND created_by = %s
                    """,
                    (int(schedule_id), created_by),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            raise ValueError(f"预取计划不存在或无权访问：{schedule_id}")
        return _schedule_row(row)

    def list_schedules(
        self,
        *,
        created_by: str,
        source_system: str | None = None,
        enabled: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """列出当前用户创建的预取计划。"""
        clauses = ["created_by = %s"]
        params: list[Any] = [created_by]
        if source_system:
            clauses.append("source_system = %s")
            params.append(source_system)
        if enabled is not None:
            clauses.append("enabled = %s")
            params.append(int(enabled))
        params.append(max(1, min(int(limit), 500)))
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, schedule_name, source_system, scenario, request_json,
                           cadence, run_time, timezone, enabled, next_run_at,
                           created_by, created_at, updated_at
                    FROM collection_prefetch_schedules
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        return [_schedule_row(row) for row in rows]

    def update_schedule(
        self,
        *,
        schedule_id: int,
        created_by: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """更新当前用户计划的白名单字段。"""
        allowed = {
            "schedule_name",
            "request_json",
            "run_time",
            "timezone",
            "enabled",
            "next_run_at",
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"不允许更新预取计划字段：{', '.join(unknown)}")
        if not values:
            return self.get_schedule(schedule_id=schedule_id, created_by=created_by)
        assignments = [f"{field} = %s" for field in values]
        params = [
            _json_dump(value) if field == "request_json" else value
            for field, value in values.items()
        ]
        params.extend((int(schedule_id), created_by))
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute(
                    f"""
                    UPDATE collection_prefetch_schedules
                    SET {', '.join(assignments)}
                    WHERE id = %s AND created_by = %s
                    """,
                    tuple(params),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if not affected:
            raise ValueError(f"预取计划不存在或无权访问：{schedule_id}")
        return self.get_schedule(schedule_id=schedule_id, created_by=created_by)

    def set_schedules_enabled(
        self,
        *,
        schedule_ids: Iterable[int],
        created_by: str,
        enabled: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """在一个事务中批量启用或禁用当前用户的计划。"""
        ids = tuple(dict.fromkeys(int(value) for value in schedule_ids))
        if not ids:
            raise ValueError("至少提供一个预取计划 ID")
        if len(ids) > 100:
            raise ValueError("单次最多启停 100 个预取计划")
        if any(value <= 0 for value in ids):
            raise ValueError("预取计划 ID 必须为正整数")

        placeholders = ", ".join("%s" for _ in ids)
        current = _utc_naive(now)
        changed_count = 0
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, run_time, timezone, enabled, next_run_at
                    FROM collection_prefetch_schedules
                    WHERE created_by = %s AND id IN ({placeholders})
                    FOR UPDATE
                    """,
                    (created_by, *ids),
                )
                rows = cursor.fetchall() or []
                found_ids = {int(row["id"]) for row in rows}
                if found_ids != set(ids):
                    missing = ", ".join(
                        str(value) for value in ids if value not in found_ids
                    )
                    raise ValueError(f"预取计划不存在或无权访问：{missing}")

                for row in rows:
                    currently_enabled = bool(row.get("enabled"))
                    if enabled and not currently_enabled:
                        next_run_at = next_daily_run(
                            _time_text(row.get("run_time")),
                            str(row.get("timezone") or "Asia/Shanghai"),
                            after=current.replace(tzinfo=timezone.utc),
                        )
                        cursor.execute(
                            """
                            UPDATE collection_prefetch_schedules
                            SET enabled = 1, next_run_at = %s
                            WHERE id = %s AND created_by = %s
                            """,
                            (next_run_at, int(row["id"]), created_by),
                        )
                        changed_count += 1
                    elif not enabled and currently_enabled:
                        cursor.execute(
                            """
                            UPDATE collection_prefetch_schedules
                            SET enabled = 0
                            WHERE id = %s AND created_by = %s
                            """,
                            (int(row["id"]), created_by),
                        )
                        changed_count += 1

                cursor.execute(
                    f"""
                    SELECT id, schedule_name, source_system, scenario, request_json,
                           cadence, run_time, timezone, enabled, next_run_at,
                           created_by, created_at, updated_at
                    FROM collection_prefetch_schedules
                    WHERE created_by = %s AND id IN ({placeholders})
                    """,
                    (created_by, *ids),
                )
                updated_rows = cursor.fetchall() or []
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        schedules_by_id = {
            int(row["id"]): _schedule_row(row) for row in updated_rows
        }
        return {
            "changed_count": changed_count,
            "schedules": [schedules_by_id[value] for value in ids],
        }

    def delete_schedule(self, *, schedule_id: int, created_by: str) -> None:
        """删除当前用户拥有的计划及其级联运行历史。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id FROM collection_prefetch_schedules
                    WHERE id = %s AND created_by = %s
                    FOR UPDATE
                    """,
                    (int(schedule_id), created_by),
                )
                if not cursor.fetchone():
                    raise ValueError(f"预取计划不存在或无权访问：{schedule_id}")
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM collection_prefetch_runs
                    WHERE schedule_id = %s AND status IN ('queued', 'running')
                    """,
                    (int(schedule_id),),
                )
                active = cursor.fetchone() or {}
                if int(active.get("total") or 0) > 0:
                    raise ValueError("预取计划仍有排队或运行中的任务，请等待完成后再删除")
                cursor.execute(
                    """
                    DELETE FROM collection_prefetch_schedules
                    WHERE id = %s AND created_by = %s
                    """,
                    (int(schedule_id), created_by),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def queue_run_now(
        self,
        *,
        schedule_id: int,
        created_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """为当前用户计划追加一条立即执行记录。"""
        current = _utc_naive(now)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, source_system, scenario, request_json
                    FROM collection_prefetch_schedules
                    WHERE id = %s AND created_by = %s
                    FOR UPDATE
                    """,
                    (int(schedule_id), created_by),
                )
                schedule = cursor.fetchone()
                if not schedule:
                    raise ValueError(f"预取计划不存在或无权访问：{schedule_id}")
                cursor.execute(
                    """
                    INSERT INTO collection_prefetch_runs (
                        schedule_id, source_system, scenario, request_json,
                        trigger_type, scheduled_for, status
                    ) VALUES (%s, %s, %s, %s, 'manual', %s, 'queued')
                    """,
                    (
                        int(schedule_id),
                        schedule["source_system"],
                        schedule["scenario"],
                        schedule["request_json"],
                        current,
                    ),
                )
                run_id = int(cursor.lastrowid or 0)
                if run_id <= 0:
                    raise RuntimeError("MySQL 未返回预取运行 ID")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "run_id": run_id,
            "schedule_id": int(schedule_id),
            "trigger_type": "manual",
            "status": "queued",
            "scheduled_for": current.isoformat(timespec="seconds") + "Z",
        }

    def enqueue_due(
        self,
        *,
        source_systems: Iterable[str],
        now: datetime | None = None,
        limit: int = 20,
    ) -> int:
        """将当前宿主负责且已经到期的每日计划推进到运行队列。"""
        sources = tuple(sorted(set(source_systems)))
        if not sources:
            return 0
        current = _utc_naive(now)
        placeholders = ", ".join("%s" for _ in sources)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, source_system, scenario, request_json,
                           run_time, timezone, next_run_at
                    FROM collection_prefetch_schedules
                    WHERE enabled = 1
                      AND source_system IN ({placeholders})
                      AND next_run_at <= %s
                    ORDER BY next_run_at, id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (*sources, current, max(1, min(int(limit), 100))),
                )
                rows = cursor.fetchall() or []
                for row in rows:
                    scheduled_for = _utc_naive(row.get("next_run_at"))
                    cursor.execute(
                        """
                        INSERT IGNORE INTO collection_prefetch_runs (
                            schedule_id, source_system, scenario, request_json,
                            trigger_type, scheduled_for, status
                        ) VALUES (%s, %s, %s, %s, 'scheduled', %s, 'queued')
                        """,
                        (
                            int(row["id"]),
                            row["source_system"],
                            row["scenario"],
                            row["request_json"],
                            scheduled_for,
                        ),
                    )
                    next_at = next_daily_run(
                        _time_text(row.get("run_time")),
                        str(row.get("timezone") or "Asia/Shanghai"),
                        after=current.replace(tzinfo=timezone.utc),
                    )
                    cursor.execute(
                        """
                        UPDATE collection_prefetch_schedules
                        SET next_run_at = %s
                        WHERE id = %s
                        """,
                        (next_at, int(row["id"])),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return len(rows)

    def claim_next(
        self,
        *,
        source_systems: Iterable[str],
        execution_owner: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> PrefetchRunClaim | None:
        """按来源归属领取一条运行，并恢复租约过期的中断任务。"""
        sources = tuple(sorted(set(source_systems)))
        if not sources:
            return None
        current = _utc_naive(now)
        lease_expires_at = current + timedelta(seconds=max(1.0, lease_seconds))
        placeholders = ", ".join("%s" for _ in sources)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT runs.id AS run_id, runs.schedule_id, runs.trigger_type,
                           runs.scheduled_for, runs.source_system,
                           runs.scenario, runs.request_json
                    FROM collection_prefetch_runs AS runs
                    WHERE runs.source_system IN ({placeholders})
                      AND runs.scheduled_for <= %s
                      AND (
                          runs.status = 'queued'
                          OR (
                              runs.status = 'running'
                              AND runs.lease_expires_at < %s
                          )
                      )
                    ORDER BY runs.scheduled_for, runs.id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    (*sources, current, current),
                )
                row = cursor.fetchone()
                if not row:
                    connection.commit()
                    return None
                cursor.execute(
                    """
                    UPDATE collection_prefetch_runs
                    SET status = 'running', execution_owner = %s,
                        lease_expires_at = %s,
                        started_at = COALESCE(started_at, %s),
                        error_code = NULL, error_message = NULL
                    WHERE id = %s
                    """,
                    (
                        execution_owner,
                        lease_expires_at,
                        current,
                        int(row["run_id"]),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return PrefetchRunClaim(
            run_id=int(row["run_id"]),
            schedule_id=int(row["schedule_id"]),
            source_system=str(row["source_system"]),
            scenario=str(row["scenario"]),
            request=_json_load(row.get("request_json")),
            trigger_type=str(row["trigger_type"]),
            scheduled_for=_utc_naive(row.get("scheduled_for")),
        )

    def extend_lease(
        self,
        *,
        run_id: int,
        execution_owner: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        """延长当前宿主持有的运行租约。"""
        current = _utc_naive(now)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute(
                    """
                    UPDATE collection_prefetch_runs
                    SET lease_expires_at = %s
                    WHERE id = %s AND status = 'running'
                      AND execution_owner = %s
                    """,
                    (
                        current + timedelta(seconds=max(1.0, lease_seconds)),
                        int(run_id),
                        execution_owner,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return bool(affected)

    def finish_run(
        self,
        *,
        run_id: int,
        execution_owner: str,
        status: str,
        source_job_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """仅允许租约持有者把运行更新为成功或失败终态。"""
        if status not in {"succeeded", "failed"}:
            raise ValueError(f"不支持的预取运行终态：{status}")
        current = _utc_naive(now)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute(
                    """
                    UPDATE collection_prefetch_runs
                    SET status = %s, source_job_id = %s,
                        error_code = %s, error_message = %s,
                        completed_at = %s, lease_expires_at = NULL
                    WHERE id = %s AND status = 'running'
                      AND execution_owner = %s
                    """,
                    (
                        status,
                        source_job_id,
                        error_code,
                        error_message,
                        current,
                        int(run_id),
                        execution_owner,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if not affected:
            raise RuntimeError("预取运行租约已丢失，拒绝覆盖其他宿主的执行结果")

    def list_runs(
        self,
        *,
        created_by: str,
        schedule_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出当前用户计划的最近执行记录。"""
        clauses = ["schedules.created_by = %s"]
        params: list[Any] = [created_by]
        if schedule_id is not None:
            clauses.append("runs.schedule_id = %s")
            params.append(int(schedule_id))
        params.append(max(1, min(int(limit), 500)))
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT runs.id, runs.schedule_id, schedules.schedule_name,
                           schedules.source_system, schedules.scenario,
                           runs.trigger_type, runs.scheduled_for, runs.status,
                           runs.source_job_id, runs.error_code, runs.error_message,
                           runs.started_at, runs.completed_at, runs.created_at
                    FROM collection_prefetch_runs AS runs
                    JOIN collection_prefetch_schedules AS schedules
                      ON schedules.id = runs.schedule_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY runs.created_at DESC, runs.id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        return [_public_row(row) for row in rows]

    def _connect(self) -> Any:
        """创建使用字典游标的短连接。"""
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 PyMySQL 依赖，无法连接预取计划 MySQL") from exc
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            connect_timeout=self.settings.connect_timeout_seconds,
            read_timeout=60,
            write_timeout=60,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            ssl_ca=self.settings.ssl_ca or None,
            ssl_verify_cert=bool(self.settings.ssl_ca),
            ssl_verify_identity=bool(self.settings.ssl_ca),
        )


def _schedule_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _public_row(row)
    payload["request"] = _json_load(payload.pop("request_json", None))
    payload["enabled"] = bool(payload.get("enabled"))
    payload["run_time"] = _time_text(payload.get("run_time"))
    return payload


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, datetime):
            result[key] = value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
        else:
            result[key] = value
    return result


def _json_dump(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_load(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError("预取计划 request_json 必须是 JSON 对象")
    return parsed


def _utc_naive(value: datetime | Any | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if not isinstance(value, datetime):
        raise ValueError("预取计划时间字段必须是 datetime")
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _mysql_datetime(value: datetime) -> datetime:
    return _utc_naive(value)


def _time_text(value: Any) -> str:
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) == 3:
        return ":".join(part.zfill(2) for part in parts)
    return text
