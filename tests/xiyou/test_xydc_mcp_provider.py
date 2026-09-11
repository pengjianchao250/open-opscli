"""西柚 MCP 多账号 Provider 测试。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from opscli.api_credentials import ApiCredentialLease
from opscli.api_credentials.exceptions import ApiCredentialUnavailableError
from opscli.mcp_client import RemoteMcpToolError
from opscli.xiyou.providers.xydc_mcp import (
    XYDC_MCP_URL,
    XydcMcpError,
    XydcMcpProvider,
)


def _run(coro):
    return asyncio.run(coro)


def _lease(account_id: int, secret: str) -> ApiCredentialLease:
    return ApiCredentialLease(
        account_id=account_id,
        provider="xydc_mcp",
        account_name=f"trial-{account_id}",
        secret=secret,
        secret_version=1,
    )


class FakePool:
    def __init__(self, leases):
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
        raise ApiCredentialUnavailableError("none")

    def report_success(self, lease, *, runtime=None):
        self.successes.append((lease, runtime))

    def report_failure(self, lease, **kwargs):
        self.failures.append((lease, kwargs))


def _client_factory(outcomes, calls):
    class FakeClient:
        def __init__(self, url, **kwargs):
            calls.append((url, kwargs))

        async def call_tool(self, tool_name, arguments):
            calls[-1] += (tool_name, arguments)
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    return FakeClient


def _remote_error(payload: dict) -> RemoteMcpToolError:
    raw_text = json.dumps(payload, ensure_ascii=False)
    return RemoteMcpToolError(
        raw_text,
        result=SimpleNamespace(isError=True),
        raw_text=raw_text,
    )


def test_provider_sends_fixed_url_and_exact_bearer_header_without_rotation():
    pool = FakePool([_lease(1, "mcp_primary")])
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory(
            [{"status": 200, "cost_credits": 1, "data": []}],
            calls,
        ),
    )

    result = _run(provider.call("get_asin_info", {"asins": ["B012345678"], "country": "US"}))

    assert result == {
        "success": True,
        "data": [],
        "error": None,
        "source": "xydc_mcp",
        "provider_status": 200,
        "cost_credits": 1,
    }
    assert calls == [
        (
            XYDC_MCP_URL,
            {
                "headers": {"Authorization": "Bearer mcp_primary"},
                "follow_redirects": False,
                "max_response_bytes": 10 * 1024 * 1024,
            },
            "get_asin_info",
            {"asins": ["B012345678"], "country": "US"},
        )
    ]
    assert len(pool.acquire_calls) == 1
    assert len(pool.successes) == 1
    assert pool.failures == []


def test_provider_rotates_only_after_confirmed_weekly_quota_exhaustion():
    pool = FakePool([_lease(1, "mcp_first"), _lease(2, "mcp_second")])
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory(
            [
                _remote_error(
                    {
                        "error": {
                            "code": "WEEKLY_QUOTA_EXCEEDED",
                            "quota_reset_at": "2026-09-14T00:00:00Z",
                        }
                    }
                ),
                {"status": "success", "cost_credits": 1, "data": {"ok": True}},
            ],
            calls,
        ),
    )

    result = _run(provider.call("get_keyword_info", {"keywords": ["charger"], "country": "US"}))

    assert result["success"] is True
    assert [call[1]["headers"]["Authorization"] for call in calls] == [
        "Bearer mcp_first",
        "Bearer mcp_second",
    ]
    assert pool.failures[0][1]["exhausted"] is True
    assert pool.failures[0][1]["runtime"]["quota_reset_at"] == "2026-09-14T00:00:00Z"
    assert pool.acquire_calls[1] == ("xydc_mcp", {1})


def test_provider_rotates_after_http_401_and_marks_token_invalid():
    pool = FakePool([_lease(1, "mcp_first"), _lease(2, "mcp_second")])
    request = httpx.Request("POST", XYDC_MCP_URL)
    unauthorized = httpx.HTTPStatusError(
        "authorization header rejected",
        request=request,
        response=httpx.Response(401, request=request),
    )
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory(
            [unauthorized, {"status": "success", "cost_credits": 1, "data": []}],
            calls,
        ),
    )

    result = _run(provider.call("get_asin_traffic", {"asins": ["B012345678"], "country": "US"}))

    assert result["success"] is True
    assert len(calls) == 2
    assert pool.failures[0][1]["disable"] is True
    assert pool.failures[0][1]["error_code"] == "xydc_invalid_token"


@pytest.mark.parametrize(
    "outcome",
    [
        RuntimeError("transport failed with mcp_secret_should_not_leak"),
        httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("POST", XYDC_MCP_URL),
            response=httpx.Response(503),
        ),
        {"status": "error", "error": {"code": "BAD_ARGUMENT", "message": "invalid country"}},
    ],
)
def test_provider_does_not_rotate_on_unclassified_transport_or_business_failure(outcome):
    pool = FakePool([_lease(1, "mcp_secret_should_not_leak"), _lease(2, "mcp_second")])
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory([outcome], calls),
    )

    with pytest.raises(XydcMcpError) as exc_info:
        _run(provider.call("get_keyword_info", {"keywords": ["charger"], "country": "US"}))

    assert exc_info.value.code == "XYDC_MCP_CALL_FAILED"
    assert "mcp_secret_should_not_leak" not in str(exc_info.value)
    assert len(calls) == 1
    assert len(pool.acquire_calls) == 1
    assert pool.failures[0][1].get("disable", False) is False
    assert pool.failures[0][1].get("exhausted", False) is False


def test_provider_treats_empty_data_as_success_and_redacts_echoed_token():
    secret = "mcp_secret_should_not_leak"
    pool = FakePool([_lease(1, secret), _lease(2, "mcp_second")])
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory(
            [
                {
                    "status": "success",
                    "cost_credits": 1,
                    "data": {"items": [], "debug": f"Bearer {secret}"},
                }
            ],
            calls,
        ),
    )

    result = _run(provider.call("get_asin_info", {"asins": [], "country": "US"}))

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["data"]["items"] == []
    assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert len(calls) == 1


def test_provider_stops_after_three_switchable_accounts():
    leases = [_lease(index, f"mcp_{index}") for index in range(1, 5)]
    pool = FakePool(leases)
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory(
            [
                _remote_error({"error": {"code": "INSUFFICIENT_CREDITS"}}),
                _remote_error({"error": {"code": "INSUFFICIENT_CREDITS"}}),
                _remote_error({"error": {"code": "INSUFFICIENT_CREDITS"}}),
            ],
            calls,
        ),
    )

    with pytest.raises(XydcMcpError) as exc_info:
        _run(provider.call("get_asin_info", {"asins": ["B012345678"], "country": "US"}))

    assert exc_info.value.code == "XYDC_MCP_ACCOUNTS_UNAVAILABLE"
    assert len(calls) == 3
    assert len(pool.failures) == 3


def test_provider_timeout_does_not_rotate_accounts():
    pool = FakePool([_lease(1, "mcp_first"), _lease(2, "mcp_second")])
    calls = []
    provider = XydcMcpProvider(
        pool,
        client_factory=_client_factory([httpx.ReadTimeout("read timed out")], calls),
    )

    with pytest.raises(XydcMcpError) as exc_info:
        _run(provider.call("get_asin_info", {"asins": ["B012345678"], "country": "US"}))

    assert exc_info.value.code == "XYDC_MCP_TIMEOUT"
    assert len(calls) == 1
    assert len(pool.acquire_calls) == 1


def test_provider_hides_credential_pool_connection_error():
    class BrokenPool:
        def acquire(self, provider, *, exclude_account_ids=None):
            raise RuntimeError("mysql.internal password=secret")

    provider = XydcMcpProvider(BrokenPool())

    with pytest.raises(XydcMcpError) as exc_info:
        _run(provider.call("get_asin_info", {"asins": ["B012345678"], "country": "US"}))

    assert exc_info.value.to_dict() == {
        "code": "XYDC_MCP_CREDENTIAL_POOL_UNAVAILABLE",
        "message": "西柚 MCP 凭据池不可用",
    }
