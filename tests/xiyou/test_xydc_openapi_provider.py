"""西柚 OpenAPI v2 provider 测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from opscli.api_credentials import ApiCredentialLease
from opscli.xiyou.providers.xydc_audit import XydcAuditLogger
from opscli.xiyou.providers.xydc_openapi import (
    OPERATIONS,
    XydcOpenApiProvider,
    list_operations,
)


def _run(coro):
    return asyncio.run(coro)


def _lease(account_id: int, secret: str) -> ApiCredentialLease:
    return ApiCredentialLease(
        account_id=account_id,
        provider="xydc_openapi",
        account_name=f"openapi-{account_id}",
        secret=secret,
        secret_version=1,
    )


class FakePool:
    def __init__(self, *leases):
        self.leases = list(leases)
        self.acquire_calls = []
        self.successes = []
        self.failures = []

    def acquire(self, provider, *, exclude_account_ids=None):
        excluded = set(exclude_account_ids or ())
        self.acquire_calls.append((provider, excluded))
        for lease in self.leases:
            if lease.account_id not in excluded:
                return lease
        from opscli.api_credentials.exceptions import ApiCredentialUnavailableError

        raise ApiCredentialUnavailableError("none")

    def report_success(self, lease, *, runtime=None):
        self.successes.append((lease, runtime))

    def report_failure(self, lease, **kwargs):
        self.failures.append((lease, kwargs))


class FakeResponse:
    def __init__(self, status_code, body, *, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = httpx.Headers(headers or {})
        self.text = json.dumps(body, ensure_ascii=False)

    def json(self):
        return self._body


class FakeClient:
    outcomes = []
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, headers, json):
        self.__class__.calls.append({"url": url, "headers": headers, "json": json})
        outcome = self.__class__.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_legacy_asin_info_uses_openapi_v2_and_writes_audit_log(tmp_path: Path):
    FakeClient.calls = []
    FakeClient.outcomes = [
        FakeResponse(
            200,
            {"entities": [{"asin": "B012345678", "title": "sample"}], "debug": "secret-api-key"},
            headers={"X-Trace-Id": "trace-1", "X-Cost-Credits": "1"},
        )
    ]
    audit_path = tmp_path / "xydc.jsonl"
    pool = FakePool(_lease(1, "secret-api-key"))
    provider = XydcOpenApiProvider(
        pool,
        client_factory=FakeClient,
        audit_logger=XydcAuditLogger(audit_path),
    )

    result = _run(provider.call("get_asin_info", {"asins": ["B012345678"], "country": "US"}))

    assert result["source"] == "xydc_openapi"
    assert result["operation"] == "asin_info"
    assert FakeClient.calls[0]["url"] == "https://openapi.xydc.com/v1/asins/info"
    assert FakeClient.calls[0]["headers"]["X-Auth-Version"] == "2.0"
    assert FakeClient.calls[0]["headers"]["X-Api-Key"] == "secret-api-key"
    assert FakeClient.calls[0]["json"] == {
        "entities": [{"country": "US", "asin": "B012345678"}]
    }
    log = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert log["query"] == {"entities": [{"country": "US", "asin": "B012345678"}]}
    assert log["result"]["data"]["entities"][0]["title"] == "sample"
    assert "secret-api-key" not in audit_path.read_text(encoding="utf-8")


def test_all_documented_operations_are_registered():
    assert len(OPERATIONS) == 22
    assert len(list_operations()) == 21
    assert "client_quota" not in {item["operation"] for item in list_operations()}
    assert len(list_operations(include_internal=True)) == 22
    assert {item["method"] for item in list_operations()} == {"POST"}
    assert "/v1/client/quota" in {
        item["endpoint"] for item in list_operations(include_internal=True)
    }


def test_401_rotates_openapi_key_and_429_retries_without_rotation(tmp_path: Path):
    FakeClient.calls = []
    request = httpx.Request("POST", "https://openapi.xydc.com/v1/asins/traffic")
    unauthorized = FakeResponse(401, {"reason": "APICredentialUnavailable", "message": "bad key"})
    success = FakeResponse(200, {"entities": []}, headers={"X-Cost-Credits": "1"})
    FakeClient.outcomes = [unauthorized, success]
    pool = FakePool(_lease(1, "first"), _lease(2, "second"))
    provider = XydcOpenApiProvider(
        pool,
        client_factory=FakeClient,
        audit_logger=XydcAuditLogger(tmp_path / "audit.jsonl"),
    )

    result = _run(provider.call("get_asin_traffic", {"asins": ["B012345678"], "country": "US"}))

    assert result["success"] is True
    assert [item["headers"]["X-Api-Key"] for item in FakeClient.calls] == ["first", "second"]
    assert pool.failures[0][1]["disable"] is True

    FakeClient.calls = []
    FakeClient.outcomes = [
        FakeResponse(429, {"reason": "RateLimitExceeded"}, headers={"Retry-After": "0"}),
        success,
    ]
    result = _run(provider.call("get_asin_traffic", {"asins": ["B012345678"], "country": "US"}))
    assert result["success"] is True
    assert len(FakeClient.calls) == 2
    assert FakeClient.calls[0]["headers"]["X-Api-Key"] == FakeClient.calls[1]["headers"]["X-Api-Key"]
