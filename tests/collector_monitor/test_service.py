"""Collector Monitor 轮询服务公开契约测试。"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from opscli.collector_monitor.classifier import ClassificationPolicy, IncidentCandidate
from opscli.collector_monitor.config import MonitorSettings
from opscli.collector_monitor.repository import RepositorySourceError, ScanObservations
from opscli.collector_monitor import service as service_module
from opscli.collector_monitor.service import (
    CollectorMonitorScenarioBusyError,
    CollectorMonitorScenarioCooldownError,
    CollectorMonitorScenarioAuthError,
    CollectorMonitorProbeBusyError,
    CollectorMonitorProbeCooldownError,
    CollectorMonitorScenarioDisabledError,
    CollectorMonitorScenarioOutcomeUnknownError,
    CollectorMonitorScenarioPermissionError,
    CollectorMonitorService,
    probe_collector,
    run_collector_scenario,
)
from opscli.collector_monitor.state import MonitorStateStore

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)


def _iso(seconds: int) -> str:
    """返回相对固定时刻的 ISO 时间。"""
    return (NOW + timedelta(seconds=seconds)).isoformat()


def _settings(tmp_path: Path, **overrides) -> MonitorSettings:
    """构造完全隔离的服务配置。"""
    values = {
        "queue_db_path": tmp_path / "queue.sqlite3",
        "state_db_path": tmp_path / "state.sqlite3",
        "monitor_url": "http://127.0.0.1:8767",
        "collector_mcp_url": None,
        "collector_mcp_api_key_file": None,
        "poll_interval": 10.0,
        "stalled_threshold": 300.0,
        "queue_threshold": 300.0,
        "runtime_stale_threshold": 60.0,
        "orphan_required_scans": 2,
        "alert_cooldown": 1800.0,
        "webhook_file": None,
        "host": "127.0.0.1",
        "port": 8767,
        "collector_probe_timeout": 0.1,
        "scenario_test_enabled": False,
    }
    values.update(overrides)
    return MonitorSettings(**values)


class FakeRepository:
    """提供固定本地队列观测的仓储替身。"""

    def scan_observations(self):
        tasks = [
            {
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
                "progress_at": _iso(-400),
                "progress_sequence": 2,
                "last_error_code": None,
                "retry_reason": None,
                "row_count": 0,
            }
        ]
        runtimes = [
            {
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
        ]
        return ScanObservations(tuple(tasks), tuple(runtimes), 1, {"running": 1})

    def timelines_for_jobs(self, job_ids, *, timeline_limit=200):
        assert job_ids == ["job-1"]
        return {
            "job-1": [
                {
                    "progress_stage": "fetching",
                    "progress_at": _iso(-400),
                    "progress_sequence": 2,
                }
            ]
        }


class FailingRepository:
    """模拟本地数据源不可用。"""

    def scan_observations(self):
        raise RepositorySourceError("queue_schema_invalid", "监督 schema 缺少列")


class RecordingNotifier:
    """记录服务发出的通知动作。"""

    def __init__(self) -> None:
        self.actions = []

    def send(self, action):
        self.actions.append(action)
        return {"sent": True, "error_class": None}


def test_poll_checks_local_queue_even_when_collector_probe_fails(tmp_path: Path) -> None:
    """Collector 探测失败不得阻断本地分类、事故持久化和通知。"""
    settings = _settings(tmp_path, collector_mcp_url="https://collector.example/mcp")
    state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
    notifier = RecordingNotifier()

    async def failed_probe(_settings):
        return {"enabled": True, "status": "unavailable", "error_class": "TimeoutError"}

    service = CollectorMonitorService(
        settings,
        repository=FakeRepository(),
        state_store=state,
        notifier=notifier,
        collector_probe=failed_probe,
        clock=lambda: NOW,
    )
    snapshot = asyncio.run(service.poll_once())

    assert snapshot["source"] == {
        "ready": True,
        "error": None,
        "last_scan_at": _iso(0),
        "last_success_at": _iso(0),
        "error_code": None,
    }
    assert snapshot["collector"]["status"] == "pending"
    assert asyncio.run(service.probe_once())["status"] == "unavailable"
    assert snapshot["tasks"][0]["health"] == "stalled"
    assert snapshot["incidents"][0]["rule"] == "stalled"
    assert [item.kind for item in notifier.actions] == ["opening"]
    assert service.task_detail("job-1")["timeline"][0]["progress_sequence"] == 2


def test_manual_queue_source_probe_is_read_only_and_does_not_replace_snapshot(
    tmp_path: Path,
) -> None:
    """队列源探测只验证读取能力，不分类、不写状态库、不覆盖轮询快照。"""
    settings = _settings(tmp_path)
    state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
    service = CollectorMonitorService(
        settings,
        repository=FakeRepository(),
        state_store=state,
        notifier=RecordingNotifier(),
        clock=lambda: NOW,
    )
    before = service.cached_snapshot

    result = asyncio.run(service.manual_probe("queue-source"))

    assert result == {
        "target": "queue-source",
        "probed_at": _iso(0),
        "state": "succeeded",
        "status": "ready",
        "task_count": 1,
        "runtime_count": 1,
        "error_code": None,
        "error_class": None,
    }
    assert service.cached_snapshot is before
    assert state.scan_status()["last_scan_at"] is None


def test_manual_probe_enforces_per_target_concurrency_and_cooldown(tmp_path: Path) -> None:
    """同目标只允许一个探测，完成后十秒内拒绝重复探测。"""
    started = asyncio.Event()
    release = asyncio.Event()
    monotonic_now = [100.0]

    async def blocking_probe(_settings):
        started.set()
        await release.wait()
        return {"enabled": True, "status": "ready", "modules": []}

    async def scenario() -> None:
        settings = _settings(tmp_path, collector_mcp_url="https://collector.example/mcp")
        service = CollectorMonitorService(
            settings,
            repository=FakeRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            collector_probe=blocking_probe,
            clock=lambda: NOW,
            monotonic_clock=lambda: monotonic_now[0],
        )
        first = asyncio.create_task(service.manual_probe("collector"))
        await started.wait()
        with pytest.raises(CollectorMonitorProbeBusyError):
            await service.manual_probe("collector")
        release.set()
        assert (await first)["status"] == "ready"
        with pytest.raises(CollectorMonitorProbeCooldownError) as exc_info:
            await service.manual_probe("collector")
        assert exc_info.value.retry_after == 10.0
        monotonic_now[0] += 10.0
        assert (await service.manual_probe("collector"))["status"] == "ready"

    asyncio.run(scenario())


def test_queue_probe_timeout_keeps_target_busy_until_scan_thread_finishes(
    tmp_path: Path,
) -> None:
    """超时不能释放仍在运行的只读扫描锁，避免后续探测与残留线程重叠。"""
    started = threading.Event()
    release = threading.Event()
    monotonic_now = [100.0]

    class BlockingRepository(FakeRepository):
        def scan_observations(self):
            started.set()
            release.wait(timeout=1)
            return super().scan_observations()

    async def scenario() -> None:
        settings = _settings(tmp_path)
        service = CollectorMonitorService(
            settings,
            repository=BlockingRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            clock=lambda: NOW,
            monotonic_clock=lambda: monotonic_now[0],
        )
        result = await service.manual_probe("queue-source")
        assert result["status"] == "timeout"
        monotonic_now[0] += 10.0
        with pytest.raises(CollectorMonitorProbeBusyError):
            await service.manual_probe("queue-source")
        release.set()
        for _ in range(20):
            if not service._probe_locks["queue-source"].locked():
                break
            await asyncio.sleep(0.01)
        assert service._probe_locks["queue-source"].locked() is False

    original_timeout = service_module._MANUAL_PROBE_TIMEOUT_SECONDS
    service_module._MANUAL_PROBE_TIMEOUT_SECONDS = 0.01
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        service_module._MANUAL_PROBE_TIMEOUT_SECONDS = original_timeout


def test_poll_exposes_clear_not_ready_source_without_resolving_incidents(tmp_path: Path) -> None:
    """队列源失败应缓存安全未就绪结果而不是抛出或误恢复事故。"""
    settings = _settings(tmp_path)
    state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
    service = CollectorMonitorService(
        settings,
        repository=FailingRepository(),
        state_store=state,
        notifier=RecordingNotifier(),
        clock=lambda: NOW,
    )

    snapshot = asyncio.run(service.poll_once())

    assert snapshot["source"]["ready"] is False
    assert snapshot["source"]["error"]["code"] == "queue_schema_invalid"
    assert snapshot["source"]["last_scan_at"] == _iso(0)
    assert snapshot["source"]["last_success_at"] is None
    assert snapshot["source"]["error_code"] == "queue_schema_invalid"
    assert state.scan_status() == {
        "last_scan_at": _iso(0),
        "last_success_at": None,
        "error_code": "queue_schema_invalid",
    }
    assert snapshot["collector"]["status"] == "not_configured"
    assert service.is_ready is False


def test_failed_scan_preserves_last_successful_scan_time(tmp_path: Path) -> None:
    """失败扫描应保留最近成功时间，并只公开稳定错误码。"""

    class ToggleRepository(FakeRepository):
        failed = False

        def scan_observations(self):
            if self.failed:
                raise RuntimeError("secret queue path")
            return super().scan_observations()

    current = [NOW]
    settings = _settings(tmp_path)
    state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
    repository = ToggleRepository()
    service = CollectorMonitorService(
        settings,
        repository=repository,
        state_store=state,
        notifier=RecordingNotifier(),
        clock=lambda: current[0],
    )

    asyncio.run(service.poll_once())
    repository.failed = True
    current[0] = NOW + timedelta(seconds=10)
    failed = asyncio.run(service.poll_once())

    assert failed["source"]["last_scan_at"] == _iso(10)
    assert failed["source"]["last_success_at"] == _iso(0)
    assert failed["source"]["error_code"] == "queue_source_unavailable"
    assert "secret" not in repr(failed)


def test_local_scan_and_state_transactions_do_not_block_event_loop(tmp_path: Path) -> None:
    """队列扫描或状态事务等待时，事件循环仍应继续处理存活请求。"""

    class BlockingRepository(FakeRepository):
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def scan_observations(self):
            self.started.set()
            self.release.wait(timeout=1)
            return super().scan_observations()

    class BlockingStateStore(MonitorStateStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.started = threading.Event()
            self.release = threading.Event()

        def observe_consecutive(self, rule, subjects):
            self.started.set()
            self.release.wait(timeout=1)
            return super().observe_consecutive(rule, subjects)

    async def scenario() -> None:
        settings = _settings(tmp_path)
        repository = BlockingRepository()
        state = BlockingStateStore(settings.state_db_path, cooldown_seconds=1800)
        service = CollectorMonitorService(
            settings,
            repository=repository,
            state_store=state,
            notifier=RecordingNotifier(),
            clock=lambda: NOW,
        )
        task = asyncio.create_task(service.poll_once())

        await asyncio.to_thread(repository.started.wait, 1)
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.2)
        repository.release.set()
        await asyncio.to_thread(state.started.wait, 1)
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.2)
        state.release.set()
        await task

    asyncio.run(scenario())


def test_disabled_notifications_are_terminal_noops(tmp_path: Path) -> None:
    """未配置 Webhook 时事故应保留，但后续扫描不得每轮重试通知。"""

    class DisabledNotifier:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, _action):
            self.calls += 1
            return {
                "sent": False,
                "disabled": True,
                "error_class": "NotificationDisabled",
            }

    settings = _settings(tmp_path)
    state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
    notifier = DisabledNotifier()
    service = CollectorMonitorService(
        settings,
        repository=FakeRepository(),
        state_store=state,
        notifier=notifier,
        clock=lambda: NOW,
    )

    first = asyncio.run(service.poll_once())
    second = asyncio.run(service.poll_once())

    assert notifier.calls == 1
    assert first["incidents"][0]["alert_status"] == "disabled"
    assert second["incidents"][0]["delivery_result"] == "disabled"


def test_notifications_are_offloaded_and_delivered_concurrently(tmp_path: Path) -> None:
    """同轮通知不得阻塞事件循环，并应使用有界并发记录每条结果。"""

    class TwoIncidentRepository(FakeRepository):
        def scan_observations(self):
            observations = super().scan_observations()
            second = {**observations.tasks[0], "job_id": "job-2"}
            return ScanObservations(
                (*observations.tasks, second),
                observations.runtimes,
                2,
                {"running": 2},
            )

        def timelines_for_jobs(self, job_ids, *, timeline_limit=200):
            return {job_id: [] for job_id in job_ids}

    class BlockingNotifier:
        def __init__(self) -> None:
            self.started = threading.Barrier(3)
            self.release = threading.Event()
            self.threads: list[str] = []

        def send(self, action):
            self.threads.append(threading.current_thread().name)
            self.started.wait(timeout=1)
            self.release.wait(timeout=1)
            return {
                "sent": action.subject == "job-1",
                "error_class": None
                if action.subject == "job-1"
                else "NotificationError",
            }

    async def scenario() -> tuple[dict, BlockingNotifier]:
        settings = _settings(tmp_path)
        state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
        notifier = BlockingNotifier()
        service = CollectorMonitorService(
            settings,
            repository=TwoIncidentRepository(),
            state_store=state,
            notifier=notifier,
            clock=lambda: NOW,
        )
        task = asyncio.create_task(service.poll_once())
        await asyncio.to_thread(notifier.started.wait, 1)
        assert not task.done()
        notifier.release.set()
        return await task, notifier

    snapshot, notifier = asyncio.run(scenario())

    assert len(notifier.threads) == 2
    assert all(name != threading.main_thread().name for name in notifier.threads)
    deliveries = {item["subject"]: item for item in snapshot["incidents"]}
    assert deliveries["job-1"]["alert_status"] == "delivered"
    assert deliveries["job-2"]["alert_status"] == "failed"
    assert deliveries["job-2"]["delivery_error_class"] == "NotificationError"


def test_snapshot_caches_up_to_api_incident_limit(tmp_path: Path) -> None:
    """快照应缓存最多 500 条事故，支持 API 的完整有界查询。"""
    settings = _settings(tmp_path)
    state = MonitorStateStore(settings.state_db_path, cooldown_seconds=1800)
    state.reconcile(
        [
            IncidentCandidate("stalled", f"job-{index}", "high", "任务没有进度")
            for index in range(120)
        ],
        now=NOW,
    )
    service = CollectorMonitorService(
        settings,
        repository=FailingRepository(),
        state_store=state,
        notifier=RecordingNotifier(),
        clock=lambda: NOW,
    )

    snapshot = asyncio.run(service.poll_once())

    assert len(snapshot["incidents"]) == 120
    assert snapshot["summary"]["active_incident_count"] == 120


def test_probe_uses_remote_mcp_client_key_file_and_bounded_call(
    tmp_path: Path, monkeypatch
) -> None:
    """可选 Collector 探测应读取 API Key 文件并调用健康工具。"""
    key_file = tmp_path / "collector.key"
    key_file.write_text("mcp-secret", encoding="utf-8")
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        collector_mcp_api_key_file=key_file,
        collector_probe_timeout=0.5,
    )
    captured = {}

    class FakeRemoteClient:
        def __init__(self, url, *, headers=None, follow_redirects=True):
            captured.update(
                url=url,
                headers=headers,
                follow_redirects=follow_redirects,
            )

        async def call_tool(self, tool_name, arguments):
            captured.update(tool_name=tool_name, arguments=arguments)
            return {
                "success": True,
                "data": {
                    "status": "ready",
                    "api_key": "must-not-leak",
                    "modules": [
                        {
                            "bundle_id": "seller_sprite",
                            "status": "failed",
                            "checks": {
                                "queue": "error",
                                "scheduler": "not_started",
                                "password": "must-not-leak",
                            },
                            "error_code": "QUEUE_DATABASE_UNAVAILABLE",
                            "error_class": "OperationalError",
                            "runtime": {
                                "lifecycle_state": "running",
                                "generic_available_capacity": 1,
                                "listing_available_capacity": 0,
                                "authorization": "must-not-leak",
                            },
                            "cookie": "must-not-leak",
                        }
                    ],
                },
            }

    monkeypatch.setattr(
        "opscli.collector_monitor.service.RemoteMcpClient", FakeRemoteClient
    )

    result = asyncio.run(probe_collector(settings))

    assert result == {
        "enabled": True,
        "status": "ready",
        "modules": [
            {
                "bundle_id": "seller_sprite",
                "status": "failed",
                "checks": {"queue": "error", "scheduler": "not_started"},
                "error_code": "QUEUE_DATABASE_UNAVAILABLE",
                "error_class": "OperationalError",
                "runtime": {
                    "lifecycle_state": "running",
                    "generic_available_capacity": 1,
                    "listing_available_capacity": 0,
                },
            }
        ],
        "error_class": None,
    }
    assert "must-not-leak" not in repr(result)
    assert captured == {
        "url": "https://collector.example/mcp",
        "headers": {"Authorization": "Bearer mcp-secret"},
        "follow_redirects": False,
        "tool_name": "collector_modules_health",
        "arguments": {},
    }


def test_probe_auth_header_is_accepted_by_collector_middleware(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Monitor 生成的凭据 Header 必须能通过真实 Collector 鉴权中间件。"""
    from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

    accepted = {}

    async def authorized_app(scope, receive, send):
        accepted["api_key"] = scope.get("mcp_api_key")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = ApiKeyAuthMiddleware(authorized_app, api_key="contract-key")

    class ContractRemoteClient:
        def __init__(self, url, *, headers=None, follow_redirects=True):
            self.headers = headers or {}

        async def call_tool(self, tool_name, arguments):
            sent = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http",
                "path": "/mcp",
                "query_string": b"",
                "headers": [
                    (name.lower().encode(), value.encode())
                    for name, value in self.headers.items()
                ],
            }
            await middleware(scope, receive, send)
            assert sent[0]["status"] == 200
            return {"success": True, "data": {"status": "ready", "modules": []}}

    monkeypatch.setattr(
        "opscli.collector_monitor.service.RemoteMcpClient",
        ContractRemoteClient,
    )
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
    )

    result = asyncio.run(probe_collector(settings, api_key="contract-key"))

    assert result["status"] == "ready"
    assert accepted == {"api_key": "contract-key"}


