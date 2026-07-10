from __future__ import annotations

from types import MethodType
from typing import Any

import httpx

from opscli.asin_data.services import bi_report_data as bi_module
from opscli.asin_data.services.bi_report_data import (
    BI_REPORT_DATA_SOURCES,
    DEFAULT_BI_LOGIN_PASSWORD,
    DEFAULT_BI_LOGIN_USERNAME,
    AsinBiReportDataBusinessError,
    AsinBiReportDataClient,
)


class DummyAuthClient:
    def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        assert alias == "ops"
        return {"Authorization": "Bearer ops-token"}, {}


def _json_response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://example.test"))


def test_listing_auth_ignores_local_bi_env_and_prefers_managed_token(monkeypatch):
    monkeypatch.setenv("BI_AUTH", "Bearer stale-local-token")
    monkeypatch.setenv("BI_COOKIE", "polarisUserToken=stale")

    def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        return _json_response({"code": 200, "data": {"polaris_bjx_token": "managed-token"}})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        http_get=fake_get,
        ops_url="https://ops.example.test",
    )

    headers, cookies = client._build_listing_request_auth(
        fallback_headers={},
        fallback_cookies={},
    )

    assert headers["Authorization"] == "Bearer managed-token"
    assert cookies == {}


def test_listing_auth_retries_with_default_bi_login_when_managed_token_expires(monkeypatch):
    monkeypatch.setattr(bi_module, "_load_bi_login_config", lambda: {})
    post_calls: list[dict[str, Any]] = []

    def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        return _json_response({"code": 200, "data": {"polaris_bjx_token": "managed-token"}})

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        post_calls.append(kwargs)
        return _json_response({"code": 200, "data": {"token": "login-token"}})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        http_get=fake_get,
        http_post=fake_post,
        ops_url="https://ops.example.test",
    )
    seen_authorizations: list[str] = []

    def fake_fetch_listing_basic_source(self: AsinBiReportDataClient, **kwargs: Any) -> dict[str, Any]:
        seen_authorizations.append(kwargs["headers"]["Authorization"])
        if len(seen_authorizations) == 1:
            raise AsinBiReportDataBusinessError(401, "用户未登录")
        return {
            "key": kwargs["key"],
            "label": BI_REPORT_DATA_SOURCES["listing_basic"]["label"],
            "endpoint": BI_REPORT_DATA_SOURCES["listing_basic"]["endpoint"],
            "status": "success",
            "row_count": 1,
            "rows": [{"asin": "B0TEST"}],
            "raw": [],
        }

    client._fetch_listing_basic_source = MethodType(fake_fetch_listing_basic_source, client)

    result = client._fetch_source(
        key="listing_basic",
        config=BI_REPORT_DATA_SOURCES["listing_basic"],
        asins=["B0TEST"],
        start_date=None,
        end_date=None,
        headers={},
        cookies={},
    )

    assert result["status"] == "success"
    assert seen_authorizations == ["Bearer managed-token", "Bearer login-token"]
    assert post_calls[0]["json"]["username"] == DEFAULT_BI_LOGIN_USERNAME
    assert post_calls[0]["json"]["password"] == DEFAULT_BI_LOGIN_PASSWORD
