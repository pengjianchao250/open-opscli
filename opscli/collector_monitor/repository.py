"""SellerSprite 固定监督表契约的严格只读查询仓储。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import quote

from opscli.collector_monitor.classifier import ClassificationPolicy, classify_snapshot

_TASK_TABLE = "seller_sprite_task_queue"
_EVENT_TABLE = "seller_sprite_task_progress_events"
_RUNTIME_TABLE = "seller_sprite_runtime_heartbeats"
_TASK_COLUMNS = (
    "job_id",
    "queue_scope",
    "task_kind",
    "status",
    "created_at",
    "started_at",
    "finished_at",
    "execution_owner",
    "heartbeat_at",
    "lease_expires_at",
    "progress_stage",
    "progress_at",
    "progress_sequence",
    "last_error_code",
    "retry_reason",
    "row_count",
)
_EVENT_COLUMNS = (
    "job_id",
    "progress_stage",
    "progress_at",
    "progress_sequence",
)
_RUNTIME_COLUMNS = (
    "execution_owner",
    "lifecycle_state",
    "heartbeat_at",
    "generic_workers_alive",
    "listing_worker_alive",
    "generic_available_capacity",
    "listing_available_capacity",
    "available_capacity",
    "standby_capacity",
    "last_claim_at",
    "last_progress_at",
)
_ALLOWED_HEALTH = {
    "healthy",
    "slow",
    "stalled",
    "orphaned",
    "queue_starved",
    "worker_unavailable",
}
_ALLOWED_LIFECYCLE = {"queued", "running", "succeeded", "failed"}
_ALLOWED_TASK_KIND = {"generic", "listing_analysis"}
_MAX_SNAPSHOT_TASKS = 1000
_MAX_RUNTIMES = 100
_MAX_LIST_LIMIT = 500
_MAX_TIMELINE_LIMIT = 500
_READ_BATCH_SIZE = 500
_SQLITE_PARAMETER_BATCH = 400


class RepositorySourceError(RuntimeError):
    """表示队列文件不可读或固定监督 schema 不满足契约。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message

    def to_dict(self) -> dict[str, str]:
        """返回不含路径和数据库原始错误的安全结构。"""
        return {"code": self.code, "message": self.safe_message}


class TaskNotFoundError(LookupError):
    """表示指定任务不存在。"""


@dataclass(frozen=True)
class ScanObservations:
    """一次只读事务内取得的完整活动观测和有界展示历史。"""

    tasks: tuple[dict[str, Any], ...]
    runtimes: tuple[dict[str, Any], ...]
    total: int
    lifecycle_counts: Mapping[str, int]
    public_task_limit: int = _MAX_SNAPSHOT_TASKS