def test_manual_probe_uses_one_time_key_without_persisting_it(tmp_path: Path) -> None:
    """临时 Key 只存在于当前 Collector 调用参数，不进入结果或服务快照。"""
    captured = {}

    async def probe_with_key(settings, api_key):
        captured.update(settings=settings, api_key=api_key)
        return {"enabled": True, "status": "ready", "modules": []}

    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
    )
    service = CollectorMonitorService(
        settings,
        repository=FakeRepository(),
        state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
        notifier=RecordingNotifier(),
        collector_api_key_probe=probe_with_key,
        clock=lambda: NOW,
    )

    result = asyncio.run(
        service.manual_probe("collector", api_key="temporary-mcp-key")
    )

    assert captured == {"settings": settings, "api_key": "temporary-mcp-key"}
    assert result["status"] == "ready"
    assert "temporary-mcp-key" not in repr(result)
    assert "temporary-mcp-key" not in repr(service.cached_snapshot)


def test_scenario_submission_calls_fixed_keyword_reverse_and_returns_job_id(
    tmp_path: Path,
) -> None:
    """场景测试只能提交固定关键词反查，并返回可跟踪的任务标识。"""
    captured = {}

    async def run_scenario(settings, arguments, api_key):
        captured.update(settings=settings, arguments=arguments, api_key=api_key)
        return {"job_id": "job-keyword-1", "state": "queued"}

    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        scenario_test_enabled=True,
    )
    service = CollectorMonitorService(
        settings,
        repository=FakeRepository(),
        state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
        notifier=RecordingNotifier(),
        scenario_runner=run_scenario,
        clock=lambda: NOW,
    )

    result = asyncio.run(
        service.submit_keyword_reverse(
            asin="B07YRMT36L",
            site="US",
            period="30d",
            page_size=100,
            api_key="temporary-mcp-key",
        )
    )

    assert captured == {
        "settings": settings,
        "arguments": {
            "scenario": "keyword-reverse",
            "params": {"asin": "B07YRMT36L"},
            "site": "US",
            "period": "30d",
            "page_size": 100,
            "export_format": "json",
        },
        "api_key": "temporary-mcp-key",
    }
    assert result == {
        "scenario": "keyword-reverse",
        "job_id": "job-keyword-1",
        "state": "queued",
        "submitted_at": NOW.isoformat(),
    }
    assert "temporary-mcp-key" not in repr(result)
    assert "temporary-mcp-key" not in repr(service.cached_snapshot)


