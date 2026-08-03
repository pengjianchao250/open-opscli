"""Collector Monitor Starlette API 与嵌入式 UI 契约测试。"""

from __future__ import annotations

import threading

from starlette.testclient import TestClient

from opscli.collector_monitor.app import create_app


class FakeService:
    """提供固定缓存快照的应用服务替身。"""

    def __init__(self, *, ready: bool = True) -> None:
        self.is_ready = ready
        self.cached_snapshot = {
            "generated_at": "2026-07-29T04:00:00+00:00",
            "source": {
                "ready": ready,
                "error": None
                if ready
                else {"code": "queue_schema_invalid", "message": "监督 schema 缺少列"},
                "last_scan_at": "2026-07-29T04:00:00+00:00",
                "last_success_at": "2026-07-29T04:00:00+00:00" if ready else None,
                "error_code": None if ready else "queue_schema_invalid",
            },
            "collector": {
                "enabled": True,
                "status": "ready",
                "modules": [
                    {
                        "bundle_id": "seller_sprite",
                        "status": "ready",
                        "api_key": "must-not-leak",
                        "password": "must-not-leak",
                        "authorization": "must-not-leak",
                        "cookie": "must-not-leak",
                        "secret": "must-not-leak",
                    }
                ],
            },
            "summary": {
                "total": 1,
                "by_lifecycle": {"running": 1},
                "by_health": {"stalled": 1},
                "active_incident_count": 1,
            },
            "tasks": [
                {
                    "job_id": "job-1",
                    "queue_scope": "default",
                    "task_kind": "generic",
                    "lifecycle": "running",
                    "health": "stalled",
                    "progress_stage": "fetching",
                    "progress_at": "2026-07-29T03:50:00+00:00",
                    "assigned_account": "must-not-leak",
                    "request_json": {"token": "must-not-leak"},
                    "result_path": "C:/must-not-leak",
                }
            ],
            "runtimes": [
                {
                    "execution_owner": "scheduler-a",
                    "lifecycle_state": "running",
                    "heartbeat_at": "2026-07-29T03:59:50+00:00",
                    "available_capacity": 2,
                }
            ],
            "incidents": [
                {
                    "rule": "stalled",
                    "subject": "job-1",
                    "severity": "high",
                    "status": "active",
                    "message": "任务没有进度",
                },
                {
                    "rule": "queue_starved",
                    "subject": "generic",
                    "severity": "medium",
                    "status": "resolved",
                    "message": "队列已恢复消费",
                },
            ],
        }

    def task_detail(self, job_id: str):
        if job_id != "job-1":
            raise KeyError(job_id)
        return {
            **self.cached_snapshot["tasks"][0],
            "timeline": [
                {
                    "progress_stage": "fetching",
                    "progress_at": "2026-07-29T03:50:00+00:00",
                    "progress_sequence": 2,
                    "error_json": "must-not-leak",
                }
            ],
        }

    async def manual_probe(self, target: str):
        return {
            "target": target,
            "probed_at": "2026-07-29T04:00:00+00:00",
            "status": "ready",
            "error_class": None,
        }


def _client(*, ready: bool = True) -> TestClient:
    """创建不启动后台轮询的隔离 ASGI 客户端。"""
    return TestClient(create_app(FakeService(ready=ready), manage_polling=False))


def test_lifespan_performs_only_one_initial_scan() -> None:
    """应用启动不能在同一瞬间重复满足孤儿任务连续观测阈值。"""

    class PollingService(FakeService):
        def __init__(self) -> None:
            super().__init__()
            self.poll_count = 0
            self.started = threading.Event()

        async def poll_once(self):
            self.poll_count += 1
            return self.cached_snapshot

        async def run(self, stop_event, *, poll_immediately=True):
            assert poll_immediately is False
            self.started.set()
            await stop_event.wait()

    service = PollingService()
    with TestClient(create_app(service)):
        assert service.started.wait(timeout=1)
        assert service.poll_count == 1


def test_health_endpoints_and_no_store_headers() -> None:
    """存活检查始终成功，就绪检查反映本地数据源状态。"""
    with _client() as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "live"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert live.headers["cache-control"] == "no-store"
    assert ready.headers["cache-control"] == "no-store"
    assert live.headers["x-frame-options"] == "DENY"
    assert live.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in live.headers["content-security-policy"]

    with _client(ready=False) as client:
        unavailable = client.get("/health/ready")
    assert unavailable.status_code == 503
    assert unavailable.json()["status"] == "not_ready"
    assert unavailable.json()["source_error"]["code"] == "queue_schema_invalid"


