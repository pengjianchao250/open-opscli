"""回放西柚日流量真实错误，验证业务分类、日期透传与恢复边界。"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from opscli.mcp.tools import xydc as tools
from opscli.xiyou.providers.xydc_audit import XydcAuditLogger
from opscli.xiyou.providers.xydc_openapi import XydcOpenApiError, XydcOpenApiProvider
from tests.xiyou.test_xydc_openapi_provider import FakePool, _lease


CAPTURE = json.loads((Path(__file__).parent / "fixtures" / "daily_traffic_range.json").read_text(encoding="utf-8"))
ENDPOINT = "https://openapi.xydc.com/v1/asins/trafficScore/trend/daily"


def _provider(tmp_path):
    pool = FakePool(_lease(1, "test-secret"), _lease(2, "other-secret"))
    provider = XydcOpenApiProvider(pool, audit_logger=XydcAuditLogger(tmp_path / "audit.jsonl"))
    return provider, pool


def test_captured_invalid_range_reaches_mcp_with_business_code_and_no_replay(tmp_path, respx_mock, monkeypatch):
    """真实 code/msg 错误不再泛化为 HTTP_400，且保留请求、Trace ID 与反馈证据。"""
    sample = CAPTURE["failed"]
    route = respx_mock.post(ENDPOINT).respond(400, json=sample["body"], headers={"X-Trace-Id": sample["trace_id"]})
    provider, pool = _provider(tmp_path)
    monkeypatch.setattr(tools, "XydcOpenApiProvider", lambda: provider)
    payload = dict(sample["request"])
    result = asyncio.run(tools.ext_xydc_openapi_call(operation="asin_traffic_score_daily", payload=payload))
    error = result["error"]
    assert result["success"] is False
    assert error["code"] == "InvalidTrendsRange"
    assert error["message"] == "Internal Server Error"
    assert error["details"] == sample["body"]
    assert error["status_code"] == 400
    assert error["trace_id"] == sample["trace_id"]
    assert "hint" in error
    assert route.call_count == len(pool.acquire_calls) == 1
    assert not pool.failures[0][1].get("disable")
    assert json.loads(route.calls.last.request.content) == payload == sample["request"]
    failed_call = result["feedback"]["execution_summary"]["failed_calls"][0]
    assert failed_call["call_params"]["payload"] == payload
    assert "InvalidTrendsRange" in failed_call["error_message"]
    event = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert event["query"] == payload
    assert event["error"] == error


def test_captured_available_range_preserves_dates_and_snapshot_totals(tmp_path, respx_mock):
    """可用 7 天样本完整透传，结果周期以返回日期为准，不按客户端昨日改标签。"""
    sample = CAPTURE["available"]
    route = respx_mock.post(ENDPOINT).respond(200, json=sample["body"], headers={"X-Trace-Id": sample["trace_id"], "X-Cost-Credits": "1"})
    provider, _ = _provider(tmp_path)
    result = asyncio.run(provider.call("asin_traffic_score_daily", sample["request"]))
    assert json.loads(route.calls.last.request.content) == sample["request"]
    assert result["data"] == sample["body"]
    trends = result["data"]["trends"]
    assert (trends[0]["date"], trends[-1]["date"], len(trends)) == ("2026-10-02", "2026-10-08", 7)
    assert sum(row["summaryTrafficScore"]["organic"] for row in trends) == 511
    assert sum(row["summaryTrafficScore"]["advertising"] for row in trends) == 3


@pytest.mark.parametrize("body,code,message", [
    ({"reason":"InvalidTrendsRange","message":"v2 message","code":400}, "InvalidTrendsRange", "v2 message"),
    ({"reason":"InvalidParams","message":"v2 message","code":"InvalidTrendsRange","msg":"legacy message"}, "InvalidParams", "v2 message"),
    ({"code":400,"msg":"numeric status"}, "HTTP_400", "numeric status"),
    ({"code":"400","msg":"text status"}, "HTTP_400", "text status"),
    ({"code":{"reason":"InvalidTrendsRange"}}, "HTTP_400", "西柚 OpenAPI 返回 HTTP 400"),
    ({"reason":"","message":"","code":"InvalidTrendsRange","msg":"legacy message"}, "InvalidTrendsRange", "legacy message"),
    (["unexpected body"], "HTTP_400", "西柚 OpenAPI 返回 HTTP 400"),
])
def test_error_formats_preserve_v2_priority_and_ignore_http_code(tmp_path, respx_mock, body, code, message):
    """兼容两种供应商响应，同时保持标准 v2 字段优先级和未知响应兜底。"""
    respx_mock.post(ENDPOINT).respond(400, json=body)
    provider, _ = _provider(tmp_path)
    with pytest.raises(XydcOpenApiError) as caught:
        asyncio.run(provider.call("asin_traffic_score_daily", CAPTURE["failed"]["request"]))
    error = caught.value.to_dict()
    assert error["code"] == code
    assert error["message"] == message
    assert error["details"] == body
    assert ("hint" in error) == (code == "InvalidTrendsRange")


def test_legacy_error_fields_remain_sanitized(tmp_path, respx_mock):
    """新解析的 msg 和 code 仍经过共享脱敏出口。"""
    body = {"code":"InvalidTrendsRange", "msg":"debug test-secret", "secret":"test-secret"}
    respx_mock.post(ENDPOINT).respond(400, json=body, headers={"X-Trace-Id":"trace-test-secret"})
    provider, _ = _provider(tmp_path)
    with pytest.raises(XydcOpenApiError) as caught:
        asyncio.run(provider.call("asin_traffic_score_daily", CAPTURE["failed"]["request"]))
    assert caught.value.message == "debug [REDACTED]"
    assert "test-secret" not in json.dumps(caught.value.to_dict())
    assert "test-secret" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_legacy_credit_error_uses_existing_credential_rotation(tmp_path, respx_mock):
    """新识别的额度业务码继续走原有轮换策略，不对普通 403 放宽重试。"""
    route = respx_mock.post(ENDPOINT).mock(side_effect=[
        httpx.Response(403, json={"code":"CreditBalanceInsufficient", "msg":"credit exhausted"}),
        httpx.Response(200, json=CAPTURE["available"]["body"]),
    ])
    provider, pool = _provider(tmp_path)
    result = asyncio.run(provider.call("asin_traffic_score_daily", CAPTURE["available"]["request"]))
    assert result["success"] is True
    assert route.call_count == len(pool.acquire_calls) == 2
    assert pool.failures[0][1]["exhausted"] is True


def test_ordinary_legacy_403_is_not_replayed(tmp_path, respx_mock):
    """参数以外的普通业务禁止错误不触发额度轮换。"""
    route = respx_mock.post(ENDPOINT).respond(403, json={"code":"Forbidden", "msg":"not allowed"})
    provider, pool = _provider(tmp_path)
    with pytest.raises(XydcOpenApiError) as caught:
        asyncio.run(provider.call("asin_traffic_score_daily", CAPTURE["available"]["request"]))
    assert caught.value.code == "Forbidden"
    assert route.call_count == len(pool.acquire_calls) == 1
