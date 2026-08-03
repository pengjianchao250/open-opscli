"""Collector Monitor Starlette API 与嵌入式 UI 契约测试。"""

from __future__ import annotations

import threading

import pytest
from starlette.testclient import TestClient

from opscli.collector_monitor.app import create_app
from opscli.collector_monitor.service import (
    CollectorMonitorScenarioAuthError,
    CollectorMonitorScenarioBusyError,
    CollectorMonitorScenarioCooldownError,
    CollectorMonitorScenarioDisabledError,
    CollectorMonitorScenarioOutcomeUnknownError,
    CollectorMonitorScenarioPermissionError,
    CollectorMonitorScenarioRejectedError,
    CollectorMonitorScenarioUnavailableError,
)


class FakeService:
    """提供固定缓存快照的应用服务替身。"""

    def __init__(self, *, ready: bool = True) -> None:
        self.is_ready = ready
        self.probe_calls: list[tuple[str, str | None]] = []
        self.scenario_calls: list[dict] = []
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

    async def manual_probe(self, target: str, *, api_key: str | None = None):
        self.probe_calls.append((target, api_key))
        return {
            "target": target,
            "probed_at": "2026-07-29T04:00:00+00:00",
            "status": "ready",
            "error_class": None,
        }

    def scenario_test_config(self):
        return {
            "enabled": True,
            "configured": True,
            "scenario": {"id": "keyword-reverse", "name": "关键词反查"},
            "defaults": {
                "site": "US",
                "period": "30d",
                "page_size": 100,
                "export_format": "json",
            },
        }

    async def submit_keyword_reverse(self, **arguments):
        self.scenario_calls.append(arguments)
        return {
            "scenario": "keyword-reverse",
            "job_id": "job-keyword-1",
            "state": "queued",
            "submitted_at": "2026-07-29T04:00:00+00:00",
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
    for name in ("tasks", "collector", "scenario", "runtimes", "incidents"):
        assert f'id="tab-{name}"' in html
        assert f'aria-controls="panel-{name}"' in html
        assert f'id="panel-{name}"' in html
        assert f'aria-labelledby="tab-{name}"' in html
    assert 'id="tab-tasks" type="button" role="tab"' in html
    assert 'id="panel-collector" role="tabpanel"' in html


def test_dashboard_exposes_controlled_keyword_reverse_scenario_form() -> None:
    """场景 Tab 应显示固定关键词反查和可编辑白名单参数。"""
    with _client() as client:
        html = client.get("/").text

    for text in (
        'id="tab-scenario"',
        'id="panel-scenario"',
        "关键词反查",
        "keyword-reverse",
        'id="scenario-asin"',
        'id="scenario-site" value="US"',
        'id="scenario-period" value="30d"',
        'id="scenario-page-size" type="number" min="1" max="100" value="100"',
        'id="scenario-confirmed" type="checkbox"',
        "会创建真实任务并消耗额度",
        "提交关键词反查任务",
        "/api/v1/commands/scenario-test",
        'id="scenario-api-key" type="password" maxlength="512" autocomplete="new-password" autocapitalize="off" spellcheck="false" required',
        'id="scenario-api-key-save" type="checkbox"',
    ):
        assert text in html


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


def test_scenario_test_contract_and_confirmed_submission() -> None:
    """场景接口仅公开固定关键词反查，并把确认后的白名单参数交给服务。"""
    service = FakeService()
    with TestClient(create_app(service, manage_polling=False)) as client:
        contract = client.get("/api/v1/commands/scenario-test")
        submitted = client.post(
            "/api/v1/commands/scenario-test",
            json={
                "api_key": "  temporary-mcp-key  ",
                "confirmed": True,
                "asin": " b07yrmt36l ",
                "site": "us",
                "period": "30d",
                "page_size": 100,
            },
        )

    assert contract.status_code == 200
    assert contract.json() == service.scenario_test_config()
    assert submitted.status_code == 202
    assert submitted.json()["job_id"] == "job-keyword-1"
    assert service.scenario_calls == [
        {
            "api_key": "temporary-mcp-key",
            "asin": "B07YRMT36L",
            "site": "US",
            "period": "30d",
            "page_size": 100,
        }
    ]
    assert "temporary-mcp-key" not in submitted.text


@pytest.mark.parametrize(
    "payload",
    [
        {"confirmed": False, "asin": "B07YRMT36L", "site": "US", "period": "30d", "page_size": 100},
        {"confirmed": True, "asin": "B07YRMT36L", "site": "US", "period": "30d", "page_size": 100},
        {"confirmed": True, "asin": "bad", "site": "US", "period": "30d", "page_size": 100},
        {
            "confirmed": True,
            "asin": "测试测试测试测试测试",
            "site": "US",
            "period": "30d",
            "page_size": 100,
        },
        {"confirmed": True, "asin": "B07YRMT36L", "site": "USA", "period": "30d", "page_size": 100},
        {
            "confirmed": True,
            "asin": "B07YRMT36L",
            "site": "美国",
            "period": "30d",
            "page_size": 100,
        },
        {
            "confirmed": True,
            "asin": "B07YRMT36L",
            "site": "ZZ",
            "period": "30d",
            "page_size": 100,
        },
        {"confirmed": True, "asin": "B07YRMT36L", "site": "US", "period": "forever", "page_size": 100},
        {"api_key": "key", "confirmed": True, "asin": "B07YRMT36L", "site": "US", "period": "٢٠٢٦-٠٨", "page_size": 100},
        {"confirmed": True, "asin": "B07YRMT36L", "site": "US", "period": "30d", "page_size": 101},
        {"confirmed": True, "asin": "B07YRMT36L", "site": "US", "period": "30d", "page_size": True},
        {"confirmed": True, "asin": "B07YRMT36L", "site": "US", "period": "30d", "page_size": 100, "tool": "arbitrary"},
    ],
)
def test_scenario_test_rejects_unconfirmed_or_invalid_payloads(payload: dict) -> None:
    """所有场景参数必须在白名单和固定边界内，拒绝后不得调用服务。"""
    service = FakeService()
    with TestClient(create_app(service, manage_polling=False)) as client:
        response = client.post("/api/v1/commands/scenario-test", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_scenario_payload"
    assert service.scenario_calls == []


def test_scenario_test_rejects_cross_origin_and_non_json_requests() -> None:
    """真实任务写接口只接受当前来源的 JSON 请求。"""
    service = FakeService()
    with TestClient(create_app(service, manage_polling=False)) as client:
        cross_origin = client.post(
            "/api/v1/commands/scenario-test",
            json={},
            headers={"Origin": "https://attacker.example"},
        )
        non_json = client.post("/api/v1/commands/scenario-test")

    assert cross_origin.status_code == 403
    assert cross_origin.json()["error"]["code"] == "cross_origin_scenario_denied"
    assert non_json.status_code == 415
    assert service.scenario_calls == []


def test_scenario_test_rejects_declared_oversized_body_before_buffering() -> None:
    """写接口应先按 Content-Length 拒绝超限请求。"""
    service = FakeService()
    with TestClient(create_app(service, manage_polling=False)) as client:
        response = client.post(
            "/api/v1/commands/scenario-test",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "4096"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_scenario_payload"
    assert service.scenario_calls == []


def test_scenario_cannot_borrow_server_api_key(tmp_path) -> None:
    """任何场景请求都不得借用 Monitor 的服务端密钥。"""
    service = FakeService()
    service.settings = type(
        "Settings",
        (),
        {
            "collector_mcp_api_key_file": tmp_path / "collector.key",
            "monitor_url": "http://testserver",
        },
    )()
    payload = {
        "confirmed": True,
        "asin": "B07YRMT36L",
        "site": "US",
        "period": "30d",
        "page_size": 100,
    }
    app = create_app(service, manage_polling=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        denied = client.post("/api/v1/commands/scenario-test", json=payload)

    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "invalid_scenario_payload"
    assert service.scenario_calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (CollectorMonitorScenarioDisabledError(), 403, "scenario_test_disabled"),
        (CollectorMonitorScenarioBusyError(), 409, "scenario_test_in_progress"),
        (CollectorMonitorScenarioCooldownError(7.5), 429, "scenario_test_cooldown"),
        (CollectorMonitorScenarioAuthError(), 401, "collector_auth_failed"),
        (CollectorMonitorScenarioPermissionError(), 403, "collector_permission_denied"),
        (CollectorMonitorScenarioRejectedError(), 422, "scenario_test_rejected"),
        (CollectorMonitorScenarioUnavailableError(), 503, "collector_unavailable"),
        (
            CollectorMonitorScenarioOutcomeUnknownError(),
            504,
            "scenario_outcome_unknown",
        ),
    ],
)
def test_scenario_test_maps_safe_operational_errors(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    """场景失败应返回稳定诊断码，不能回显异常或凭据。"""

    class FailingService(FakeService):
        async def submit_keyword_reverse(self, **arguments):
            raise error

    with TestClient(create_app(FailingService(), manage_polling=False)) as client:
        response = client.post(
            "/api/v1/commands/scenario-test",
            json={
                "api_key": "temporary-mcp-key",
                "confirmed": True,
                "asin": "B07YRMT36L",
                "site": "US",
                "period": "30d",
                "page_size": 100,
            },
        )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "temporary-mcp-key" not in response.text


def test_collector_probe_accepts_one_time_api_key_without_echoing_it() -> None:
    """临时 Key 只传给 Collector 服务调用，不得进入响应或缓存快照。"""
    service = FakeService()
    with TestClient(create_app(service, manage_polling=False)) as client:
        response = client.post(
            "/api/v1/probes/collector",
            json={"api_key": "  temporary-mcp-key  "},
        )

    assert response.status_code == 200
    assert service.probe_calls == [("collector", "temporary-mcp-key")]
    assert "temporary-mcp-key" not in response.text
    assert "temporary-mcp-key" not in repr(service.cached_snapshot)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/probes/queue-source", {"api_key": "mcp-key"}),
        ("/api/v1/probes/collector", {"api_key": 123}),
        ("/api/v1/probes/collector", {"api_key": ""}),
        ("/api/v1/probes/collector", {"api_key": "x" * 513}),
        ("/api/v1/probes/collector", {"url": "https://attacker.example"}),
    ],
)
def test_probe_rejects_invalid_or_out_of_scope_credentials(
    path: str,
    payload: dict,
) -> None:
    """探测参数必须有界，临时 Key 不得用于队列源或任意远端地址。"""
    with _client() as client:
        response = client.post(path, json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_probe_payload"
    assert "mcp-key" not in response.text


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
        "保存到此浏览器",
        'type="password"',
        'autocomplete="new-password"',
        'id="collector-api-key-save" type="checkbox"',
        "opscli.collector_monitor.collector_api_key",
        "localStorage.setItem",
        "localStorage.removeItem",
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
    assert "JSON.stringify({api_key:apiKey})" in html
    assert 'collectorKeyInput.value=""' in html
    assert "if(collectorKeySave.checked)" in html
    assert 'fetch("/api/v1/probes/' not in html.split("async function refresh")[1]