def test_dashboard_exposes_accessible_tab_views() -> None:
    """仪表盘应按任务、Collector、运行时和事故拆分为可访问 Tab。"""
    with _client() as client:
        response = client.get("/")

    html = response.text
    assert response.status_code == 200
    assert 'role="tablist"' in html
    for name in ("tasks", "collector", "runtimes", "incidents"):
        assert f'id="tab-{name}"' in html
        assert f'aria-controls="panel-{name}"' in html
        assert f'id="panel-{name}"' in html
        assert f'aria-labelledby="tab-{name}"' in html
    assert 'id="tab-tasks" type="button" role="tab"' in html
    assert 'id="panel-collector" role="tabpanel"' in html


def test_api_uses_cached_snapshot_filters_tasks_and_redacts_defensively() -> None:
    """API 应读取缓存、支持健康过滤并剔除敏感字段和值。"""
    with _client() as client:
        status = client.get("/api/v1/status")
        tasks = client.get("/api/v1/tasks?health=stalled")
        empty = client.get("/api/v1/tasks?health=healthy")
        invalid = client.get("/api/v1/tasks?health=unknown")
        detail = client.get("/api/v1/tasks/job-1")
        missing = client.get("/api/v1/tasks/job-missing")
        incidents = client.get("/api/v1/incidents")

    assert status.status_code == 200
    assert tasks.json()["tasks"][0]["job_id"] == "job-1"
    assert empty.json() == {"tasks": []}
    assert invalid.status_code == 400
    assert detail.json()["timeline"][0]["progress_sequence"] == 2
    assert missing.status_code == 404
    assert incidents.json()["incidents"][0]["rule"] == "stalled"
    for response in (status, tasks, detail, incidents):
        serialized = response.text
        assert response.headers["cache-control"] == "no-store"
        assert "must-not-leak" not in serialized
        assert "assigned_account" not in serialized
        assert "request_json" not in serialized
        assert "result_path" not in serialized
        assert "error_json" not in serialized
        assert "api_key" not in serialized
        assert "password" not in serialized
        assert "authorization" not in serialized
        assert "cookie" not in serialized
        assert "secret" not in serialized


def test_manual_probe_endpoints_use_only_fixed_targets() -> None:
    """探测 API 只暴露两个固定服务端目标，不接受调用方提供地址。"""
    with _client() as client:
        collector = client.post("/api/v1/probes/collector", json={})
        queue_source = client.post("/api/v1/probes/queue-source", json={})
        arbitrary = client.post("/api/v1/probes/https://example.com", json={})

    assert collector.status_code == queue_source.status_code == 200
    assert collector.json()["target"] == "collector"
    assert queue_source.json()["target"] == "queue-source"
    assert arbitrary.status_code == 404


def test_manual_probe_rejects_cross_origin_and_non_json_requests() -> None:
    with _client() as client:
        cross_origin = client.post(
            "/api/v1/probes/collector",
            json={},
            headers={"Origin": "https://attacker.example"},
        )
        non_json = client.post("/api/v1/probes/collector")

    assert cross_origin.status_code == 403
    assert cross_origin.json()["error"]["code"] == "cross_origin_probe_denied"
    assert non_json.status_code == 415
    assert non_json.json()["error"]["code"] == "invalid_content_type"


def test_list_apis_enforce_bounded_allowlist_filters() -> None:
    """任务和事故列表只接受有界 limit 与固定过滤字段和值。"""
    with _client() as client:
        task = client.get("/api/v1/tasks?status=running&task_kind=generic&limit=1")
        incident = client.get("/api/v1/incidents?status=active&rule=stalled&limit=1")
        bad_limit = client.get("/api/v1/tasks?limit=501")
        bad_field = client.get("/api/v1/incidents?severity=high")
        bad_value = client.get("/api/v1/tasks?status=unknown")

    assert task.status_code == 200 and len(task.json()["tasks"]) == 1
    assert incident.status_code == 200 and len(incident.json()["incidents"]) == 1
    assert bad_limit.status_code == bad_field.status_code == bad_value.status_code == 400


def test_embedded_ui_has_required_sections_and_no_external_assets() -> None:
    """首页应是无 CDN 的只读仪表盘，并以 5 到 10 秒间隔轮询。"""
    with _client() as client:
        response = client.get("/")

    html = response.text
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    for text in (
        "任务总览",
        "事故历史",
        "任务列表",
        "Collector 状态",
        "运行时状态",
        "进度时间线",
        "立即探测",
        "/api/v1/probes/collector",
        "/api/v1/probes/queue-source",
        "data.collector",
        'i.status==="resolved"',
    ):
        assert text in html
    assert "setInterval(refresh, 7000)" in html
    assert "cdn" not in html.lower()
    assert "linear-gradient" not in html.lower()
    assert "purple" not in html.lower()
    assert "取消" not in html
    assert "重试" not in html
    assert "重新排队" not in html
    assert 'fetch("/api/v1/probes/' not in html.split("async function refresh")[1]