class ReadOnlySellerSpriteRepository:
    """通过 SQLite 只读 URI 查询 SellerSprite 固定监督表。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        policy: ClassificationPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def snapshot(
        self,
        *,
        orphan_observations: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        """返回一次脱敏队列快照；活动任务和汇总不受展示上限影响。"""
        now = self.clock()
        try:
            observations = self.scan_observations()
        except RepositorySourceError as exc:
            return _unready_snapshot(now, exc)
        classified = classify_snapshot(
            observations.tasks,
            observations.runtimes,
            now=now,
            policy=self.policy,
            orphan_observations=orphan_observations,
        )
        return {
            "generated_at": _iso(now),
            "source": {"ready": True, "error": None},
            "summary": _complete_summary(classified.summary, observations),
            "tasks": [
                task.to_dict()
                for task in classified.tasks[: observations.public_task_limit]
            ],
            "runtimes": [
                _runtime_to_public(runtime) for runtime in observations.runtimes
            ],
            "incident_candidates": [item.to_dict() for item in classified.incidents],
        }

    def list_tasks(
        self,
        *,
        health: str | None = None,
        lifecycle: str | None = None,
        task_kind: str | None = None,
        limit: int = 100,
        orphan_observations: Mapping[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """按白名单条件列出有界的脱敏任务。"""
        if health is not None and health not in _ALLOWED_HEALTH:
            raise ValueError(f"unsupported health filter: {health}")
        if lifecycle is not None and lifecycle not in _ALLOWED_LIFECYCLE:
            raise ValueError(f"unsupported lifecycle filter: {lifecycle}")
        if task_kind is not None and task_kind not in _ALLOWED_TASK_KIND:
            raise ValueError(f"unsupported task kind filter: {task_kind}")
        safe_limit = _bounded_limit(limit, maximum=_MAX_LIST_LIMIT)
        snapshot = self.snapshot(orphan_observations=orphan_observations)
        self._raise_for_snapshot_source(snapshot)
        tasks = snapshot["tasks"]
        if health is not None:
            tasks = [item for item in tasks if item["health"] == health]
        if lifecycle is not None:
            tasks = [item for item in tasks if item["lifecycle"] == lifecycle]
        if task_kind is not None:
            tasks = [item for item in tasks if item["task_kind"] == task_kind]
        return tasks[:safe_limit]

    def task_detail(
        self,
        job_id: str,
        *,
        timeline_limit: int = 200,
        orphan_observations: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        """直接返回单个脱敏任务及时间线，不重新扫描全队列。"""
        normalized_job_id = _normalized_job_id(job_id)
        safe_limit = _bounded_limit(timeline_limit, maximum=_MAX_TIMELINE_LIMIT)
        with self._read_connection() as conn:
            task_row = conn.execute(
                f"SELECT {', '.join(_TASK_COLUMNS)} FROM {_TASK_TABLE} WHERE job_id = ?",
                (normalized_job_id,),
            ).fetchone()
            if task_row is None:
                raise TaskNotFoundError(f"任务不存在：{normalized_job_id}")
            runtime_rows = conn.execute(
                f"SELECT {', '.join(_RUNTIME_COLUMNS)} FROM {_RUNTIME_TABLE} "
                "ORDER BY heartbeat_at DESC LIMIT ?",
                (_MAX_RUNTIMES,),
            ).fetchall()
            event_rows = conn.execute(
                f"SELECT {', '.join(_EVENT_COLUMNS)} FROM {_EVENT_TABLE} "
                "WHERE job_id = ? ORDER BY progress_sequence ASC, progress_at ASC LIMIT ?",
                (normalized_job_id, safe_limit),
            ).fetchall()
        task = {column: task_row[column] for column in _TASK_COLUMNS}
        runtimes = [
            {column: row[column] for column in _RUNTIME_COLUMNS}
            for row in runtime_rows
        ]
        classified = classify_snapshot(
            [task],
            runtimes,
            now=self.clock(),
            policy=self.policy,
            orphan_observations=orphan_observations,
        )
        detail = classified.tasks[0].to_dict()
        detail["timeline"] = [_event_to_public(row) for row in event_rows]
        return detail

    def timelines_for_jobs(
        self,
        job_ids: Iterable[str],
        *,
        timeline_limit: int = 200,
    ) -> dict[str, list[dict[str, Any]]]:
        """按 SQLite 参数上限分批读取每个任务的有界进度事件。"""
        safe_limit = _bounded_limit(timeline_limit, maximum=_MAX_TIMELINE_LIMIT)
        normalized = list(dict.fromkeys(_normalized_job_id(item) for item in job_ids))
        timelines = {job_id: [] for job_id in normalized}
        if not normalized:
            return timelines
        with self._read_connection() as conn:
            for batch in _chunks(normalized, _SQLITE_PARAMETER_BATCH):
                placeholders = ", ".join("?" for _ in batch)
                rows = conn.execute(
                    f"""
                    SELECT job_id, progress_stage, progress_at, progress_sequence
                    FROM (
                        SELECT {', '.join(_EVENT_COLUMNS)},
                               ROW_NUMBER() OVER (
                                   PARTITION BY job_id
                                   ORDER BY progress_sequence ASC, progress_at ASC
                               ) AS event_number
                        FROM {_EVENT_TABLE}
                        WHERE job_id IN ({placeholders})
                    )
                    WHERE event_number <= ?
                    ORDER BY job_id ASC, progress_sequence ASC, progress_at ASC
                    """,
                    [*batch, safe_limit],
                ).fetchall()
                for row in rows:
                    timelines[str(row["job_id"])].append(_event_to_public(row))
        return timelines

    def scan_observations(self) -> ScanObservations:
        """在一次只读事务中完整读取活动任务和有界终态历史。"""
        with self._read_connection() as conn:
            conn.execute("BEGIN")
            lifecycle_rows = conn.execute(
                f"SELECT status, COUNT(*) AS count FROM {_TASK_TABLE} GROUP BY status"
            ).fetchall()
            lifecycle_counts = {
                str(row["status"]): int(row["count"]) for row in lifecycle_rows
            }
            active_rows = self._read_active_tasks(conn)
            terminal_limit = max(0, _MAX_SNAPSHOT_TASKS - len(active_rows))
            terminal_rows = conn.execute(
                f"SELECT {', '.join(_TASK_COLUMNS)} FROM {_TASK_TABLE} "
                "WHERE status NOT IN (?, ?) ORDER BY id DESC LIMIT ?",
                ("queued", "running", terminal_limit),
            ).fetchall()
            runtime_rows = conn.execute(
                f"SELECT {', '.join(_RUNTIME_COLUMNS)} FROM {_RUNTIME_TABLE} "
                "ORDER BY heartbeat_at DESC LIMIT ?",
                (_MAX_RUNTIMES,),
            ).fetchall()
            conn.commit()
        tasks = tuple(
            {column: row[column] for column in _TASK_COLUMNS}
            for row in [*active_rows, *terminal_rows]
        )
        runtimes = tuple(
            {column: row[column] for column in _RUNTIME_COLUMNS}
            for row in runtime_rows
        )
        return ScanObservations(
            tasks=tasks,
            runtimes=runtimes,
            total=sum(lifecycle_counts.values()),
            lifecycle_counts=lifecycle_counts,
        )

    def raw_observations(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """兼容返回完整活动观测和有界终态历史。"""
        observations = self.scan_observations()
        return list(observations.tasks), list(observations.runtimes)

    def _read_active_tasks(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        """使用主键游标分批读取全部排队和运行任务。"""
        rows: list[sqlite3.Row] = []
        before_id = 2**63 - 1
        while True:
            batch = conn.execute(
                f"SELECT id, {', '.join(_TASK_COLUMNS)} FROM {_TASK_TABLE} "
                "WHERE status IN (?, ?) AND id < ? ORDER BY id DESC LIMIT ?",
                ("queued", "running", before_id, _READ_BATCH_SIZE),
            ).fetchall()
            if not batch:
                break
            rows.extend(batch)
            before_id = int(batch[-1]["id"])
        return rows

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        """统一包装连接建立后所有 SQLite 只读错误。"""
        conn = self._connect_validated()
        try:
            yield conn
        except RepositorySourceError:
            raise
        except sqlite3.Error as exc:
            raise _repository_read_error(exc) from None
        finally:
            conn.close()

    def _connect_validated(self) -> sqlite3.Connection:
        """打开只读 URI、启用 query_only 并验证固定监督 schema。"""
        if not self.db_path.is_file():
            raise RepositorySourceError(
                "queue_source_unavailable",
                "SellerSprite 队列数据库不存在或不可读",
            )
        conn: sqlite3.Connection | None = None
        try:
            uri_path = quote(self.db_path.resolve().as_posix(), safe="/:")
            conn = sqlite3.connect(
                f"file:{uri_path}?mode=ro",
                uri=True,
                timeout=2.0,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            self._validate_schema(conn)
            return conn
        except RepositorySourceError:
            if conn is not None:
                conn.close()
            raise
        except sqlite3.Error as exc:
            if conn is not None:
                conn.close()
            raise _repository_read_error(exc) from None

    def _validate_schema(self, conn: sqlite3.Connection) -> None:
        """验证固定表名和列名，禁止运行时猜测或迁移。"""
        contracts = {
            _TASK_TABLE: set(_TASK_COLUMNS) | {"id"},
            _EVENT_TABLE: set(_EVENT_COLUMNS),
            _RUNTIME_TABLE: set(_RUNTIME_COLUMNS),
        }
        existing_tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        problems: list[str] = []
        for table, required in contracts.items():
            if table not in existing_tables:
                problems.append(f"缺少表 {table}")
                continue
            columns = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing = sorted(required - columns)
            if missing:
                problems.append(f"表 {table} 缺少列 {', '.join(missing)}")
        if problems:
            raise RepositorySourceError(
                "queue_schema_invalid",
                "SellerSprite 监督 schema 不满足固定契约：" + "；".join(problems),
            )

    @staticmethod
    def _raise_for_snapshot_source(snapshot: Mapping[str, Any]) -> None:
        """把快照中的数据源错误恢复为稳定异常。"""
        source = snapshot["source"]
        if source["ready"]:
            return
        error = source["error"]
        raise RepositorySourceError(str(error["code"]), str(error["message"]))


def _repository_read_error(exc: sqlite3.Error) -> RepositorySourceError:
    """将底层 SQLite 异常压缩为不含路径和 SQL 的稳定错误。"""
    return RepositorySourceError(
        "queue_source_unavailable",
        f"SellerSprite 队列数据库只读访问失败（{type(exc).__name__}）",
    )


def _unready_snapshot(now: datetime, exc: RepositorySourceError) -> dict[str, Any]:
    """构造不泄露路径和 SQL 的未就绪快照。"""
    return {
        "generated_at": _iso(now),
        "source": {"ready": False, "error": exc.to_dict()},
        "summary": {
            "total": 0,
            "by_lifecycle": {},
            "by_health": {},
            "active_incident_count": 0,
        },
        "tasks": [],
        "runtimes": [],
        "incident_candidates": [],
    }


def _complete_summary(
    classified_summary: Mapping[str, Any], observations: ScanObservations
) -> dict[str, Any]:
    """用 SQL 总数补齐未展示终态任务；活动任务始终已完整分类。"""
    health_counts = dict(classified_summary["by_health"])
    omitted_terminal = observations.total - len(observations.tasks)
    if omitted_terminal > 0:
        health_counts["healthy"] = health_counts.get("healthy", 0) + omitted_terminal
    return {
        "total": observations.total,
        "by_lifecycle": dict(observations.lifecycle_counts),
        "by_health": health_counts,
        "active_incident_count": classified_summary["active_incident_count"],
    }


def _event_to_public(row: Mapping[str, Any]) -> dict[str, Any]:
    """将进度事件转换为固定公开字段。"""
    return {
        "progress_stage": _optional_string(row["progress_stage"]),
        "progress_at": _optional_string(row["progress_at"]),
        "progress_sequence": _integer(row["progress_sequence"]),
    }


def _normalized_job_id(value: object) -> str:
    """校验任务标识，避免无界参数进入查询。"""
    normalized = str(value).strip()
    if not normalized or len(normalized) > 200:
        raise TaskNotFoundError("任务标识无效")
    return normalized


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    """按固定参数预算切分 SQLite IN 查询。"""
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def _runtime_to_public(runtime: Mapping[str, Any]) -> dict[str, Any]:
    """将运行时观测转换为固定公开字段。"""
    return {
        "execution_owner": _optional_string(runtime.get("execution_owner")),
        "lifecycle_state": _optional_string(runtime.get("lifecycle_state")),
        "heartbeat_at": _optional_string(runtime.get("heartbeat_at")),
        "generic_workers_alive": _integer(runtime.get("generic_workers_alive")),
        "listing_worker_alive": _integer(runtime.get("listing_worker_alive")),
        "generic_available_capacity": _integer(
            runtime.get("generic_available_capacity")
        ),
        "listing_available_capacity": _integer(
            runtime.get("listing_available_capacity")
        ),
        "available_capacity": _integer(runtime.get("available_capacity")),
        "standby_capacity": _integer(runtime.get("standby_capacity")),
        "last_claim_at": _optional_string(runtime.get("last_claim_at")),
        "last_progress_at": _optional_string(runtime.get("last_progress_at")),
    }


def _bounded_limit(value: int, *, maximum: int) -> int:
    """校验并约束公开查询行数。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return parsed


def _iso(value: datetime) -> str:
    """输出带时区的秒级 ISO 时间。"""
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


def _optional_string(value: Any) -> str | None:
    """转换可选文本值。"""
    return str(value) if value is not None else None


def _integer(value: Any) -> int:
    """转换数据库整数值。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
