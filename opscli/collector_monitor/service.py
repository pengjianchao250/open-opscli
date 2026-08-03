"""Collector Monitor 轮询编排与缓存快照。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic
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
# 手动探测按确认的运维合同限制为每目标 10 秒一次，避免重复施压。
_MANUAL_PROBE_COOLDOWN_SECONDS = 10.0
# 手动探测硬上限固定为 5 秒，确保 UI 和 CLI 可以有界返回。
_MANUAL_PROBE_TIMEOUT_SECONDS = 5.0
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


class CollectorMonitorError(RuntimeError):
    """Collector Monitor 模块业务异常基类。"""


class CollectorMonitorProbeBusyError(CollectorMonitorError):
    """同一目标已有手动探测正在执行。"""


class CollectorMonitorProbeCooldownError(CollectorMonitorError):
    """同一目标仍处于手动探测冷却期。"""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(0.0, retry_after)
        super().__init__("探测操作仍在冷却期")


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
        collector_api_key_probe: (
            Callable[[MonitorSettings, str], Awaitable[dict[str, Any]]] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.state_store = state_store
        self.notifier = notifier
        self.collector_probe = collector_probe or probe_collector
        self.collector_api_key_probe = (
            collector_api_key_probe or probe_collector_with_api_key
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic_clock = monotonic_clock or monotonic
        self._probe_locks = {
            "collector": asyncio.Lock(),
            "queue-source": asyncio.Lock(),
        }
        self._probe_started_at: dict[str, float] = {}
        # 超时后底层线程或远端调用可能仍未结束；保留任务引用并继续占锁。
        self._background_probe_tasks: set[asyncio.Task[Any]] = set()
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

    async def manual_probe(
        self,
        target: str,
        *,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """按固定目标执行有界、限并发和带冷却的无副作用探测。

        Args:
            target: 固定目标标识，仅支持 `collector` 或 `queue-source`。
            api_key: 仅用于本次 Collector 请求的临时 API Key，不持久化。

        Returns:
            仅含目标、探测时间、状态和脱敏诊断字段的同步结果。

        Raises:
            ValueError: 目标不在固定白名单中。
            CollectorMonitorProbeBusyError: 同一目标已有探测正在运行。
            CollectorMonitorProbeCooldownError: 距上次探测开始不足 10 秒。
        """
        if target not in self._probe_locks:
            raise ValueError("不支持的探测目标")
        if api_key is not None and target != "collector":
            raise ValueError("临时 API Key 只允许用于 Collector 探测")
        lock = self._probe_locks[target]
        if lock.locked():
            raise CollectorMonitorProbeBusyError("同一目标已有探测正在执行")

        await lock.acquire()
        release_lock = True
        try:
            started_at = self.monotonic_clock()
            previous = self._probe_started_at.get(target)
            if previous is not None:
                remaining = _MANUAL_PROBE_COOLDOWN_SECONDS - (started_at - previous)
                if remaining > 0:
                    raise CollectorMonitorProbeCooldownError(round(remaining, 3))
            self._probe_started_at[target] = started_at
            if target == "collector":
                probe_call = (
                    _safe_probe_result(
                        self.collector_api_key_probe(self.settings, api_key)
                    )
                    if api_key is not None
                    else _safe_probe_call(self.collector_probe, self.settings)
                )
                result, release_lock = await self._bounded_probe(
                    probe_call,
                    lock,
                )
                if result is None:
                    result = {
                        "enabled": bool(self.settings.collector_mcp_url),
                        "status": "timeout",
                        "modules": [],
                        "error_code": "COLLECTOR_UNREACHABLE",
                        "error_class": "TimeoutError",
                    }
                elif result.get("status") == "unavailable":
                    if not result.get("error_code"):
                        result["error_code"] = "COLLECTOR_UNREACHABLE"
                    if result.get("error_class") == "TimeoutError":
                        result["status"] = "timeout"
                        result["error_code"] = "COLLECTOR_UNREACHABLE"
                self._collector = result
                self._snapshot["collector"] = dict(result)
            else:
                result, release_lock = await self._bounded_probe(
                    self._probe_queue_source(),
                    lock,
                )
                if result is None:
                    result = {
                        "status": "timeout",
                        "task_count": 0,
                        "runtime_count": 0,
                        "error_code": "QUEUE_DATABASE_UNAVAILABLE",
                        "error_class": "TimeoutError",
                    }
            probe_state = (
                "timeout"
                if result.get("status") == "timeout"
                else "failed"
                if result.get("status") == "unavailable"
                else "succeeded"
            )
            return {
                "target": target,
                "probed_at": _iso(self.clock()),
                "state": probe_state,
                **result,
            }
        finally:
            if release_lock:
                lock.release()

    async def _bounded_probe(
        self,
        probe: Awaitable[dict[str, Any]],
        lock: asyncio.Lock,
    ) -> tuple[dict[str, Any] | None, bool]:
        """有界等待探测，并在超时后继续持锁直到底层操作实际结束。"""
        task = asyncio.create_task(probe)
        done, _pending = await asyncio.wait(
            {task},
            timeout=_MANUAL_PROBE_TIMEOUT_SECONDS,
        )
        if task in done:
            return await task, True

        self._background_probe_tasks.add(task)

        def finish_background(completed: asyncio.Task[Any]) -> None:
            """消费后台结果并释放目标锁，避免异常泄露或并发穿透。"""
            self._background_probe_tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()
            if lock.locked():
                lock.release()

        task.add_done_callback(finish_background)
        return None, False

    async def _probe_queue_source(self) -> dict[str, Any]:
        """只读打开并查询固定队列源，不更新监控状态或任务缓存。"""
        try:
            observations = await asyncio.to_thread(self.repository.scan_observations)
            return {
                "status": "ready",
                "task_count": int(observations.total),
                "runtime_count": len(observations.runtimes),
                "error_code": None,
                "error_class": None,
            }
        except RepositorySourceError as exc:
            error_code = str(exc.code or "").strip().upper()
            return {
                "status": "unavailable",
                "task_count": 0,
                "runtime_count": 0,
                "error_code": error_code or "QUEUE_DATABASE_UNAVAILABLE",
                "error_class": type(exc).__name__,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "task_count": 0,
                "runtime_count": 0,
                "error_code": "QUEUE_DATABASE_UNAVAILABLE",
                "error_class": type(exc).__name__,
            }

    async def run(
        self,
        stop_event: asyncio.Event,
        *,
        poll_immediately: bool = True,
    ) -> None:
        """运行本地队列扫描；远端 Collector 仅允许手动探测。"""
        should_poll = poll_immediately
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


async def probe_collector(
    settings: MonitorSettings,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
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
            _probe_collector_with_credentials(settings, api_key=api_key),
            timeout=settings.collector_probe_timeout,
        )
        data = response.get("data") if isinstance(response, Mapping) else None
        if not isinstance(data, Mapping):
            raise ValueError("Collector MCP 健康响应缺少 data")
        return _public_collector_result(data)
    except Exception as exc:
        error_code, error_class = _collector_probe_error_fields(exc)
        return {
            "enabled": True,
            "status": "unavailable",
            "modules": [],
            "error_code": error_code,
            "error_class": error_class,
        }


async def probe_collector_with_api_key(
    settings: MonitorSettings,
    api_key: str,
) -> dict[str, Any]:
    """使用仅驻留于当前调用生命周期的 API Key 探测 Collector。"""
    return await probe_collector(settings, api_key=api_key)


async def _probe_collector_with_credentials(
    settings: MonitorSettings,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """在线程中读取密钥，并禁止携带自定义密钥跟随重定向。"""
    headers = None
    effective_api_key = api_key
    if effective_api_key is None and settings.collector_mcp_api_key_file is not None:
        effective_api_key = await asyncio.to_thread(
            read_protected_text,
            settings.collector_mcp_api_key_file,
        )
        if not effective_api_key:
            raise ValueError("Collector MCP API Key 文件为空")
    if effective_api_key is not None:
        headers = {"X-MCP-API-Key": effective_api_key}
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
    return await _safe_probe_result(probe(settings))


async def _safe_probe_result(
    probe: Awaitable[dict[str, Any]],
) -> dict[str, Any]:
    """清洗探测协程结果，并将异常压缩为稳定公开诊断。"""
    try:
        result = await probe
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
        error_code, error_class = _collector_probe_error_fields(exc)
        return {
            "enabled": True,
            "status": "unavailable",
            "modules": [],
            "error_code": error_code,
            "error_class": error_class,
        }


def _collector_probe_error_fields(exc: BaseException) -> tuple[str, str]:
    """识别嵌套传输异常中的鉴权状态，避免将 401 误报为网络不通。"""
    for current in _walk_exceptions(exc):
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) in {401, 403}:
            return "COLLECTOR_AUTH_FAILED", type(current).__name__
    return "COLLECTOR_UNREACHABLE", type(exc).__name__


def _walk_exceptions(exc: BaseException) -> list[BaseException]:
    """有界遍历 cause、context 与 ExceptionGroup 子异常。"""
    pending = [exc]
    visited: set[int] = set()
    result: list[BaseException] = []
    while pending and len(result) < 32:
        current = pending.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        result.append(current)
        nested = getattr(current, "exceptions", ())
        if isinstance(nested, tuple):
            pending.extend(item for item in nested if isinstance(item, BaseException))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return result


def _public_collector_result(data: Mapping[str, Any]) -> dict[str, Any]:
    """将 Collector 响应压缩到固定模块、检查和运行态字段。"""
    modules = data.get("modules")
    source_modules = modules if isinstance(modules, list) else []
    result = {
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
    if data.get("error_code") is not None:
        result["error_code"] = _safe_error_code(data.get("error_code"))
    return result


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
    if "error_code" in value:
        result["error_code"] = _safe_error_code(value.get("error_code"))
    if "error_class" in value:
        result["error_class"] = _safe_error_class(value.get("error_class"))
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


def _safe_error_code(value: Any) -> str:
    """只允许大写稳定错误码进入公开探测状态。"""
    normalized = str(value or "").strip().upper()
    if (
        normalized
        and len(normalized) <= 80
        and normalized[0].isalpha()
        and all(character.isalnum() or character == "_" for character in normalized)
    ):
        return normalized
    return "UNKNOWN_PROBE_ERROR"


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