def test_scenario_submission_is_rejected_when_feature_is_disabled(
    tmp_path: Path,
) -> None:
    """默认关闭时不得通过服务层绕过场景测试开关。"""
    calls = 0

    async def run_scenario(settings, arguments, api_key):
        nonlocal calls
        calls += 1
        return {"job_id": "must-not-run", "state": "queued"}

    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        scenario_test_enabled=False,
    )
    service = CollectorMonitorService(
        settings,
        repository=FakeRepository(),
        state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
        notifier=RecordingNotifier(),
        scenario_runner=run_scenario,
    )

    with pytest.raises(CollectorMonitorScenarioDisabledError):
        asyncio.run(
            service.submit_keyword_reverse(
                asin="B07YRMT36L",
                site="US",
                period="30d",
                page_size=100,
            )
        )

    assert calls == 0


def test_scenario_submission_enforces_single_flight_and_cooldown(
    tmp_path: Path,
) -> None:
    """真实额度任务在执行中和完成后十秒内不得重复提交。"""
    started = asyncio.Event()
    release = asyncio.Event()
    monotonic_now = [100.0]

    async def run_scenario(settings, arguments, api_key):
        started.set()
        await release.wait()
        return {"job_id": "job-keyword-1", "state": "queued"}

    async def scenario() -> None:
        settings = _settings(
            tmp_path,
            collector_mcp_url="https://collector.example/mcp",
            scenario_test_enabled=True,
        )
        service = CollectorMonitorService(
            settings,
            repository=FakeRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            scenario_runner=run_scenario,
            monotonic_clock=lambda: monotonic_now[0],
        )
        first = asyncio.create_task(
            service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        )
        await started.wait()
        with pytest.raises(CollectorMonitorScenarioBusyError):
            await service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        release.set()
        assert (await first)["job_id"] == "job-keyword-1"
        with pytest.raises(CollectorMonitorScenarioCooldownError) as exc_info:
            await service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        assert exc_info.value.retry_after == 10.0
        monotonic_now[0] += 10.0
        assert (
            await service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        )["state"] == "queued"

    asyncio.run(scenario())


