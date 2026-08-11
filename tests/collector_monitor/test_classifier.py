"""Collector Monitor 纯分类器契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from opscli.collector_monitor.classifier import ClassificationPolicy, classify_snapshot

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)


def _iso(seconds: float) -> str:
    """返回相对固定时刻的 ISO 时间。"""
    return (NOW + timedelta(seconds=seconds)).isoformat()


def _runtime(**overrides):
    """构造存活且有容量的调度器观测。"""
    value = {
        "execution_owner": "scheduler-a",
        "lifecycle_state": "running",
        "heartbeat_at": _iso(-10),
        "generic_workers_alive": 1,
        "listing_worker_alive": 1,
        "generic_available_capacity": 1,
        "listing_available_capacity": 1,
        "available_capacity": 2,
        "standby_capacity": 1,
        "last_claim_at": _iso(-10),
        "last_progress_at": _iso(-10),
    }
    value.update(overrides)
    return value


def _task(**overrides):
    """构造正在运行且持续推进的任务观测。"""
    value = {
        "job_id": "job-1",
        "queue_scope": "default",
        "task_kind": "generic",
        "status": "running",
        "created_at": _iso(-600),
        "started_at": _iso(-500),
        "finished_at": None,
        "execution_owner": "scheduler-a",
        "heartbeat_at": _iso(-10),
        "lease_expires_at": _iso(60),
        "progress_stage": "fetching",
        "progress_at": _iso(-10),
        "progress_sequence": 3,
        "last_error_code": None,
        "retry_reason": None,
        "row_count": 0,
    }
    value.update(overrides)
    return value


POLICY = ClassificationPolicy(
    stalled_threshold=300,
    queue_threshold=300,
    runtime_stale_threshold=60,
    orphan_required_scans=2,
)


def test_running_task_with_live_lease_and_fresh_progress_is_healthy() -> None:
    """存活租约、运行时和新鲜进度共同表示健康运行。"""
    result = classify_snapshot([_task()], [_runtime()], now=NOW, policy=POLICY)

    assert result.tasks[0].lifecycle == "running"
    assert result.tasks[0].health == "healthy"
    assert result.incidents == ()


def test_live_running_task_becomes_slow_then_stalled_by_progress_age() -> None:
    """运行任务应根据进度年龄区分慢速与停滞。"""
    slow = classify_snapshot(
        [_task(progress_at=_iso(-200))], [_runtime()], now=NOW, policy=POLICY
    )
    stalled = classify_snapshot(
        [_task(progress_at=_iso(-301))], [_runtime()], now=NOW, policy=POLICY
    )

    assert slow.tasks[0].health == "slow"
    assert stalled.tasks[0].health == "stalled"
    assert stalled.incidents[0].rule == "stalled"
    assert stalled.incidents[0].subject == "job-1"


def test_orphan_requires_consecutive_confirmations() -> None:
    """过期租约必须连续观测达到阈值后才确认孤儿任务。"""
    task = _task(lease_expires_at=_iso(-1))

    first = classify_snapshot(
        [task],
        [_runtime()],
        now=NOW,
        policy=POLICY,
        orphan_observations={"job-1": 1},
    )
    second = classify_snapshot(
        [task],
        [_runtime()],
        now=NOW,
        policy=POLICY,
        orphan_observations={"job-1": 2},
    )

    assert first.tasks[0].health == "slow"
    assert first.incidents == ()
    assert second.tasks[0].health == "orphaned"
    assert second.incidents[0].rule == "orphaned"


def test_queued_task_distinguishes_starvation_and_worker_unavailable() -> None:
    """有容量但不领取为饥饿，无运行调度器为工作器不可用。"""
    queued = _task(
        status="queued",
        started_at=None,
        execution_owner=None,
        heartbeat_at=None,
        lease_expires_at=None,
        progress_at=None,
        progress_sequence=0,
        created_at=_iso(-400),
    )
    starved = classify_snapshot(
        [queued],
        [_runtime(last_claim_at=_iso(-400), last_progress_at=_iso(-400))],
        now=NOW,
        policy=POLICY,
    )
    unavailable = classify_snapshot(
        [queued],
        [_runtime(heartbeat_at=_iso(-120))],
        now=NOW,
        policy=POLICY,
    )

    assert starved.tasks[0].health == "queue_starved"
    assert [(item.rule, item.subject) for item in starved.incidents] == [
        ("queue_starved", "default:generic")
    ]
    assert unavailable.tasks[0].health == "worker_unavailable"
    assert unavailable.incidents[0].rule == "worker_unavailable"


def test_runtime_at_stale_threshold_is_not_live() -> None:
    """运行时心跳达到失联阈值时必须按不可用处理。"""
    queued = _task(
        status="queued",
        started_at=None,
        execution_owner=None,
        heartbeat_at=None,
        lease_expires_at=None,
        progress_at=None,
        progress_sequence=0,
        created_at=_iso(-400),
    )

    result = classify_snapshot(
        [queued],
        [_runtime(heartbeat_at=_iso(-60))],
        now=NOW,
        policy=POLICY,
    )

    assert result.tasks[0].health == "worker_unavailable"


def test_matching_capacity_is_task_kind_specific() -> None:
    """其他类型空闲槽不得掩盖目标工作槽已占满。"""
    queued = _task(
        status="queued",
        started_at=None,
        execution_owner=None,
        heartbeat_at=None,
        lease_expires_at=None,
        progress_at=None,
        progress_sequence=0,
        created_at=_iso(-400),
    )
    runtime = _runtime(
        generic_available_capacity=0,
        listing_available_capacity=1,
        available_capacity=1,
    )

    generic = classify_snapshot([queued], [runtime], now=NOW, policy=POLICY)
    listing = classify_snapshot(
        [{**queued, "job_id": "listing-1", "task_kind": "listing_analysis"}],
        [runtime],
        now=NOW,
        policy=POLICY,
    )

    assert generic.tasks[0].health == "worker_unavailable"
    assert listing.tasks[0].health == "slow"


def test_recent_scheduler_activity_prevents_false_queue_starvation() -> None:
    """调度器近期仍在领取或推进时，旧排队任务不应误报队列饥饿。"""
    queued = _task(
        status="queued",
        started_at=None,
        execution_owner=None,
        heartbeat_at=None,
        lease_expires_at=None,
        progress_at=None,
        progress_sequence=0,
        created_at=_iso(-400),
    )

    result = classify_snapshot(
        [queued],
        [_runtime(last_claim_at=_iso(-5), last_progress_at=_iso(-5))],
        now=NOW,
        policy=POLICY,
    )

    assert result.tasks[0].health == "slow"
    assert result.incidents == ()


def test_empty_queue_never_creates_queue_incident() -> None:
    """即使调度器离线，空队列也不应制造事故。"""
    result = classify_snapshot([], [], now=NOW, policy=POLICY)

    assert result.tasks == ()
    assert result.incidents == ()
    assert result.summary["total"] == 0
