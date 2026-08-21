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
    assert event["status"] == "success"
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


def test_uses_normalized_result_scenario_for_feature_alias(fired_events):
    async def sif_run(feature: str, site: str = "US") -> dict:
        return {
            "success": True,
            "data": {"feature": "sales", "site": site},
            "error": None,
        }

    wrapped = telemetry_wrap(sif_run, module="sif")
    _run(wrapped("查销量"))

    assert fired_events[0]["dimensions"]["scenario"] == "sales"


def test_records_business_failure_as_error(fired_events):
    async def keepa_run(scenario: str) -> dict:
        return {
            "success": False,
            "data": None,
            "error": {"code": "KEEPA_QUOTA_EXCEEDED", "message": "额度不足"},
        }

    wrapped = telemetry_wrap(keepa_run, module="keepa")
    _run(wrapped(scenario="product"))

    event = fired_events[0]
    assert event["status"] == "error"
    assert event["error_type"] == "KEEPA_QUOTA_EXCEEDED"
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