def test_scenario_runner_uses_bearer_key_and_fixed_seller_sprite_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """真实场景调用必须复用 Bearer 鉴权并固定工具名。"""
    captured = {}

    class FakeRemoteClient:
        def __init__(self, url, *, headers=None, follow_redirects=True):
            captured.update(
                url=url,
                headers=headers,
                follow_redirects=follow_redirects,
            )

        async def call_tool(self, tool_name, arguments):
            captured.update(tool_name=tool_name, arguments=arguments)
            return {
                "success": True,
                "data": {"job_id": "job-keyword-1", "state": "queued"},
            }

    monkeypatch.setattr(
        "opscli.collector_monitor.service.RemoteMcpClient",
        FakeRemoteClient,
    )
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        scenario_test_enabled=True,
    )
    arguments = {
        "scenario": "keyword-reverse",
        "params": {"asin": "B07YRMT36L"},
        "site": "US",
        "period": "30d",
        "page_size": 100,
        "export_format": "json",
    }

    result = asyncio.run(
        run_collector_scenario(settings, arguments, "temporary-mcp-key")
    )

    assert result == {"job_id": "job-keyword-1", "state": "queued"}
    assert captured == {
        "url": "https://collector.example/mcp",
        "headers": {"Authorization": "Bearer temporary-mcp-key"},
        "follow_redirects": False,
        "tool_name": "seller_sprite_run",
        "arguments": arguments,
    }
    assert "temporary-mcp-key" not in repr(result)


