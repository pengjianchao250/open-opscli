"""西柚 REST 的鉴权、治理、合同与日志联通测试。"""

import asyncio
import json
from typing import get_args

import httpx
import pytest
from starlette.testclient import TestClient

from opscli.api import create_api_app, wrap_mcp_app
from opscli.api.routers import xydc as router_module
from opscli.mcp import instrumentation, quota
from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.tools import xydc as tools
from opscli.xiyou.contracts import XydcOperation
from opscli.xiyou.providers.xydc_openapi import OPERATIONS, XydcOpenApiError


BODY = {"operation": "search_terms_info", "payload": {"country": "US", "searchTerms": ["bed frame"]}}
HEADERS = {"X-Ops-Token": "viewer-token", "X-User-Email": "Viewer@Example.com", "X-User-Id": "u-1"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    """隔离认证、限额与遥测；默认 Provider 不访问真实网络和凭据。"""
    monkeypatch.delenv("LOCAL_AUTH_FALLBACK_ENABLED", raising=False)
    monkeypatch.setenv("OPSCLI_MCP_QUOTA_ENABLED", "1")
    store = quota.SQLiteQuotaStore(tmp_path / "quota.sqlite3")
    monkeypatch.setattr(quota, "_default_limiter", quota.QuotaLimiter(store=store))
    monkeypatch.setattr(instrumentation, "_fire_mcp_event", lambda *a, **k: None)
    monkeypatch.setattr(quota, "_load_local_quota_email", lambda: None)

    class FakeProvider:
        async def call(self, operation, payload):
            return {"success": True, "data": payload, "error": None, "source": "xydc_openapi"}

    monkeypatch.setattr(tools, "XydcOpenApiProvider", FakeProvider)
    with TestClient(create_api_app()) as http:
        yield http


def test_catalog_is_public_and_matches_mcp_schema(client, monkeypatch):
    def forbidden():
        pytest.fail("读取目录不应创建 Provider")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", forbidden)
    response = client.get("/api/v1/xydc/scenarios")
    assert response.status_code == 200
    operations = {item["operation"] for item in response.json()["data"]}
    assert "client_quota" not in operations
    assert operations == set(OPERATIONS) - {"client_quota"} == set(get_args(XydcOperation))
    schema = client.get("/openapi.json").json()
    assert "/api/v1/xydc/run" in schema["paths"]
    contract = schema["components"]["schemas"]["XydcRunRequest"]
    assert set(contract["properties"]["operation"]["enum"]) == operations
    assert contract["additionalProperties"] is False


def test_client_quota_is_rejected_by_public_rest_contract(client, monkeypatch):
    def forbidden():
        pytest.fail("内部额度操作不应进入公共 REST 入口")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", forbidden)
    response = client.post(
        "/api/v1/xydc/run",
        headers=HEADERS,
        json={"operation": "client_quota", "payload": {}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_run_requires_apphub_identity_before_provider(client, monkeypatch):
    def forbidden():
        pytest.fail("未登录不应领取凭据")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", forbidden)
    # MCP Key 不能替代 REST 的 AppHub 登录态。
    response = client.post("/api/v1/xydc/run", headers={"Authorization": "Bearer mcp-key"}, json=BODY)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.parametrize("body", [
    {"operation": "not_an_operation", "payload": {}},
    {"operation": "search_terms_info", "payload": "not-an-object"},
    {"operation": "search_terms_info"},
    {**BODY, "jwt": "untrusted"},
    {**BODY, "session_id": "untrusted"},
    {**BODY, "userEmail": "other@example.com"},
    {**BODY, "api_key": "untrusted"},
    {**BODY, "endpoint": "https://other.example/"},
])
def test_contract_rejects_invalid_and_internal_parameters(client, monkeypatch, body):
    def forbidden():
        pytest.fail("错误合同不应调用 Provider")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", forbidden)
    response = client.post("/api/v1/xydc/run", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("operation", get_args(XydcOperation))
def test_all_operations_forward_payload_without_changing_fields(client, monkeypatch, operation):
    received = []

    class Provider:
        async def call(self, name, payload):
            received.append((name, payload))
            return {"success": True, "data": {}, "error": None}

    monkeypatch.setattr(tools, "XydcOpenApiProvider", Provider)
    payload = {"startWeek": {"startDate": "2026-09-07"}, "pageSize": 20}
    response = client.post("/api/v1/xydc/run", headers=HEADERS, json={"operation": operation, "payload": payload})
    assert response.status_code == 200
    assert received == [(operation, payload)]
    assert response.json()["quota"]["used"] == 1


@pytest.mark.parametrize(("code", "upstream_status", "expected"), [
    ("XYDC_OPENAPI_INVALID_PARAMS", None, 400),
    ("InvalidParams", 400, 400),
    ("APICredentialUnavailable", 401, 503),
    ("CreditBalanceInsufficient", 403, 503),
    ("APICredentialNotFound", 404, 503),
    ("XYDC_OPENAPI_CREDENTIAL_UNAVAILABLE", None, 503),
    ("RateLimitExceeded", 429, 429),
    ("InternalError", 500, 502),
    ("XYDC_OPENAPI_TRANSPORT_ERROR", None, 502),
])
def test_errors_map_http_status_and_refund_quota(client, monkeypatch, code, upstream_status, expected):
    class Provider:
        async def call(self, operation, payload):
            raise XydcOpenApiError(
                code, "业务错误", status_code=upstream_status, trace_id="trace-error",
                retry_after="12" if upstream_status == 429 else None,
            )

    monkeypatch.setattr(tools, "XydcOpenApiProvider", Provider)
    response = client.post("/api/v1/xydc/run", headers=HEADERS, json=BODY)
    assert response.status_code == expected
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code
    assert body["quota"]["used"] == 0
    assert body["quota"]["failures"] == 1
    assert "feedback" not in body
    if upstream_status == 429:
        assert response.headers["Retry-After"] == "12"
        assert body["error"]["trace_id"] == "trace-error"


def test_internal_exception_is_not_exposed(client, monkeypatch):
    class Provider:
        async def call(self, operation, payload):
            raise RuntimeError("mysql.internal password=do-not-expose")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", Provider)
    response = client.post("/api/v1/xydc/run", headers=HEADERS, json=BODY)
    assert response.status_code == 502
    assert "do-not-expose" not in response.text
    assert "mysql.internal" not in response.text
    assert response.json()["quota"]["used"] == 0


def test_missing_business_fields_fails_before_credential_lookup(client, monkeypatch, tmp_path):
    from opscli.xiyou.providers.xydc_audit import XydcAuditLogger
    from opscli.xiyou.providers.xydc_openapi import XydcOpenApiProvider

    class Pool:
        def acquire(self, *args, **kwargs):
            pytest.fail("必填参数缺失不应查询 MySQL")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", lambda: XydcOpenApiProvider(
        Pool(), audit_logger=XydcAuditLogger(tmp_path / "unused.jsonl"),
    ))
    response = client.post("/api/v1/xydc/run", headers=HEADERS,
                           json={"operation": "search_terms_info", "payload": {"country": "US"}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "XYDC_OPENAPI_INVALID_PARAMS"
    assert response.json()["quota"]["used"] == 0


def test_session_identity_comes_from_verified_session(client, monkeypatch):
    from opscli.auth import AuthClient
    from opscli.mcp.context import get_current_user_email

    monkeypatch.setattr(AuthClient, "get_me", lambda *a, **k: {
        "data": {"email": "verified@example.com", "id": "verified-user"},
    })
    observed = []

    class Provider:
        async def call(self, operation, payload):
            observed.append(get_current_user_email())
            return {"success": True, "data": {}, "error": None}

    monkeypatch.setattr(tools, "XydcOpenApiProvider", Provider)
    response = client.post("/api/v1/xydc/run", headers={
        "X-Session-Id": "session-value", "X-User-Email": "untrusted@example.com",
    }, json=BODY)
    assert response.status_code == 200
    assert observed == ["verified@example.com"]
    assert mcp_request_ctx.get() is None


def test_rest_and_mcp_share_user_quota_and_block_before_provider(client, monkeypatch):
    assert client.post("/api/v1/xydc/run", headers=HEADERS, json=BODY).json()["quota"]["used"] == 1

    async def mcp_calls():
        token = mcp_request_ctx.set({"email": "viewer@example.com"})
        try:
            run = instrumentation.quota_wrap(tools.ext_xydc_openapi_call)
            for _ in range(9):
                result = await run(**BODY)
            return result
        finally:
            mcp_request_ctx.reset(token)

    assert asyncio.run(mcp_calls())["quota"]["used"] == 10

    def forbidden():
        pytest.fail("耗尽限额后不得调用 Provider")

    monkeypatch.setattr(tools, "XydcOpenApiProvider", forbidden)
    response = client.post("/api/v1/xydc/run", headers=HEADERS, json=BODY)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "MCP_QUOTA_EXCEEDED"


def test_rest_provider_audit_captures_verified_user_query_and_result(client, monkeypatch, tmp_path, respx_mock):
    from opscli.api_credentials import ApiCredentialLease
    from opscli.xiyou.providers.xydc_audit import XydcAuditLogger
    from opscli.xiyou.providers.xydc_openapi import XydcOpenApiProvider

    acquired = []

    class Pool:
        def acquire(self, provider, **kwargs):
            acquired.append(provider)
            return ApiCredentialLease(14, provider, "test", "supplier-secret", 1)

        def report_success(self, lease, **kwargs):
            pass

    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(tools, "XydcOpenApiProvider", lambda: XydcOpenApiProvider(
        Pool(), audit_logger=XydcAuditLogger(path),
    ))
    route = respx_mock.post("https://openapi.xydc.com/v1/searchTerms/info").mock(
        return_value=httpx.Response(200, json={"list": [{"searchTerm": "bed frame"}], "debug": "supplier-secret"},
                                   headers={"X-Trace-Id": "trace-ok", "X-Cost-Credits": "1"})
    )
    response = client.post("/api/v1/xydc/run", headers=HEADERS, json=BODY)
    assert response.status_code == 200
    body = response.json()
    assert acquired == ["xydc_openapi"]
    assert route.calls.last.request.headers["X-Auth-Version"] == "2.0"
    assert body["source"] == "xydc_openapi"
    assert body["trace_id"] == "trace-ok"
    assert body["cost_credits"] == 1
    assert "supplier-secret" not in response.text
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["user_email"] == "viewer@example.com"
    assert event["user_id"] == "u-1"
    assert event["query"] == BODY["payload"]
    assert event["result"]["data"]["list"] == body["data"]["list"]
    assert "viewer-token" not in path.read_text(encoding="utf-8")
    assert "supplier-secret" not in path.read_text(encoding="utf-8")
    assert mcp_request_ctx.get() is None


def test_combined_app_exposes_rest_outside_mcp_key_boundary(client, monkeypatch):
    from starlette.applications import Starlette
    from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

    # 采用正式组合方式验证外层 MCP 鉴权不拦截 REST；避免启动无关采集任务。
    combined = ApiKeyAuthMiddleware(
        wrap_mcp_app(Starlette()), api_key="mcp-secret",
        protected_path_prefixes=("/mcp", "/sse"),
    )
    with TestClient(combined) as http:
        assert http.get("/api/v1/xydc/scenarios").status_code == 200
        assert http.post("/api/v1/xydc/run", json=BODY).status_code == 401
        assert http.post("/api/v1/xydc/run", headers=HEADERS, json=BODY).status_code == 200
