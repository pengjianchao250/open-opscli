"""Collector Monitor 轮询编排与缓存快照。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Protocol

from opscli.collector_monitor.classifier import (
    ClassificationPolicy,
    classify_snapshot,
    orphan_candidates,
)
from opscli.collector_monitor.config import MonitorSettings, read_protected_text
from opscli.collector_monitor.repository import RepositorySourceError, ScanObservations
from opscli.collector_monitor.state import IncidentAction, MonitorStateStore
from opscli.mcp_client import RemoteMcpClient

_INCIDENT_CACHE_LIMIT = 500
_NOTIFICATION_CONCURRENCY = 4
_COLLECTOR_CHECK_FIELDS = ("queue", "scheduler")
_COLLECTOR_RUNTIME_FIELDS = (
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
    "heartbeat_fresh",
)


class _Repository(Protocol):
    """轮询服务所需的最小只读仓储协议。"""

    def scan_observations(self) -> ScanObservations: ...

    def timelines_for_jobs(
        self, job_ids: list[str], *, timeline_limit: int = 200
    ) -> dict[str, list[dict[str, Any]]]: ...


class _Notifier(Protocol):
    """轮询服务所需的通知协议。"""

    def send(self, action: Any) -> dict[str, Any]: ...


class CollectorMonitorService:
    """读取本地队列、评估事故、通知并缓存只读快照。"""

    def __init__(
        self,
        settings: MonitorSettings,
        *,
        repository: _Repository,
        state_store: MonitorStateStore,
        notifier: _Notifier,
        collector_probe: Callable[[MonitorSettings], Awaitable[dict[str, Any]]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.state_store = state_store
        self.notifier = notifier
        self.collector_probe = collector_probe or probe_collector
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._collector = {
            "enabled": bool(settings.collector_mcp_url),
            "status": "pending" if settings.collector_mcp_url else "not_configured",
            "modules": [],
            "error_class": None,
        }
        self._snapshot = _empty_snapshot("not_polled", "监控服务尚未完成首次扫描")
        self._snapshot["collector"] = dict(self._collector)
        self._details: dict[str, dict[str, Any]] = {}

    @property
    def cached_snapshot(self) -> dict[str, Any]:
        """返回当前内存缓存快照。"""
        return self._snapshot

    @property
    def is_ready(self) -> bool:
        """仅当首次本地队列扫描成功后报告就绪。"""
        return bool(self._snapshot.get("source", {}).get("ready"))

    async def poll_once(self) -> dict[str, Any]:
        """执行一次本地扫描、分类和事故更新，并刷新只读缓存。"""
        now = self.clock()
        try:
            observations = await asyncio.to_thread(self.repository.scan_observations)
        except RepositorySourceError as exc:
            return await self._cache_source_error(exc.code, exc.safe_message, now=now)
        except Exception as exc:
            return await self._cache_source_error(
                "queue_source_unavailable",
                f"SellerSprite 队列只读扫描失败（{type(exc).__name__}）",
                now=now,
            )

        try:
            prepared = await asyncio.to_thread(
                self._evaluate_observations,
                observations,
                now,
            )
            await self._deliver_actions(prepared["actions"], now=now)
            state = await asyncio.to_thread(self._complete_scan_state, now)
        except Exception as exc:
            return await self._cache_source_error(
                "monitor_state_unavailable",
                f"Collector Monitor 状态更新失败（{type(exc).__name__}）",
                now=now,
            )

        summary = prepared["summary"]
        summary["active_incident_count"] = state["active_incident_count"]
        snapshot = {
            "generated_at": _iso(now),
            "source": {"ready": True, "error": None, **state["scan_status"]},
            "collector": dict(self._collector),
            "summary": summary,
            "tasks": prepared["tasks"],
            "runtimes": prepared["runtimes"],
            "incidents": state["incidents"],
        }
        self._details = prepared["details"]
        self._snapshot = snapshot
        return snapshot

    def _evaluate_observations(
        self,
        observations: ScanObservations,
        now: datetime,
    ) -> dict[str, Any]:
        """在线程边界内完成分类、事故事务和任务时间线读取。"""
        tasks = list(observations.tasks)
        runtimes = list(observations.runtimes)
        candidates = orphan_candidates(
            tasks,
            runtimes,
            now=now,
            runtime_stale_threshold=self.settings.runtime_stale_threshold,
        )
        orphan_observations = self.state_store.observe_consecutive(
            "orphaned",
            candidates,
        )
        classified = classify_snapshot(
            tasks,
            runtimes,
            now=now,
            policy=ClassificationPolicy(
                stalled_threshold=self.settings.stalled_threshold,
                queue_threshold=self.settings.queue_threshold,
                runtime_stale_threshold=self.settings.runtime_stale_threshold,
                orphan_required_scans=self.settings.orphan_required_scans,
            ),
            orphan_observations=orphan_observations,
        )
        actions = self.state_store.reconcile(classified.incidents, now=now)
        public_tasks = [
            task.to_dict()
            for task in classified.tasks[: observations.public_task_limit]
        ]
        job_ids = [str(task["job_id"]) for task in public_tasks]
        try:
            timelines = self.repository.timelines_for_jobs(job_ids)
        except Exception:
            timelines = {}
        return {
            "actions": actions,
            "tasks": public_tasks,
            "runtimes": [_runtime_to_public(runtime) for runtime in runtimes],
            "details": {
                job_id: {**task, "timeline": timelines.get(job_id, [])}
                for job_id, task in zip(job_ids, public_tasks)
            },
            "summary": _complete_summary(classified.summary, observations),
        }

    def _complete_scan_state(self, now: datetime) -> dict[str, Any]:
        """在线程边界内提交扫描结果并读取事故缓存。"""
        self.state_store.record_scan(success=True, now=now, error_code=None)
        return {
            "scan_status": self.state_store.scan_status(),
            "incidents": self.state_store.list_incidents(limit=_INCIDENT_CACHE_LIMIT),
            "active_incident_count": self.state_store.count_incidents(status="active"),
        }

    async def _deliver_actions(
        self,
        actions: list[IncidentAction],
        *,
        now: datetime,
    ) -> None:
        """在线程中有界并发通知，并在线程边界内保存安全投递结果。"""
        semaphore = asyncio.Semaphore(_NOTIFICATION_CONCURRENCY)

        async def deliver(action: IncidentAction) -> tuple[IncidentAction, dict[str, Any]]:
            async with semaphore:
                try:
                    result = await asyncio.to_thread(self.notifier.send, action)
                except Exception as exc:
                    result = {"sent": False, "error_class": type(exc).__name__}
                return action, result if isinstance(result, dict) else {
                    "sent": False,
                    "error_class": "NotificationError",
                }

        delivered = await asyncio.gather(*(deliver(action) for action in actions))
        await asyncio.to_thread(self._record_deliveries, delivered, now)

    def _record_deliveries(
        self,
        delivered: list[tuple[IncidentAction, dict[str, Any]]],
        now: datetime,
    ) -> None:
        """顺序写入通知结果，避免并发 SQLite 写事务互相争锁。"""
        for action, result in delivered:
            disabled = bool(result.get("disabled"))
            sent = bool(result.get("sent"))
            self.state_store.record_delivery(
                action,
                success=sent or disabled,
                error_class=None
                if disabled
                else _optional_string(result.get("error_class")),
                result="disabled" if disabled else ("sent" if sent else "failed"),
                now=now,
            )

    async def _cache_source_error(
        self,
        code: str,
        message: str,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        """在线程中记录扫描失败，并缓存不触发事故恢复的安全快照。"""
        snapshot = await asyncio.to_thread(
            self._build_source_error_snapshot,
            code,
            message,
            now,
        )
        self._snapshot = snapshot
        self._details = {}
        return snapshot

    def _build_source_error_snapshot(
        self,
        code: str,
        message: str,
        now: datetime,
    ) -> dict[str, Any]:
        """持久化扫描失败并构造保留既有事故的安全快照。"""
        snapshot = _empty_snapshot(code, message, now=now)
        snapshot["collector"] = dict(self._collector)
        try:
            self.state_store.record_scan(success=False, now=now, error_code=code)
            snapshot["source"].update(self.state_store.scan_status())
            snapshot["incidents"] = self.state_store.list_incidents(
                limit=_INCIDENT_CACHE_LIMIT
            )
            snapshot["summary"]["active_incident_count"] = (
                self.state_store.count_incidents(status="active")
            )
        except Exception:
            # 状态库本身不可用时仍需发布安全未就绪快照，不能让后台轮询永久退出。
            snapshot["source"].update(
                {
                    "last_scan_at": _iso(now),
                    "last_success_at": None,
                    "error_code": code,
                }
            )
        return snapshot

    def task_detail(self, job_id: str) -> dict[str, Any]:
        """从本轮缓存读取任务详情，避免 API 请求访问业务队列。"""
        normalized = str(job_id).strip()
        if normalized not in self._details:
            raise KeyError(normalized)
        return self._details[normalized]

    async def probe_once(self) -> dict[str, Any]:
        """独立刷新 Collector 状态，失败不会改变本地队列就绪性。"""
        self._collector = await _safe_probe_call(self.collector_probe, self.settings)
        self._snapshot["collector"] = dict(self._collector)
        return dict(self._collector)

    async def run(
        self,
        stop_event: asyncio.Event,
        *,
        poll_immediately: bool = True,
    ) -> None:
        """分别运行本地高频扫描和 Collector 低频探测。"""
        probe_task = asyncio.create_task(self._run_probe_loop(stop_event))
        should_poll = poll_immediately
        try:
            while not stop_event.is_set():
                if should_poll:
                    await self.poll_once()
                should_poll = True
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self.settings.poll_interval,
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            stop_event.set()
            await probe_task

    async def _run_probe_loop(self, stop_event: asyncio.Event) -> None:
        """以不低于一分钟的独立节拍刷新远端探测缓存。"""
        while not stop_event.is_set():
            await self.probe_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=max(60.0, self.settings.poll_interval))
            except asyncio.TimeoutError:
                continue


async def probe_collector(settings: MonitorSettings) -> dict[str, Any]:
    """使用有界总超时探测可选 Collector MCP 健康工具。"""
    if not settings.collector_mcp_url:
        return {
            "enabled": False,
            "status": "not_configured",
            "modules": [],
            "error_class": None,
        }
    try:
        response = await asyncio.wait_for(
            _probe_collector_with_credentials(settings),
            timeout=settings.collector_probe_timeout,
        )
        data = response.get("data") if isinstance(response, Mapping) else None
        if not isinstance(data, Mapping):
            raise ValueError("Collector MCP 健康响应缺少 data")
        return _public_collector_result(data)
    except Exception as exc:
        return {
            "enabled": True,
            "status": "unavailable",
            "modules": [],
            "error_class": type(exc).__name__,
        }


async def _probe_collector_with_credentials(
    settings: MonitorSettings,
) -> dict[str, Any]:
    """在线程中读取密钥，并禁止携带自定义密钥跟随重定向。"""
    headers = None
    if settings.collector_mcp_api_key_file is not None:
        api_key = await asyncio.to_thread(
            read_protected_text,
            settings.collector_mcp_api_key_file,
        )
        if not api_key:
            raise ValueError("Collector MCP API Key 文件为空")
        headers = {"X-MCP-API-Key": api_key}
    client = RemoteMcpClient(
        str(settings.collector_mcp_url),
        headers=headers,
        follow_redirects=headers is None,
    )
    return await client.call_tool("collector_modules_health", {})


async def _safe_probe_call(
    probe: Callable[[MonitorSettings], Awaitable[dict[str, Any]]],
    settings: MonitorSettings,
) -> dict[str, Any]:
    """确保自定义探测器异常或任意字段不会破坏本地队列扫描。"""
    try:
        result = await probe(settings)
        if not isinstance(result, Mapping):
            raise ValueError("Collector 探测结果不是对象")
        enabled = bool(result.get("enabled", True))
        if not enabled:
            return {
                "enabled": False,
                "status": "not_configured",
                "modules": [],
                "error_class": None,
            }
        return _public_collector_result(result)
    except Exception as exc:
        return {
            "enabled": True,
            "status": "unavailable",
            "modules": [],
            "error_class": type(exc).__name__,
        }


def _public_collector_result(data: Mapping[str, Any]) -> dict[str, Any]:
    """将 Collector 响应压缩到固定模块、检查和运行态字段。"""
    modules = data.get("modules")
    source_modules = modules if isinstance(modules, list) else []
    return {
        "enabled": True,
        "status": _safe_state(data.get("status"), default="unknown"),
        "modules": [
            public
            for module in source_modules
            for public in [_public_collector_module(module)]
            if public is not None
        ],
        "error_class": _safe_error_class(data.get("error_class")),
    }


def _public_collector_module(value: Any) -> dict[str, Any] | None:
    """只接收公开 Collector 模块合同中的固定字段。"""
    if not isinstance(value, Mapping):
        return None
    bundle_id = _safe_state(value.get("bundle_id"), default="")
    if not bundle_id:
        return None
    result: dict[str, Any] = {
        "bundle_id": bundle_id,
        "status": _safe_state(value.get("status"), default="unknown"),
    }
    checks = value.get("checks")
    if isinstance(checks, Mapping):
        result["checks"] = {
            field: _safe_state(checks.get(field), default="unknown")
            for field in _COLLECTOR_CHECK_FIELDS
            if field in checks
        }
    runtime = value.get("runtime")
    if isinstance(runtime, Mapping):
        public_runtime: dict[str, Any] = {}
        for field in _COLLECTOR_RUNTIME_FIELDS:
            if field not in runtime:
                continue
            item = runtime[field]
            if field.endswith("_capacity") or field.endswith("_alive"):
                public_runtime[field] = max(0, _integer(item))
            elif field == "heartbeat_fresh":
                public_runtime[field] = bool(item)
            elif field in {"heartbeat_at", "last_claim_at", "last_progress_at"}:
                public_runtime[field] = _safe_timestamp(item)
            else:
                public_runtime[field] = _safe_state(item, default="unknown")
        result["runtime"] = public_runtime
    return result


def _safe_state(value: Any, *, default: str) -> str:
    """只允许低敏标识符进入 Collector 公开状态。"""
    normalized = str(value or "").strip().lower()
    if not normalized or len(normalized) > 64:
        return default
    return (
        normalized
        if all(character.isalnum() or character in {"_", "-"} for character in normalized)
        else default
    )


def _safe_error_class(value: Any) -> str | None:
    """只允许 Python 风格异常类名进入公开探测状态。"""
    if value is None:
        return None
    normalized = str(value).strip()
    if (
        normalized
        and len(normalized) <= 80
        and normalized[0].isalpha()
        and all(character.isalnum() or character == "_" for character in normalized)
    ):
        return normalized
    return "CollectorProbeError"


def _safe_timestamp(value: Any) -> str | None:
    """只保留可解析 ISO 时间，拒绝远端任意文本。"""
    if value is None:
        return None
    normalized = str(value).strip()
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return normalized


def _integer(value: Any) -> int:
    """将 Collector 数值约束为整数，异常输入按零处理。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _empty_snapshot(
    code: str,
    message: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """构造安全未就绪快照。"""
    return {
        "generated_at": _iso(now or datetime.now(timezone.utc)),
        "source": {
            "ready": False,
            "error": {"code": code, "message": message},
        },
        "collector": {
            "enabled": False,
            "status": "not_configured",
            "modules": [],
            "error_class": None,
        },
        "summary": {
            "total": 0,
            "by_lifecycle": {},
            "by_health": {},
            "active_incident_count": 0,
        },
        "tasks": [],
        "runtimes": [],
        "incidents": [],
    }


def _complete_summary(
    classified_summary: Mapping[str, Any], observations: ScanObservations
) -> dict[str, Any]:
    """补齐有界终态历史之外的总数和健康计数。"""
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


def _runtime_to_public(runtime: Mapping[str, Any]) -> dict[str, Any]:
    """返回固定运行时监督字段，不暴露账号和凭据。"""
    integer_fields = {
        "generic_workers_alive",
        "listing_worker_alive",
        "generic_available_capacity",
        "listing_available_capacity",
        "available_capacity",
        "standby_capacity",
    }
    fields = (
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
    return {
        field: int(runtime.get(field) or 0)
        if field in integer_fields
        else _optional_string(runtime.get(field))
        for field in fields
    }


def _optional_string(value: Any) -> str | None:
    """将可选值转换为字符串。"""
    return str(value) if value is not None else None


def _iso(value: datetime) -> str:
    """输出 UTC 秒级 ISO 时间。"""
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")