def test_scenario_timeout_reports_unknown_outcome_without_retrying(
    tmp_path: Path,
) -> None:
    """提交超时后不得自动重试，并在底层结束前继续阻止重复扣额。"""
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def run_scenario(settings, arguments, api_key):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"job_id": "job-late", "state": "queued"}

    async def scenario() -> None:
        settings = _settings(
            tmp_path,
            collector_mcp_url="https://collector.example/mcp",
            scenario_test_enabled=True,
        )
        service = CollectorMonitorService(
            settings,
            repository=FakeRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            scenario_runner=run_scenario,
        )
        with pytest.raises(CollectorMonitorScenarioOutcomeUnknownError):
            await service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        assert calls == 1
        with pytest.raises(CollectorMonitorScenarioBusyError):
            await service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        release.set()
        for _ in range(20):
            if not service._scenario_lock.locked():
                break
            await asyncio.sleep(0.01)
        assert service._scenario_lock.locked() is False
        assert calls == 1

    original_timeout = service_module._SCENARIO_SUBMIT_TIMEOUT_SECONDS
    service_module._SCENARIO_SUBMIT_TIMEOUT_SECONDS = 0.01
    try:
        asyncio.run(scenario())
    finally:
        service_module._SCENARIO_SUBMIT_TIMEOUT_SECONDS = original_timeout


