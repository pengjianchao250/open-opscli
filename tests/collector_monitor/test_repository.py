"""SellerSprite 只读监控仓储公开契约测试。"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opscli.collector_monitor.classifier import ClassificationPolicy
from opscli.collector_monitor.repository import (
    ReadOnlySellerSpriteRepository,
    RepositorySourceError,
    TaskNotFoundError,
)

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)


def _iso(seconds: int) -> str:
    """返回相对固定时刻的 ISO 时间。"""
    return (NOW + timedelta(seconds=seconds)).isoformat()


def _create_queue_db(path: Path) -> None:
    """创建满足固定监督契约且含敏感列的队列数据库。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA user_version = 77;
            CREATE TABLE seller_sprite_task_queue (
                id INTEGER PRIMARY KEY,
                job_id TEXT UNIQUE NOT NULL,
                queue_scope TEXT NOT NULL,
                task_kind TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                execution_owner TEXT,
                heartbeat_at TEXT,
                lease_expires_at TEXT,
                progress_stage TEXT,
                progress_at TEXT,
                progress_sequence INTEGER NOT NULL,
                last_error_code TEXT,
                retry_reason TEXT,
                row_count INTEGER NOT NULL,
                assigned_account TEXT,
                credential_scope TEXT,
                request_json TEXT,
                root_dir TEXT,
                result_path TEXT,
                error_json TEXT
            );
            CREATE TABLE seller_sprite_task_progress_events (
                id INTEGER PRIMARY KEY,
                job_id TEXT NOT NULL,
                progress_stage TEXT NOT NULL,
                progress_at TEXT NOT NULL,
                progress_sequence INTEGER NOT NULL
            );
            CREATE TABLE seller_sprite_runtime_heartbeats (
                execution_owner TEXT PRIMARY KEY,
                lifecycle_state TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                generic_workers_alive INTEGER NOT NULL,
                listing_worker_alive INTEGER NOT NULL,
                generic_available_capacity INTEGER NOT NULL,
                listing_available_capacity INTEGER NOT NULL,
                available_capacity INTEGER NOT NULL,
                standby_capacity INTEGER NOT NULL,
                last_claim_at TEXT,
                last_progress_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO seller_sprite_task_queue VALUES (
                1, 'job-1', 'default', 'generic', 'running', ?, ?, NULL,
                'scheduler-a', ?, ?, 'fetching', ?, 9, NULL, NULL, 12,
                'secret-account', 'secret-credential', '{"token":"secret"}',
                'C:/secret/root', 'C:/secret/result', '{"trace":"secret"}'
            )
            """,
            (_iso(-600), _iso(-500), _iso(-10), _iso(60), _iso(-400)),
        )
        conn.executemany(
            "INSERT INTO seller_sprite_task_progress_events "
            "(job_id, progress_stage, progress_at, progress_sequence) VALUES (?, ?, ?, ?)",
            [
                ("job-1", "claimed", _iso(-500), 1),
                ("job-1", "fetching", _iso(-400), 9),
            ],
        )
        conn.execute(
            "INSERT INTO seller_sprite_runtime_heartbeats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "scheduler-a",
                "running",
                _iso(-10),
                1,
                1,
                1,
                1,
                2,
                1,
                _iso(-20),
                _iso(-10),
            ),
        )


def _repository(path: Path) -> ReadOnlySellerSpriteRepository:
    """创建使用固定时钟的只读仓储。"""
    return ReadOnlySellerSpriteRepository(
        path,
        policy=ClassificationPolicy(300, 300, 60, 2),
        clock=lambda: NOW,
    )


def test_snapshot_is_strictly_read_only_and_redacted(tmp_path: Path) -> None:
    """读取快照不得更改队列文件、schema、日志模式或泄露敏感字段。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    before_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    with sqlite3.connect(db_path) as conn:
        before_schema = conn.execute("PRAGMA user_version").fetchone()[0]
        before_journal = conn.execute("PRAGMA journal_mode").fetchone()[0]

    snapshot = _repository(db_path).snapshot()

    with sqlite3.connect(db_path) as conn:
        after_schema = conn.execute("PRAGMA user_version").fetchone()[0]
        after_journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert snapshot["source"] == {"ready": True, "error": None}
    assert snapshot["tasks"][0]["health"] == "stalled"
    assert snapshot["runtimes"][0]["execution_owner"] == "scheduler-a"
    assert snapshot["runtimes"][0]["generic_available_capacity"] == 1
    assert snapshot["runtimes"][0]["listing_available_capacity"] == 1
    serialized = repr(snapshot)
    for secret in (
        "secret-account",
        "secret-credential",
        "token",
        "C:/secret",
        "trace",
        "request_json",
        "error_json",
    ):
        assert secret not in serialized
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before_hash
    assert after_schema == before_schema == 77
    assert after_journal == before_journal
    assert not db_path.with_name(f"{db_path.name}-wal").exists()


def test_missing_file_or_schema_returns_clear_source_error_without_creation(tmp_path: Path) -> None:
    """数据源不存在或契约缺失时应明确未就绪，且绝不创建目录或迁移。"""
    missing = tmp_path / "missing" / "queue.sqlite3"
    missing_snapshot = _repository(missing).snapshot()

    assert missing_snapshot["source"]["ready"] is False
    assert missing_snapshot["source"]["error"]["code"] == "queue_source_unavailable"
    assert not missing.parent.exists()

    invalid = tmp_path / "invalid.sqlite3"
    with sqlite3.connect(invalid) as conn:
        conn.execute("CREATE TABLE seller_sprite_task_queue (job_id TEXT)")
    invalid_snapshot = _repository(invalid).snapshot()

    assert invalid_snapshot["source"]["ready"] is False
    assert invalid_snapshot["source"]["error"]["code"] == "queue_schema_invalid"
    assert "seller_sprite_task_progress_events" in invalid_snapshot["source"]["error"]["message"]


def test_list_tasks_filters_by_health_and_task_detail_has_timeline(tmp_path: Path) -> None:
    """任务列表支持健康过滤，详情只返回脱敏字段和有序进度时间线。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    repository = _repository(db_path)

    assert [item["job_id"] for item in repository.list_tasks(health="stalled")] == ["job-1"]
    assert repository.list_tasks(health="healthy") == []
    detail = repository.task_detail("job-1")

    assert detail["job_id"] == "job-1"
    assert detail["timeline"] == [
        {"progress_stage": "claimed", "progress_at": _iso(-500), "progress_sequence": 1},
        {"progress_stage": "fetching", "progress_at": _iso(-400), "progress_sequence": 9},
    ]
    assert "execution_owner" not in detail


def test_scan_includes_more_than_snapshot_cap_active_tasks_and_batches_timelines(
    tmp_path: Path,
) -> None:
    """扫描不得因展示上限漏掉活动任务，时间线应支持批量受限读取。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO seller_sprite_task_queue (
                id, job_id, queue_scope, task_kind, status, created_at,
                progress_sequence, row_count
            ) VALUES (?, ?, 'default', 'generic', 'queued', ?, 0, 0)
            """,
            [(index + 2, f"job-{index + 2}", _iso(-600)) for index in range(1100)],
        )
        conn.executemany(
            """
            INSERT INTO seller_sprite_task_progress_events (
                job_id, progress_stage, progress_at, progress_sequence
            ) VALUES (?, 'queued', ?, 1)
            """,
            [(f"job-{index + 2}", _iso(-600)) for index in range(1100)],
        )

    repository = _repository(db_path)
    tasks, _runtimes = repository.raw_observations()
    timelines = repository.timelines_for_jobs(
        [str(task["job_id"]) for task in tasks], timeline_limit=1
    )
    snapshot = repository.snapshot()

    assert len(tasks) == 1101
    assert len(timelines) == 1101
    assert snapshot["summary"]["total"] == 1101
    assert snapshot["summary"]["by_lifecycle"] == {"queued": 1100, "running": 1}
    assert len(snapshot["tasks"]) == 1000


def test_task_detail_uses_direct_lookup_without_rescanning_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    """单任务详情应直接读取白名单字段，不得重新生成完整快照。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    repository = _repository(db_path)
    monkeypatch.setattr(
        repository,
        "snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("不得调用 snapshot")),
    )

    detail = repository.task_detail("job-1")

    assert detail["job_id"] == "job-1"
    assert [item["progress_sequence"] for item in detail["timeline"]] == [1, 9]


def _fail_repository_queries_after_schema_validation(
    monkeypatch,
) -> None:
    """让真实连接只在固定 schema 校验完成后的业务查询失败。"""
    real_connect = sqlite3.connect

    class FailingConnection:
        def __init__(self, connection) -> None:
            self.connection = connection

        @property
        def row_factory(self):
            return self.connection.row_factory

        @row_factory.setter
        def row_factory(self, value) -> None:
            self.connection.row_factory = value

        def execute(self, statement, parameters=()):
            normalized = " ".join(str(statement).split())
            if normalized == "BEGIN" or (
                "FROM seller_sprite_" in normalized
                and "PRAGMA" not in normalized
            ):
                raise sqlite3.OperationalError("sensitive database detail")
            return self.connection.execute(statement, parameters)

        def close(self) -> None:
            self.connection.close()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.close()
            return False

    monkeypatch.setattr(
        "opscli.collector_monitor.repository.sqlite3.connect",
        lambda *args, **kwargs: FailingConnection(real_connect(*args, **kwargs)),
    )


def test_snapshot_wraps_read_error_after_schema_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """快照应把 schema 校验后的 SQLite 错误转为安全未就绪结果。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    _fail_repository_queries_after_schema_validation(monkeypatch)

    snapshot = _repository(db_path).snapshot()

    assert snapshot["source"]["ready"] is False
    assert snapshot["source"]["error"]["code"] == "queue_source_unavailable"
    assert "sensitive" not in repr(snapshot)


@pytest.mark.parametrize(
    "operation",
    [
        lambda repository: repository.task_detail("job-1"),
        lambda repository: repository.timelines_for_jobs(["job-1"]),
    ],
)
def test_direct_reads_wrap_error_after_schema_validation(
    tmp_path: Path,
    monkeypatch,
    operation,
) -> None:
    """详情和时间线读取也应抛出稳定 RepositorySourceError。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    _fail_repository_queries_after_schema_validation(monkeypatch)

    with pytest.raises(RepositorySourceError, match="只读访问失败") as exc_info:
        operation(_repository(db_path))

    assert exc_info.value.code == "queue_source_unavailable"
    assert "sensitive" not in str(exc_info.value)


def test_public_methods_report_invalid_filters_and_missing_tasks(tmp_path: Path) -> None:
    """无效过滤和不存在任务应通过稳定异常类型报告。"""
    db_path = tmp_path / "queue.sqlite3"
    _create_queue_db(db_path)
    repository = _repository(db_path)

    with pytest.raises(ValueError, match="health"):
        repository.list_tasks(health="unknown")
    with pytest.raises(TaskNotFoundError, match="job-missing"):
        repository.task_detail("job-missing")

    invalid = tmp_path / "invalid.sqlite3"
    invalid.touch()
    with pytest.raises(RepositorySourceError, match="schema"):
        _repository(invalid).list_tasks()
