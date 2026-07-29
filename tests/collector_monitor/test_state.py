"""监控状态库事故生命周期契约测试。"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opscli.collector_monitor.classifier import IncidentCandidate
from opscli.collector_monitor.state import IncidentAction, MonitorStateStore

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)
INCIDENT = IncidentCandidate("stalled", "job-1", "high", "任务没有进度")


def test_consecutive_observations_increment_and_reset(tmp_path: Path) -> None:
    """连续观测只对本轮仍存在的对象递增，消失后必须重置。"""
    store = MonitorStateStore(tmp_path / "state.sqlite3", cooldown_seconds=1800)

    assert store.observe_consecutive("orphaned", {"job-1"}) == {"job-1": 1}
    assert store.observe_consecutive("orphaned", {"job-1"}) == {"job-1": 2}
    assert store.observe_consecutive("orphaned", set()) == {}
    assert store.observe_consecutive("orphaned", {"job-1"}) == {"job-1": 1}


def test_incident_opening_dedupe_cooldown_and_recovery_once(tmp_path: Path) -> None:
    """事故应按规则和对象去重，冷却后提醒，并仅成功恢复一次。"""
    store = MonitorStateStore(tmp_path / "state.sqlite3", cooldown_seconds=1800)

    opening = store.reconcile([INCIDENT], now=NOW)
    assert [(item.kind, item.rule, item.subject) for item in opening] == [
        ("opening", "stalled", "job-1")
    ]
    store.record_delivery(opening[0], success=True, now=NOW)
    assert store.reconcile([INCIDENT], now=NOW + timedelta(seconds=5)) == []

    assert store.reconcile([INCIDENT], now=NOW + timedelta(seconds=1799)) == []
    reminder = store.reconcile([INCIDENT], now=NOW + timedelta(seconds=1800))
    assert [item.kind for item in reminder] == ["reminder"]
    store.record_delivery(reminder[0], success=True)

    recovery = store.reconcile([], now=NOW + timedelta(seconds=1801))
    assert [item.kind for item in recovery] == ["recovery"]
    assert store.reconcile([], now=NOW + timedelta(seconds=1900)) == []
    store.record_delivery(recovery[0], success=True)
    assert store.reconcile([], now=NOW + timedelta(seconds=2000)) == []

    incidents = store.list_incidents()
    assert incidents[0]["status"] == "resolved"
    assert incidents[0]["alert_status"] == "delivered"
    assert incidents[0]["recovery_status"] == "delivered"


def test_open_escalation_reminder_and_recovery_are_preserved(tmp_path: Path) -> None:
    """事故严重度升高必须通知，随后仍支持提醒和一次成功恢复。"""
    store = MonitorStateStore(tmp_path / "state.sqlite3", cooldown_seconds=1800)
    low = IncidentCandidate("stalled", "job-1", "medium", "任务进度偏慢")

    opening = store.reconcile([low], now=NOW)[0]
    store.record_delivery(opening, success=True, now=NOW)
    escalation = store.reconcile([INCIDENT], now=NOW + timedelta(seconds=1))[0]
    assert escalation.kind == "escalation"
    store.record_delivery(escalation, success=True, now=NOW + timedelta(seconds=1))

    reminder = store.reconcile([INCIDENT], now=NOW + timedelta(seconds=1801))[0]
    assert reminder.kind == "reminder"
    store.record_delivery(reminder, success=True, now=NOW + timedelta(seconds=1801))
    recovery = store.reconcile([], now=NOW + timedelta(seconds=1802))[0]
    assert recovery.kind == "recovery"
    store.record_delivery(recovery, success=True, now=NOW + timedelta(seconds=1802))
    assert store.reconcile([], now=NOW + timedelta(seconds=4000)) == []


def test_failed_delivery_is_retryable_and_error_class_is_sanitized(tmp_path: Path) -> None:
    """通知失败不影响事故持久化，且状态库只能保存安全错误类名。"""
    store = MonitorStateStore(tmp_path / "state.sqlite3", cooldown_seconds=1800)
    action = store.reconcile([INCIDENT], now=NOW)[0]

    store.record_delivery(
        action,
        success=False,
        error_class="credential-detail RuntimeError",
    )
    retry = store.reconcile([INCIDENT], now=NOW + timedelta(seconds=1))

    assert retry == [
        IncidentAction("opening", "stalled", "job-1", "high", "任务没有进度")
    ]
    stored = store.list_incidents()[0]
    assert stored["delivery_error_class"] == "RuntimeError"
    assert "secret" not in repr(stored)


def test_disabled_delivery_is_terminal_and_not_retried(tmp_path: Path) -> None:
    """未配置通知时应持久化 disabled，后续轮询不再重复投递。"""
    store = MonitorStateStore(tmp_path / "state.sqlite3", cooldown_seconds=60)
    opening = store.reconcile([INCIDENT], now=NOW)[0]

    store.record_delivery(
        opening,
        success=True,
        result="disabled",
        now=NOW,
    )

    assert store.reconcile([INCIDENT], now=NOW + timedelta(seconds=3600)) == []
    stored = store.list_incidents()[0]
    assert stored["alert_status"] == "disabled"
    assert stored["delivery_result"] == "disabled"
    assert stored["delivery_error_class"] is None


def test_state_store_rejects_queue_database_hard_link_without_mutation(
    tmp_path: Path,
) -> None:
    """写连接必须复核物理文件身份，拒绝修改业务队列硬链接。"""
    queue_path = tmp_path / "queue.sqlite3"
    state_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(queue_path) as conn:
        conn.execute("PRAGMA user_version = 77")
        conn.execute("CREATE TABLE queue_data (value TEXT)")
        conn.execute("INSERT INTO queue_data VALUES ('original')")
    before_hash = hashlib.sha256(queue_path.read_bytes()).hexdigest()
    state_path.hardlink_to(queue_path)

    with pytest.raises(ValueError, match="must not reference the queue database"):
        MonitorStateStore(
            state_path,
            cooldown_seconds=60,
            protected_db_path=queue_path,
        )

    assert hashlib.sha256(queue_path.read_bytes()).hexdigest() == before_hash
    with sqlite3.connect(queue_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 77
        assert conn.execute("SELECT value FROM queue_data").fetchone()[0] == "original"


def test_state_store_accepts_distinct_database_with_same_empty_schema(
    tmp_path: Path,
) -> None:
    """独立数据库即使 schema 相同，也不得被误判为业务库别名。"""
    queue_path = tmp_path / "queue.sqlite3"
    state_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(queue_path):
        pass

    MonitorStateStore(
        state_path,
        cooldown_seconds=60,
        protected_db_path=queue_path,
    )

    with sqlite3.connect(state_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_state_store_rejects_queue_database_opened_during_path_swap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """路径在 connect 前后切换时，必须校验连接实际绑定的数据库。"""
    queue_path = tmp_path / "queue.sqlite3"
    state_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(queue_path) as conn:
        conn.execute("PRAGMA user_version = 77")
        conn.execute("CREATE TABLE seller_sprite_task_queue (job_id TEXT)")
        conn.execute("INSERT INTO seller_sprite_task_queue VALUES ('original')")
    state_path.write_bytes(b"")
    before_hash = hashlib.sha256(queue_path.read_bytes()).hexdigest()
    real_connect = sqlite3.connect
    swapped = False

    def connect_with_path_swap(database, *args, **kwargs):
        nonlocal swapped
        target = Path(str(database))
        if target == state_path and not swapped:
            swapped = True
            return real_connect(queue_path, *args, **kwargs)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(
        "opscli.collector_monitor.state.sqlite3.connect",
        connect_with_path_swap,
    )

    with pytest.raises(ValueError, match="must not reference the queue database"):
        MonitorStateStore(
            state_path,
            cooldown_seconds=60,
            protected_db_path=queue_path,
        )

    assert hashlib.sha256(queue_path.read_bytes()).hexdigest() == before_hash
    with real_connect(queue_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 77
        assert conn.execute(
            "SELECT job_id FROM seller_sprite_task_queue"
        ).fetchone()[0] == "original"


def test_failed_recovery_retries_after_cooldown_then_stops(tmp_path: Path) -> None:
    """恢复投递失败应在冷却后重试，成功后不得重复发送。"""
    store = MonitorStateStore(tmp_path / "state.sqlite3", cooldown_seconds=60)
    opening = store.reconcile([INCIDENT], now=NOW)[0]
    store.record_delivery(opening, success=True, now=NOW)
    recovery = store.reconcile([], now=NOW + timedelta(seconds=1))[0]
    store.record_delivery(
        recovery,
        success=False,
        error_class="https://secret.example RuntimeError",
        now=NOW + timedelta(seconds=1),
    )

    assert store.reconcile([], now=NOW + timedelta(seconds=60)) == []
    retry = store.reconcile([], now=NOW + timedelta(seconds=61))
    assert retry == [recovery]
    store.record_delivery(retry[0], success=True, now=NOW + timedelta(seconds=61))
    assert store.reconcile([], now=NOW + timedelta(seconds=3600)) == []
    stored = store.list_incidents()[0]
    assert stored["recovery_status"] == "delivered"
    assert stored["delivery_error_class"] is None
    assert "secret" not in repr(stored)