def test_cancelled_scenario_request_holds_lock_until_runner_finishes(
    tmp_path: Path,
) -> None:
    """客户端断开取消请求时，远端调用结束前仍不得再次提交。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def run_scenario(settings, arguments, api_key):
        started.set()
        await release.wait()
        return {"job_id": "job-after-cancel", "state": "queued"}

    async def scenario() -> None:
        settings = _settings(
            tmp_path,
            collector_mcp_url="https://collector.example/mcp",
            scenario_test_enabled=True,
        )
        service = CollectorMonitorService(
            settings,
            repository=FakeRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            scenario_runner=run_scenario,
        )
        request = asyncio.create_task(
            service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        )
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(CollectorMonitorScenarioBusyError):
            await service.submit_keyword_reverse(
                asin="B07YRMT36L", site="US", period="30d", page_size=100
            )
        release.set()
        for _ in range(20):
            if not service._scenario_lock.locked():
                break
            await asyncio.sleep(0.01)
        assert service._scenario_lock.locked() is False

    asyncio.run(scenario())


def test_cancelled_manual_probe_holds_lock_until_probe_finishes(
    tmp_path: Path,
) -> None:
    """客户端取消只读探测后，底层结束前仍保持单目标并发锁。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def probe(settings):
        started.set()
        await release.wait()
        return {"enabled": True, "status": "ready", "modules": []}

    async def scenario() -> None:
        settings = _settings(
            tmp_path,
            collector_mcp_url="https://collector.example/mcp",
        )
        service = CollectorMonitorService(
            settings,
            repository=FakeRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            collector_probe=probe,
        )
        request = asyncio.create_task(service.manual_probe("collector"))
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(CollectorMonitorProbeBusyError):
            await service.manual_probe("collector")
        release.set()
        for _ in range(20):
            if not service._probe_locks["collector"].locked():
                break
            await asyncio.sleep(0.01)
        assert service._probe_locks["collector"].locked() is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, CollectorMonitorScenarioAuthError),
        (403, CollectorMonitorScenarioPermissionError),
    ],
)
def test_scenario_runner_distinguishes_invalid_key_and_missing_permission(
    tmp_path: Path,
    monkeypatch,
    status_code: int,
    error_type: type[Exception],
) -> None:
    """401 与 403 应给出不同安全诊断，且不得暴露远端错误正文。"""
    request = httpx.Request("POST", "https://collector.example/mcp")
    response = httpx.Response(status_code, request=request)
    remote_error = httpx.HTTPStatusError(
        "sensitive remote response",
        request=request,
        response=response,
    )

    class FailingRemoteClient:
        def __init__(self, url, *, headers=None, follow_redirects=True):
            pass

        async def call_tool(self, tool_name, arguments):
            raise ExceptionGroup("wrapped transport failure", [remote_error])

    monkeypatch.setattr(
        "opscli.collector_monitor.service.RemoteMcpClient",
        FailingRemoteClient,
    )
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        scenario_test_enabled=True,
    )

    with pytest.raises(error_type) as exc_info:
        asyncio.run(
            run_collector_scenario(
                settings,
                {"scenario": "keyword-reverse"},
                "temporary-mcp-key",
            )
        )

    assert "sensitive remote response" not in str(exc_info.value)
    assert "temporary-mcp-key" not in str(exc_info.value)


