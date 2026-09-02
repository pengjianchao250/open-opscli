"""SellerSprite 产品化 REST API 合同测试。"""

import asyncio

from starlette.testclient import TestClient


def _authenticate(monkeypatch) -> None:
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: "user@example.com",
    )


def test_seller_sprite_submit_requires_authenticated_user(monkeypatch):
    from opscli.api import create_api_app

    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email",
        lambda: None,
    )

    response = TestClient(create_api_app()).post(
        "/api/v1/seller-sprite/jobs",
        json={"scenario": "keyword-reverse", "params": {"asin": "B012345678"}},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_seller_sprite_submit_proxies_to_collector_and_returns_202(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    captured = {}

    async def fake_proxy(fn, **kwargs):
        captured["tool"] = fn.__name__
        captured["kwargs"] = kwargs
        return {
            "success": True,
            "data": {"job_id": "job-1", "state": "queued"},
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).post(
        "/api/v1/seller-sprite/jobs",
        json={
            "scenario": "keyword-reverse",
            "params": {"asin": "B012345678"},
            "site": "US",
            "period": "30d",
            "page_size": 100,
            "export_format": "json",
            "job_id": "job-1",
        },
    )

    assert response.status_code == 202
    assert response.json()["data"] == {"job_id": "job-1", "state": "queued"}
    assert captured == {
        "tool": "seller_sprite_run",
        "kwargs": {
            "scenario": "keyword-reverse",
            "params": {"asin": "B012345678"},
            "site": "US",
            "period": "30d",
            "page_size": 100,
            "export_format": "json",
            "job_id": "job-1",
        },
    }


def test_seller_sprite_submit_rejects_internal_runtime_fields(monkeypatch):
    from opscli.api import create_api_app

    _authenticate(monkeypatch)
    response = TestClient(create_api_app()).post(
        "/api/v1/seller-sprite/jobs",
        json={
            "scenario": "keyword-reverse",
            "params": {"asin": "B012345678"},
            "session_id": "must-not-be-accepted",
            "jwt": "must-not-be-accepted",
            "output_dir": "C:/private",
            "mode": "api-direct",
        },
    )

    assert response.status_code == 422


def test_seller_sprite_job_status_forwards_bounded_wait(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    captured = {}

    async def fake_proxy(fn, **kwargs):
        captured["tool"] = fn.__name__
        captured["kwargs"] = kwargs
        return {
            "success": True,
            "data": {"job_id": kwargs["job_id"], "state": "running"},
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-1?wait_seconds=30"
    )

    assert response.status_code == 200
    assert captured == {
        "tool": "seller_sprite_job_status",
        "kwargs": {"job_id": "job-1", "wait_seconds": 30},
    }


def test_seller_sprite_json_status_hides_download_link(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)

    async def fake_proxy(_fn, **_kwargs):
        return {
            "success": True,
            "data": {
                "job_id": "job-json",
                "state": "succeeded",
                "row_count": 1,
                "data": [{"keyword": "charger"}],
                "export": {
                    "format": "json",
                    "url": "https://files.example.com/job-json.json",
                },
            },
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-json"
    )

    assert response.status_code == 200
    assert response.json()["data"]["data"] == [{"keyword": "charger"}]
    assert "export" not in response.json()["data"]


def test_seller_sprite_json_result_returns_inline_business_data(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    captured = {}

    async def fake_proxy(fn, **kwargs):
        captured["tool"] = fn.__name__
        captured["kwargs"] = kwargs
        return {
            "success": True,
            "data": {
                "job_id": "job-json",
                "scenario": "keyword-reverse",
                "site": "US",
                "period": "30d",
                "state": "succeeded",
                "stage": "finished",
                "row_count": 1,
                "data": [{"keyword": "charger"}],
                "warnings": [],
                "export": {
                    "format": "json",
                    "url": "https://files.example.com/job-json.json",
                },
            },
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-json/result?wait_seconds=30"
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "job_id": "job-json",
            "scenario": "keyword-reverse",
            "site": "US",
            "period": "30d",
            "state": "succeeded",
            "stage": "finished",
            "ready": None,
            "row_count": 1,
            "result": [{"keyword": "charger"}],
        },
        "error": None,
    }
    assert captured == {
        "tool": "seller_sprite_job_status",
        "kwargs": {"job_id": "job-json", "wait_seconds": 30},
    }


def test_seller_sprite_json_result_returns_202_while_running(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)

    async def fake_proxy(_fn, **_kwargs):
        return {
            "success": True,
            "data": {"job_id": "job-running", "state": "running", "stage": "fetch"},
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-running/result"
    )

    assert response.status_code == 202
    assert response.json()["data"]["state"] == "running"


def test_seller_sprite_json_result_preserves_failed_task_status(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)

    async def fake_proxy(_fn, **_kwargs):
        return {
            "success": True,
            "data": {
                "job_id": "job-failed",
                "state": "failed",
                "error": {"code": "UPSTREAM_FAILED", "message": "query failed"},
            },
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-failed/result"
    )

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "failed"
    assert response.json()["data"]["error"]["code"] == "UPSTREAM_FAILED"


def test_seller_sprite_json_export_route_returns_inline_result(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    tools = []

    async def fake_proxy(fn, **_kwargs):
        tools.append(fn.__name__)
        return {
            "success": True,
            "data": {
                "job_id": "job-json",
                "state": "succeeded",
                "row_count": 1,
                "data": [{"keyword": "charger"}],
                "export": {
                    "format": "json",
                    "url": "https://files.example.com/job-json.json",
                },
            },
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-json/export"
    )

    assert response.status_code == 200
    assert response.json()["data"]["result"] == [{"keyword": "charger"}]
    assert "url" not in str(response.json())
    assert tools == ["seller_sprite_job_status"]


def test_seller_sprite_xlsx_export_keeps_download_contract(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    tools = []

    async def fake_proxy(fn, **_kwargs):
        tools.append(fn.__name__)
        if fn.__name__ == "seller_sprite_job_status":
            return {
                "success": True,
                "data": {
                    "job_id": "job-xlsx",
                    "state": "succeeded",
                    "export": {"format": "xlsx"},
                },
                "error": None,
            }
        return {
            "success": True,
            "data": {
                "format": "xlsx",
                "url": "https://files.example.com/job-xlsx.xlsx",
            },
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/jobs/job-xlsx/export"
    )

    assert response.status_code == 200
    assert response.json()["data"]["url"].endswith("job-xlsx.xlsx")
    assert tools == ["seller_sprite_job_status", "seller_sprite_export"]


def test_seller_sprite_collector_unavailable_maps_to_503(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)

    async def fake_proxy(_fn, **_kwargs):
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "COLLECTOR_MCP_UNAVAILABLE",
                "message": "数据采集服务不可用",
            },
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/scenarios"
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "COLLECTOR_MCP_UNAVAILABLE"


def test_seller_sprite_unexpected_proxy_failure_maps_to_502(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)

    async def fail_proxy(**_kwargs):
        raise RuntimeError("internal proxy failure")

    result = asyncio.run(api_module._call_gateway_proxy(fail_proxy))
    response = api_module._result_response(result)

    assert response.status_code == 502


def test_seller_sprite_batch_status_uses_static_route(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    captured = {}

    async def fake_proxy(fn, **kwargs):
        captured["tool"] = fn.__name__
        captured["kwargs"] = kwargs
        return {
            "success": True,
            "data": {"ready": False, "jobs": []},
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).post(
        "/api/v1/seller-sprite/jobs/status",
        json={"job_ids": ["job-1", "job-2"], "wait_seconds": 5},
    )

    assert response.status_code == 200
    assert captured == {
        "tool": "seller_sprite_jobs_status",
        "kwargs": {"job_ids": ["job-1", "job-2"], "wait_seconds": 5},
    }


def test_seller_sprite_listing_analysis_keeps_separate_contract(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)
    captured = {}

    async def fake_proxy(fn, **kwargs):
        captured["tool"] = fn.__name__
        captured["kwargs"] = kwargs
        return {
            "success": True,
            "data": {"job_id": "listing-job", "state": "queued"},
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).post(
        "/api/v1/seller-sprite/listing-analysis/jobs",
        json={
            "asin": "B012345678",
            "station": "GLOBAL",
            "site": "US",
            "export_format": "json",
            "job_id": "listing-job",
        },
    )

    assert response.status_code == 202
    assert captured == {
        "tool": "seller_sprite_listing_analysis_submit",
        "kwargs": {
            "asin": "B012345678",
            "station": "GLOBAL",
            "site": "US",
            "export_format": "json",
            "job_id": "listing-job",
        },
    }


def test_seller_sprite_listing_analysis_json_result_is_inline(monkeypatch):
    from opscli.api import create_api_app
    from opscli.api import seller_sprite as api_module

    _authenticate(monkeypatch)

    async def fake_proxy(_fn, **_kwargs):
        return {
            "success": True,
            "data": {
                "job_id": "listing-job",
                "state": "succeeded",
                "ready": True,
                "row_count": 1,
                "data": [{"asin": "B012345678", "score": 88}],
                "export": {
                    "format": "json",
                    "url": "https://files.example.com/listing-job.json",
                },
            },
            "error": None,
        }

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    response = TestClient(create_api_app()).get(
        "/api/v1/seller-sprite/listing-analysis/jobs/listing-job/result"
    )

    assert response.status_code == 200
    assert response.json()["data"]["result"] == [
        {"asin": "B012345678", "score": 88}
    ]
    assert "url" not in str(response.json())


def test_seller_sprite_route_is_behind_shared_api_key_middleware(monkeypatch):
    from opscli.api import seller_sprite as api_module
    from opscli.mcp.server import _build_dual_endpoint_app

    _authenticate(monkeypatch)

    async def fake_proxy(fn, **kwargs):
        assert fn.__name__ == "seller_sprite_scenarios"
        assert kwargs == {}
        return {"success": True, "data": [{"scenario_id": "keyword-reverse"}], "error": None}

    monkeypatch.setattr(api_module, "_call_gateway_proxy", fake_proxy)
    app = _build_dual_endpoint_app(api_key="test-api-key")

    with TestClient(app) as client:
        unauthorized = client.get("/api/v1/seller-sprite/scenarios")
        authorized = client.get(
            "/api/v1/seller-sprite/scenarios",
            headers={"Authorization": "Bearer test-api-key"},
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["data"] == [{"scenario_id": "keyword-reverse"}]


def test_seller_sprite_api_registers_complete_job_route_set():
    from opscli.api import create_api_app

    paths = set(create_api_app().openapi()["paths"])

    assert {
        "/api/v1/seller-sprite/scenarios",
        "/api/v1/seller-sprite/quota",
        "/api/v1/seller-sprite/jobs",
        "/api/v1/seller-sprite/jobs/{job_id}",
        "/api/v1/seller-sprite/jobs/{job_id}/result",
        "/api/v1/seller-sprite/jobs/status",
        "/api/v1/seller-sprite/jobs/{job_id}/export",
        "/api/v1/seller-sprite/listing-analysis/jobs",
        "/api/v1/seller-sprite/listing-analysis/jobs/{job_id}",
        "/api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result",
    } <= paths
