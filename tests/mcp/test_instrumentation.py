"""MCP 场景遥测切面的单元测试。"""

from __future__ import annotations

import asyncio
import json

import pytest

from opscli.mcp.instrumentation import telemetry_wrap


@pytest.fixture
def fired_events(monkeypatch):
    """捕获遥测事件并隔离设备和用户本地状态。"""
    events = []
    monkeypatch.setattr(
        "opscli.telemetry.reporter.TelemetryReporter.fire",
        staticmethod(lambda **event: events.append(event)),
    )
    monkeypatch.setattr("opscli.telemetry.device_id.get_device_id", lambda: "device-test")
    monkeypatch.setattr(
        "opscli.mcp.instrumentation._get_current_mcp_user_email",
        lambda: None,
    )
    monkeypatch.setattr(
        "opscli.mcp.instrumentation._get_current_mcp_client_name",
        lambda: None,
    )
    return events


def _run(coro):
    """使用仓库既有方式运行异步 MCP Tool 测试。"""
    return asyncio.run(coro)


def test_records_scenario_dimensions_without_sensitive_params(fired_events):
    async def seller_sprite_run(
        scenario: str,
        site: str = "US",
        jwt: str | None = None,
    ) -> dict:
        return {
            "success": True,
            "data": {"scenario": scenario, "site": site},
            "error": None,
        }

    wrapped = telemetry_wrap(
        seller_sprite_run,
        module="seller_sprite",
        runtime_role="executor",
    )
    _run(wrapped("keyword-reverse", jwt="secret-jwt"))

    assert len(fired_events) == 1
    event = fired_events[0]
    assert event["module"] == "seller_sprite"
    assert event["status"] == "called"
    assert event["dimensions"] == {
        "schema_version": 1,
        "service": "seller_sprite",
        "operation": "seller_sprite_run",
        "runtime_role": "executor",
        "scenario": "keyword-reverse",
        "site": "US",
    }
    assert event["raw_payload"] is None
    assert "secret-jwt" not in json.dumps(event, ensure_ascii=False)


def test_uses_declared_feature_as_scenario_dimension(fired_events):
    async def sif_run(feature: str, site: str = "US") -> dict:
        return {"success": True, "data": {"feature": "different"}, "error": None}

    wrapped = telemetry_wrap(sif_run, module="sif")
    _run(wrapped("查销量"))

    assert fired_events[0]["dimensions"]["scenario"] == "查销量"


def test_does_not_classify_business_failure(fired_events):
    async def keepa_run(scenario: str) -> dict:
        return {
            "success": False,
            "data": None,
            "error": {"code": "KEEPA_QUOTA_EXCEEDED", "message": "额度不足"},
        }

    wrapped = telemetry_wrap(keepa_run, module="keepa")
    _run(wrapped(scenario="product"))

    event = fired_events[0]
    assert event["status"] == "called"
    assert event["error_type"] is None
    assert event["dimensions"]["scenario"] == "product"


def test_does_not_classify_tool_exception(fired_events):
    """Tool 抛异常仍只记录调用事实，异常由业务链路自行处理。"""
    async def keepa_run(scenario: str) -> dict:
        raise RuntimeError("provider unavailable")

    wrapped = telemetry_wrap(keepa_run, module="keepa")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        _run(wrapped(scenario="product"))

    event = fired_events[0]
    assert event["status"] == "called"
    assert event["error_type"] is None
    assert event["dimensions"]["scenario"] == "product"


def test_keepa_event_records_user_email_and_scenario(fired_events, monkeypatch):
    """Keepa 场景事件必须可按用户邮箱和规范场景直接聚合。"""
    monkeypatch.setattr(
        "opscli.mcp.instrumentation._get_current_mcp_user_email",
        lambda: "user@example.com",
    )

    async def keepa_run(scenario: str, site: str = "US") -> dict:
        return {
            "success": True,
            "data": {"scenario": scenario, "site": site},
            "error": None,
        }

    wrapped = telemetry_wrap(keepa_run, module="keepa")
    _run(wrapped(scenario="product", site="DE"))

    event = fired_events[0]
    assert event["user_email"] == "user@example.com"
    assert event["dimensions"]["service"] == "keepa"
    assert event["dimensions"]["scenario"] == "product"
    assert event["dimensions"]["site"] == "DE"
    assert event["dimensions"]["runtime_role"] == "executor"


def test_dimension_resolver_adds_low_sensitivity_endpoint(fired_events):
    async def keepa_run(scenario: str) -> dict:
        return {"success": True}

    wrapped = telemetry_wrap(
        keepa_run,
        module="keepa",
        dimension_resolver=lambda arguments: {
            "endpoint": "search" if arguments.get("scenario") == "product-search" else None
        },
    )
    _run(wrapped(scenario="product-search"))

    assert fired_events[0]["dimensions"]["endpoint"] == "search"


def test_dimension_resolver_drops_full_endpoint_url(fired_events):
    async def tool(scenario: str) -> dict:
        return {"success": True}

    wrapped = telemetry_wrap(
        tool,
        module="external_service",
        dimension_resolver=lambda _arguments: {"endpoint": "https://api.example.test/v1"},
    )
    _run(wrapped(scenario="lookup"))

    assert "endpoint" not in fired_events[0]["dimensions"]


def test_marks_listing_analysis_operations_with_implicit_scenario(fired_events):
    async def seller_sprite_listing_analysis_status(job_id: str) -> dict:
        return {"success": True, "data": {"job_id": job_id}, "error": None}

    wrapped = telemetry_wrap(
        seller_sprite_listing_analysis_status,
        module="seller_sprite",
        runtime_role="gateway_proxy",
    )
    _run(wrapped(job_id="job-1"))

    assert fired_events[0]["dimensions"]["scenario"] == "listing-analysis"
    assert fired_events[0]["dimensions"]["runtime_role"] == "gateway_proxy"