def test_scenario_runner_requires_explicit_api_key(tmp_path: Path) -> None:
    """真实场景不得回退借用 Monitor 服务端 Key 文件。"""
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        collector_mcp_api_key_file=tmp_path / "collector.key",
        scenario_test_enabled=True,
    )

    with pytest.raises(
        service_module.CollectorMonitorScenarioAuthError
    ) as exc_info:
        asyncio.run(
            run_collector_scenario(
                settings,
                {"scenario": "keyword-reverse"},
                None,
            )
        )

    assert "API Key" in str(exc_info.value)


def test_scenario_runner_rejects_non_object_response(tmp_path: Path, monkeypatch) -> None:
    """Collector 非对象响应应映射为稳定拒绝错误而不是裸 500。"""

    class NonObjectRemoteClient:
        def __init__(self, url, *, headers=None, follow_redirects=True):
            pass

        async def call_tool(self, tool_name, arguments):
            return ["unexpected"]

    monkeypatch.setattr(
        "opscli.collector_monitor.service.RemoteMcpClient",
        NonObjectRemoteClient,
    )
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        scenario_test_enabled=True,
    )

    with pytest.raises(service_module.CollectorMonitorScenarioRejectedError):
        asyncio.run(
            run_collector_scenario(
                settings,
                {"scenario": "keyword-reverse"},
                "temporary-mcp-key",
            )
        )


