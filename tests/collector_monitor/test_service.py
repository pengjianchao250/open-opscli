"""Collector Monitor 轮询服务公开契约测试。"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opscli.collector_monitor.classifier import ClassificationPolicy, IncidentCandidate
from opscli.collector_monitor.config import MonitorSettings
from opscli.collector_monitor.repository import RepositorySourceError, ScanObservations
from opscli.collector_monitor.service import CollectorMonitorService, probe_collector
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
                            "status": "ready",
                            "checks": {
                                "queue": "ok",
                                "scheduler": "running",
                                "password": "must-not-leak",
                            },
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
                "status": "ready",
                "checks": {"queue": "ok", "scheduler": "running"},
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
        "headers": {"X-MCP-API-Key": "mcp-secret"},
        "follow_redirects": False,
        "tool_name": "collector_modules_health",
        "arguments": {},
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
