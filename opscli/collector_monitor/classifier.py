"""任务与运行时观测的纯健康分类规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ClassificationPolicy:
    """分类阈值策略，单位均为秒。"""

    stalled_threshold: float
    queue_threshold: float
    runtime_stale_threshold: float
    orphan_required_scans: int = 2


@dataclass(frozen=True)
class ClassifiedTask:
    """单个任务的脱敏生命周期和健康分类。"""

    job_id: str
    queue_scope: str
    task_kind: str
    lifecycle: str
    health: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    progress_stage: str | None
    progress_at: str | None
    progress_sequence: int
    last_error_code: str | None
    retry_reason: str | None
    row_count: int
    age_seconds: float | None
    progress_age_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        """返回仅包含公开白名单字段的 JSON 结构。"""
        return {
            "job_id": self.job_id,
            "queue_scope": self.queue_scope,
            "task_kind": self.task_kind,
            "lifecycle": self.lifecycle,
            "health": self.health,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress_stage": self.progress_stage,
            "progress_at": self.progress_at,
            "progress_sequence": self.progress_sequence,
            "last_error_code": self.last_error_code,
            "retry_reason": self.retry_reason,
            "row_count": self.row_count,
            "age_seconds": self.age_seconds,
            "progress_age_seconds": self.progress_age_seconds,
        }


@dataclass(frozen=True)
class IncidentCandidate:
    """由一次纯评估产生的去重事故候选。"""

    rule: str
    subject: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """返回事故候选的公开结构。"""
        return {
            "rule": self.rule,
            "subject": self.subject,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class ClassifiedSnapshot:
    """一次分类后的任务、事故和摘要。"""

    tasks: tuple[ClassifiedTask, ...]
    incidents: tuple[IncidentCandidate, ...]
    summary: dict[str, Any]


def classify_snapshot(
    tasks: Sequence[Mapping[str, Any]],
    runtimes: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    policy: ClassificationPolicy,
    orphan_observations: Mapping[str, int] | None = None,
) -> ClassifiedSnapshot:
    """按任务、租约与调度器观测生成确定性的健康分类。"""
    current = _utc(now)
    observations = orphan_observations or {}
    runtime_by_owner = {
        str(runtime.get("execution_owner")): runtime
        for runtime in runtimes
        if runtime.get("execution_owner")
    }
    live_runtimes = [
        runtime
        for runtime in runtimes
        if _runtime_is_live(runtime, current, policy.runtime_stale_threshold)
    ]

    classified: list[ClassifiedTask] = []
    incidents: dict[tuple[str, str], IncidentCandidate] = {}
    for task in tasks:
        lifecycle = str(task.get("status") or "unknown").lower()
        job_id = str(task.get("job_id") or "")
        queue_scope = str(task.get("queue_scope") or "default")
        task_kind = str(task.get("task_kind") or "generic")
        created_age = _age(task.get("created_at"), current)
        progress_at = task.get("progress_at") or task.get("started_at")
        progress_age = _age(progress_at, current)
        health = "healthy"

        if lifecycle == "running":
            owner = str(task.get("execution_owner") or "")
            runtime = runtime_by_owner.get(owner)
            lease_expired = _is_past(task.get("lease_expires_at"), current)
            owner_unavailable = not owner or runtime is None or not _runtime_is_live(
                runtime,
                current,
                policy.runtime_stale_threshold,
            )
            if lease_expired or owner_unavailable:
                observation_count = _integer(observations.get(job_id))
                if observation_count >= policy.orphan_required_scans:
                    health = "orphaned"
                    incidents[("orphaned", job_id)] = IncidentCandidate(
                        rule="orphaned",
                        subject=job_id,
                        severity="critical",
                        message="运行任务的租约或执行所有者已失效",
                    )
                else:
                    health = "slow"
            elif progress_age is None or progress_age >= policy.stalled_threshold:
                health = "stalled"
                incidents[("stalled", job_id)] = IncidentCandidate(
                    rule="stalled",
                    subject=job_id,
                    severity="high",
                    message="运行任务长时间没有进度更新",
                )
            elif progress_age >= policy.stalled_threshold / 2:
                # 仅以最近进度年龄判断 slow，长任务持续推进时仍属于健康。
                health = "slow"

        elif lifecycle == "queued" and created_age is not None:
            if created_age >= policy.queue_threshold:
                matching = [
                    runtime
                    for runtime in live_runtimes
                    if _has_matching_capacity(runtime, task_kind)
                ]
                subject = f"{queue_scope}:{task_kind}"
                if not matching:
                    health = "worker_unavailable"
                    incidents[("worker_unavailable", subject)] = IncidentCandidate(
                        rule="worker_unavailable",
                        subject=subject,
                        severity="critical",
                        message="队列存在等待任务但调度器不可用或匹配容量为零",
                    )
                elif not any(
                    _has_recent_activity(runtime, current, policy.queue_threshold)
                    for runtime in matching
                ):
                    health = "queue_starved"
                    incidents[("queue_starved", subject)] = IncidentCandidate(
                        rule="queue_starved",
                        subject=subject,
                        severity="high",
                        message="队列有匹配容量但长时间没有任务领取或进度",
                    )
                else:
                    health = "slow"
            elif created_age >= policy.queue_threshold / 2:
                health = "slow"

        classified.append(
            ClassifiedTask(
                job_id=job_id,
                queue_scope=queue_scope,
                task_kind=task_kind,
                lifecycle=lifecycle,
                health=health,
                created_at=_optional_string(task.get("created_at")),
                started_at=_optional_string(task.get("started_at")),
                finished_at=_optional_string(task.get("finished_at")),
                progress_stage=_optional_string(task.get("progress_stage")),
                progress_at=_optional_string(task.get("progress_at")),
                progress_sequence=_integer(task.get("progress_sequence")),
                last_error_code=_optional_string(task.get("last_error_code")),
                retry_reason=_optional_string(task.get("retry_reason")),
                row_count=_integer(task.get("row_count")),
                age_seconds=created_age,
                progress_age_seconds=progress_age,
            )
        )

    health_counts: dict[str, int] = {}
    lifecycle_counts: dict[str, int] = {}
    for item in classified:
        health_counts[item.health] = health_counts.get(item.health, 0) + 1
        lifecycle_counts[item.lifecycle] = lifecycle_counts.get(item.lifecycle, 0) + 1
    return ClassifiedSnapshot(
        tasks=tuple(classified),
        incidents=tuple(incidents.values()),
        summary={
            "total": len(classified),
            "by_lifecycle": lifecycle_counts,
            "by_health": health_counts,
            "active_incident_count": len(incidents),
        },
    )


def orphan_candidates(
    tasks: Sequence[Mapping[str, Any]],
    runtimes: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    runtime_stale_threshold: float,
) -> set[str]:
    """返回本轮满足孤儿前置条件的运行任务标识。"""
    current = _utc(now)
    runtime_by_owner = {
        str(runtime.get("execution_owner")): runtime
        for runtime in runtimes
        if runtime.get("execution_owner")
    }
    candidates: set[str] = set()
    for task in tasks:
        if str(task.get("status")) != "running":
            continue
        owner = str(task.get("execution_owner") or "")
        runtime = runtime_by_owner.get(owner)
        if (
            _is_past(task.get("lease_expires_at"), current)
            or not owner
            or runtime is None
            or not _runtime_is_live(runtime, current, runtime_stale_threshold)
        ):
            job_id = str(task.get("job_id") or "")
            if job_id:
                candidates.add(job_id)
    return candidates


def _runtime_is_live(
    runtime: Mapping[str, Any],
    now: datetime,
    stale_threshold: float,
) -> bool:
    """判断调度器生命周期与心跳是否同时存活。"""
    lifecycle = str(runtime.get("lifecycle_state") or "").lower()
    age = _age(runtime.get("heartbeat_at"), now)
    return (
        lifecycle in {"running", "ready", "healthy"}
        and age is not None
        and age < stale_threshold
    )


def _has_matching_capacity(runtime: Mapping[str, Any], task_kind: str) -> bool:
    """判断运行时是否具有任务类型匹配的存活工作槽和可用容量。"""
    capacity_field = (
        "listing_available_capacity"
        if task_kind == "listing_analysis"
        else "generic_available_capacity"
    )
    return _integer(runtime.get(capacity_field)) > 0


def _has_recent_activity(
    runtime: Mapping[str, Any],
    now: datetime,
    threshold: float,
) -> bool:
    """判断最近领取或进度是否仍在队列观察窗口内。"""
    ages = [
        age
        for age in (
            _age(runtime.get("last_claim_at"), now),
            _age(runtime.get("last_progress_at"), now),
        )
        if age is not None
    ]
    return bool(ages) and min(ages) < threshold


def _is_past(value: Any, now: datetime) -> bool:
    """判断时间是否为空或已经过去。"""
    parsed = _parse_time(value)
    return parsed is None or parsed <= now


def _age(value: Any, now: datetime) -> float | None:
    """计算非负时间年龄。"""
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _parse_time(value: Any) -> datetime | None:
    """宽容解析 SQLite 中的 ISO 时间字符串。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _utc(parsed)


def _utc(value: datetime) -> datetime:
    """统一时间到 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_string(value: Any) -> str | None:
    """将可选数据库值转换为字符串。"""
    return str(value) if value is not None else None


def _integer(value: Any) -> int:
    """将数据库数值安全转换为整数。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