@pytest.mark.parametrize("status_code", [401, 403])
def test_probe_maps_nested_http_auth_errors_to_stable_code(
    tmp_path: Path,
    monkeypatch,
    status_code: int,
) -> None:
    """MCP 传输层包装的 401/403 应与网络不可达明确区分。"""
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
    )
    request = httpx.Request("POST", "https://collector.example/mcp")
    response = httpx.Response(status_code, request=request)
    auth_error = httpx.HTTPStatusError(
        "collector authentication failed",
        request=request,
        response=response,
    )

    class UnauthorizedRemoteClient:
        def __init__(self, url, *, headers=None, follow_redirects=True):
            assert headers == {"Authorization": "Bearer temporary-mcp-key"}

        async def call_tool(self, tool_name, arguments):
            raise ExceptionGroup("remote unauthorized", [auth_error])

    monkeypatch.setattr(
        "opscli.collector_monitor.service.RemoteMcpClient",
        UnauthorizedRemoteClient,
    )

    result = asyncio.run(
        probe_collector(settings, api_key="temporary-mcp-key")
    )

    assert result == {
        "enabled": True,
        "status": "unavailable",
        "modules": [],
        "error_code": "COLLECTOR_AUTH_FAILED",
        "error_class": "HTTPStatusError",
    }


def test_probe_key_read_is_offloaded_and_included_in_total_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """密钥文件读取不得阻塞事件循环，并必须受探测总超时约束。"""
    key_file = tmp_path / "collector.key"
    key_file.write_text("mcp-secret", encoding="utf-8")
    settings = _settings(
        tmp_path,
        collector_mcp_url="https://collector.example/mcp",
        collector_mcp_api_key_file=key_file,
        collector_probe_timeout=0.05,
    )
    started = threading.Event()
    release = threading.Event()

    def blocking_read(_path):
        started.set()
        release.wait(timeout=1)
        return "mcp-secret"

    monkeypatch.setattr(
        "opscli.collector_monitor.service.read_protected_text",
        blocking_read,
    )

    async def scenario() -> tuple[dict, float]:
        started_at = time.monotonic()
        task = asyncio.create_task(probe_collector(settings))
        await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.03)
        result = await asyncio.wait_for(task, timeout=0.2)
        return result, time.monotonic() - started_at

    try:
        result, elapsed = asyncio.run(scenario())
    finally:
        release.set()

    assert result["status"] == "unavailable"
    assert result["error_class"] == "TimeoutError"
    assert elapsed < 0.2


def test_manual_collector_probe_timeout_returns_safe_result(tmp_path: Path) -> None:
    """手动探测必须在五秒硬上限内降级为安全结果。"""
    async def never_returns(_settings):
        await asyncio.Event().wait()

    async def scenario() -> dict:
        settings = _settings(tmp_path, collector_mcp_url="https://collector.example/mcp")
        service = CollectorMonitorService(
            settings,
            repository=FakeRepository(),
            state_store=MonitorStateStore(settings.state_db_path, cooldown_seconds=1800),
            notifier=RecordingNotifier(),
            collector_probe=never_returns,
            clock=lambda: NOW,
        )
        return await service.manual_probe("collector")

    original_timeout = service_module._MANUAL_PROBE_TIMEOUT_SECONDS
    service_module._MANUAL_PROBE_TIMEOUT_SECONDS = 0.01
    try:
        result = asyncio.run(scenario())
    finally:
        service_module._MANUAL_PROBE_TIMEOUT_SECONDS = original_timeout

    assert result["status"] == "timeout"
    assert result["error_code"] == "COLLECTOR_UNREACHABLE"
    assert result["error_class"] == "TimeoutError"
