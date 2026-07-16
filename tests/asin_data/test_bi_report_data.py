import threading
import time
from types import MethodType
from typing import Any

import httpx
import pytest

from opscli.asin_data.services import bi_report_data
from opscli.asin_data.services.bi_report_data import (
    BI_REPORT_DATA_SOURCES,
    LISTING_AUTH_MODE_ENV,
    AsinBiReportDataBusinessError,
    AsinBiReportDataClient,
    normalize_listing_basic,
    select_bi_report_data_for_asin,
)


class DummyAuthClient:
    def __init__(self) -> None:
        self.polaris_token = "user-token"
        self.build_calls: list[str] = []
        self.refresh_calls: list[str] = []

    def build_request_auth(self, scope: str):
        self.build_calls.append(scope)
        if scope == "ops":
            return {"Authorization": "Bearer test"}, {"ops_token": "test"}
        if scope == "polaris":
            return {"Authorization": f"Bearer {self.polaris_token}"}, {"polarisUserToken": "user-session"}
        raise AssertionError(f"unexpected auth scope: {scope}")

    def refresh_token(self, scope: str) -> str:
        self.refresh_calls.append(scope)
        if scope != "polaris":
            raise AssertionError(f"unexpected refresh scope: {scope}")
        self.polaris_token = "user-token-refreshed"
        return self.polaris_token


class NoOpsAuthClient:
    def build_request_auth(self, scope: str):
        raise AssertionError(f"unexpected auth scope: {scope}")


class MissingPolarisAuthClient:
    def __init__(self, *, session_error: Exception | None = None) -> None:
        self.session_error = session_error
        self.build_calls: list[str] = []

    def build_request_auth(self, scope: str):
        self.build_calls.append(scope)
        if scope == "polaris":
            raise RuntimeError("polaris system is not registered")
        if scope == "ops":
            return {"Authorization": "Bearer ops-token"}, {"ops_token": "ops-cookie"}
        raise AssertionError(f"unexpected auth scope: {scope}")

    def get_session(self, scope: str) -> str:
        assert scope == "polaris"
        if self.session_error is not None:
            raise self.session_error
        return "private-session-id"

    def get_device_code(self) -> None:
        return None


def test_listing_basic_retries_vc_account_type_when_sc_has_no_row(monkeypatch):
    client = object.__new__(AsinBiReportDataClient)
    account_types: list[int] = []

    def fake_fetch_one(**kwargs):
        account_types.append(kwargs["account_type"])
        if kwargs["account_type"] == 1:
            raise AsinBiReportDataBusinessError("LISTING_NOT_FOUND", "SC listing not found")
        return {
            "asin": kwargs["asin"],
            "row": {"ASIN": kwargs["asin"], "account_type": kwargs["account_type"]},
        }

    monkeypatch.setattr(client, "_fetch_listing_basic_for_asin", fake_fetch_one)

    result = client._fetch_listing_basic_source(
        key="listing_basic",
        config={"label": "listing", "endpoint": "/detail"},
        asins=["B086M58PQ3"],
        headers={},
        cookies={},
        site_by_asin={"B086M58PQ3": "US"},
        listing_account_type_by_asin={},
        default_site="US",
    )

    assert account_types == [1, 2]
    assert result["rows"] == [{"ASIN": "B086M58PQ3", "account_type": 2}]


def test_normalize_listing_basic_maps_item_highlight_value():
    row = normalize_listing_basic(
        asin="B0TEST1234",
        list_row={"id": 123},
        detail={"title_differentiation.value": "Quiet metal platform"},
        template={},
    )

    assert row["商品亮点"] == "Quiet metal platform"


def test_normalize_listing_basic_accepts_legacy_item_highlight_key():
    row = normalize_listing_basic(
        asin="B0TEST1234",
        list_row={"id": 123},
        detail={"title_differentiation": "Under-bed storage"},
        template={},
    )

    assert row["商品亮点"] == "Under-bed storage"


def test_bi_report_data_client_fetches_all_sources_and_filters_by_asin():
    get_calls = []
    post_calls = []

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        if url.endswith("/polaris-bjx-token"):
            return httpx.Response(
                200,
                json={"code": 200, "data": {"polaris_bjx_token": "remote-listing-token"}},
            )
        if url.endswith("/listing/getAmazonListing"):
            asin = kwargs["params"]["asin"]
            data = {"data": [{"id": 3418337, "asin": asin, "item_sku": "SKU-" + asin[-4:]}], "total": 1}
        elif url.endswith("/listing/amazonlisdet"):
            data = {
                "asin": "B0TEST1234",
                "listid": kwargs["params"]["listid"],
                "item_name.value": "Listing Endpoint Title",
                "brand.value": "ListingBrand",
                "generic_keyword.value": "storage bed frame search terms",
                "bullet_point.value1": "Listing bullet",
            }
        elif url.endswith("/sales-traffic-data"):
            data = {
                "rows": [
                    {"asin": "B0TEST1234", "salesAmount": 123.45},
                    {"asin": "B0OTHER123", "salesAmount": 7},
                ]
            }
        elif url.endswith("/sp-keyword-data"):
            data = [
                {"ASIN": "B0TEST1234", "keyword": "bed frame"},
                {"ASIN": "B0OTHER123", "keyword": "desk"},
            ]
        elif url.endswith("/deals-data"):
            data = {"asin": "B0TEST1234", "deal_name": "Prime Day"}
        elif url.endswith("/turnover-inventory-data"):
            data = {"records": [{"f_asin": "B0TEST1234", "available_inventory": 12}]}
        else:
            data = {"rows": [{"asin": "B0TEST1234", "商品标题": "Crawler Endpoint Title"}]}
        return httpx.Response(200, json={"code": 0, "data": data})

    def http_post(url, **kwargs):
        post_calls.append({"url": url, **kwargs})
        data = [
            {"ASIN": kwargs["json"]["asin"], "keyword": "bed frame"},
            {"ASIN": "B0OTHER123", "keyword": "desk"},
        ]
        return httpx.Response(200, json={"code": 0, "data": data})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.api.qa.aukeyit.com/api",
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(asins=[" b0test1234 ", "B0OTHER123", "B0TEST1234"])
    asin_bundle = select_bi_report_data_for_asin(bundle, asin="B0TEST1234")

    assert bundle["status"] == "success"
    assert bundle["asins"] == ["B0TEST1234", "B0OTHER123"]
    assert len(get_calls) == 8
    assert len(post_calls) == 2
    listing_calls = [call for call in get_calls if call["url"].endswith("/listing/getAmazonListing")]
    detail_calls = [call for call in get_calls if call["url"].endswith("/listing/amazonlisdet")]
    sales_call = next(call for call in get_calls if call["url"].endswith("/sales-traffic-data"))
    assert len(listing_calls) == 2
    assert listing_calls[0]["headers"]["Authorization"] == "Bearer user-token"
    assert listing_calls[0]["params"]["asin"] == "B0TEST1234"
    assert listing_calls[0]["params"]["site_code"] == "US"
    assert len(detail_calls) == 2
    assert detail_calls[0]["params"]["listid"] == 3418337
    assert "_t" in detail_calls[0]["params"]
    assert sales_call["url"] == "https://ops.api.qa.aukeyit.com/dataMetrics/v1/asin-report-files/sales-traffic-data"
    assert sales_call["params"] == {"asins": "B0TEST1234,B0OTHER123"}
    assert post_calls[0]["url"] == "https://ops.api.qa.aukeyit.com/api/v1/sp-search-term/query"
    assert post_calls[0]["json"]["asin"] == "B0TEST1234"
    assert get_calls[-1]["url"] == "https://ops.api.qa.aukeyit.com/dataMetrics/v1/asin-report-files/crawler-details"
    assert get_calls[-1]["params"] == {
        "asins": "B0TEST1234,B0OTHER123",
        "country": "US",
    }
    assert asin_bundle["sources"]["listing_basic"]["rows"][0]["关键词搜索"] == "storage bed frame search terms"
    assert asin_bundle["sources"]["listing_basic"]["rows"][0]["generic_keyword.value"] == "storage bed frame search terms"
    assert asin_bundle["sources"]["sales_traffic"]["rows"] == [{"asin": "B0TEST1234", "salesAmount": 123.45}]
    assert asin_bundle["sources"]["sp_search_term"]["rows"] == [{"ASIN": "B0TEST1234", "keyword": "bed frame"}]
    assert asin_bundle["sources"]["deals"]["rows"] == [{"asin": "B0TEST1234", "deal_name": "Prime Day"}]
    assert asin_bundle["sources"]["turnover_inventory"]["rows"] == [
        {"f_asin": "B0TEST1234", "available_inventory": 12}
    ]
    assert asin_bundle["sources"]["crawler_details"]["rows"] == [
        {"asin": "B0TEST1234", "商品标题": "Crawler Endpoint Title"}
    ]


def test_crawler_details_groups_asins_by_country_and_merges_rows():
    calls = []
    lock = threading.Lock()

    def http_get(url, **kwargs):
        with lock:
            calls.append(dict(kwargs["params"]))
        country = kwargs["params"]["country"]
        rows = [
            {"asin": asin, "country": country}
            for asin in kwargs["params"]["asins"].split(",")
        ]
        return httpx.Response(200, json={"code": 0, "data": {"rows": rows}})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(
        asins=["B0TEST1234", "B0TEST5678", "B0TEST9999"],
        source_keys=["crawler_details"],
        site_by_asin={"B0TEST5678": "CA", "B0TEST9999": "美国"},
        default_site="US",
    )

    source = bundle["sources"]["crawler_details"]
    calls_by_country = {call["country"]: call for call in calls}
    assert calls_by_country == {
        "US": {"asins": "B0TEST1234,B0TEST9999", "country": "US"},
        "CA": {"asins": "B0TEST5678", "country": "CA"},
    }
    assert source["status"] == "success"
    assert [row["asin"] for row in source["rows"]] == [
        "B0TEST1234",
        "B0TEST9999",
        "B0TEST5678",
    ]
    assert set(source["raw"]) == {"US", "CA"}
    assert source["country_errors"] == {}


def test_crawler_details_keeps_successful_country_when_another_country_fails():
    def http_get(url, **kwargs):
        country = kwargs["params"]["country"]
        if country == "CA":
            return httpx.Response(500, json={"message": "CA unavailable"})
        return httpx.Response(
            200,
            json={"code": 0, "data": {"rows": [{"asin": "B0TEST1234", "country": country}]}},
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(
        asins=["B0TEST1234", "B0TEST5678"],
        source_keys=["crawler_details"],
        site_by_asin={"B0TEST5678": "CA"},
    )

    source = bundle["sources"]["crawler_details"]
    assert bundle["status"] == "partial"
    assert source["status"] == "partial"
    assert source["rows"] == [{"asin": "B0TEST1234", "country": "US"}]
    assert source["country_errors"]["CA"] == {
        "code": "ASIN_BI_REPORT_DATA_HTTP_ERROR",
        "message": "CA unavailable",
        "status_code": 500,
    }


def test_crawler_details_returns_failed_when_all_countries_fail():
    def http_get(url, **kwargs):
        country = kwargs["params"]["country"]
        return httpx.Response(500, json={"message": f"{country} unavailable"})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(
        asins=["B0TEST1234", "B0TEST5678"],
        source_keys=["crawler_details"],
        site_by_asin={"B0TEST5678": "CA"},
    )

    source = bundle["sources"]["crawler_details"]
    assert bundle["status"] == "failed"
    assert source["status"] == "failed"
    assert source["rows"] == []
    assert set(source["country_errors"]) == {"US", "CA"}


def test_select_bi_report_data_filters_chinese_asin_group_rows():
    bundle = {
        "status": "success",
        "sources": {
            "sp_keyword": {
                "key": "sp_keyword",
                "label": "SP keyword data",
                "status": "success",
                "row_count": 3,
                "rows": [
                    {"ASIN\u7ec4": "B0FR59BZKL,B0GL8ZVH1S", "keyword": "match"},
                    {"ASIN\u7ec4": "B0FR559YYZ,B0GL8ZRD6X", "keyword": "other"},
                    {"ASIN\u7ec4": "B0FDG9KNXK; B0FR59BZKL", "keyword": "semicolon-match"},
                ],
            }
        },
    }

    asin_bundle = select_bi_report_data_for_asin(bundle, asin="B0FR59BZKL")

    assert asin_bundle["sources"]["sp_keyword"]["row_count"] == 2
    assert asin_bundle["sources"]["sp_keyword"]["source_row_count"] == 3
    assert asin_bundle["sources"]["sp_keyword"]["rows"] == [
        {"ASIN\u7ec4": "B0FR59BZKL,B0GL8ZVH1S", "keyword": "match"},
        {"ASIN\u7ec4": "B0FDG9KNXK; B0FR59BZKL", "keyword": "semicolon-match"},
    ]


def test_bi_report_data_client_filters_sources():
    get_calls = []

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        if url.endswith("/sales-traffic-data"):
            data = {"rows": [{"asin": "B0TEST1234", "salesAmount": 123.45}]}
        else:
            data = {"rows": [{"asin": "B0TEST1234", "deal_name": "Prime Day"}]}
        return httpx.Response(200, json={"code": 0, "data": data})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["sales_traffic", "deals"])

    assert bundle["status"] == "success"
    assert list(bundle["sources"]) == ["sales_traffic", "deals"]
    assert [call["url"] for call in get_calls] == [
        "https://ops.example.com/dataMetrics/v1/asin-report-files/sales-traffic-data",
        "https://ops.example.com/dataMetrics/v1/asin-report-files/deals-data",
    ]


def test_bi_report_data_client_fetches_bi_sources_in_parallel():
    state = {"active": 0, "max_active": 0}
    lock = threading.Lock()

    def http_get(url, **kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            time.sleep(0.05)
        finally:
            with lock:
                state["active"] -= 1
        if url.endswith("/sales-traffic-data"):
            data = {"rows": [{"asin": "B0TEST1234", "salesAmount": 123.45}]}
        elif url.endswith("/deals-data"):
            data = {"rows": [{"asin": "B0TEST1234", "deal_name": "Prime Day"}]}
        else:
            data = {"rows": [{"asin": "B0TEST1234", "available_inventory": 12}]}
        return httpx.Response(200, json={"code": 0, "data": data})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(
        asins=["B0TEST1234"],
        source_keys=["sales_traffic", "deals", "turnover_inventory"],
    )

    assert bundle["status"] == "success"
    assert state["max_active"] >= 2


def test_bi_report_data_client_fetches_sp_search_terms_in_parallel():
    state = {"active": 0, "max_active": 0}
    lock = threading.Lock()

    def http_post(url, **kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            time.sleep(0.05)
        finally:
            with lock:
                state["active"] -= 1
        asin = kwargs["json"]["asin"]
        return httpx.Response(200, json={"code": 0, "data": [{"ASIN": asin, "searchTerm": "bed frame"}]})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_post=http_post,
    )

    bundle = client.fetch(
        asins=["B0TEST1234", "B0TEST5678", "B0TEST9999"],
        source_keys=["sp_search_term"],
    )

    assert bundle["status"] == "success"
    assert state["max_active"] >= 2
    assert [row["ASIN"] for row in bundle["sources"]["sp_search_term"]["rows"]] == [
        "B0TEST1234",
        "B0TEST5678",
        "B0TEST9999",
    ]


def test_bi_report_data_client_fetches_sqp_with_short_domain_name():
    calls = []

    def http_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "date_range": {"start_date": "2026-07-01", "end_date": "2026-07-15"},
                    "total": 1,
                    "list": [{"ASIN": "B086M58PQ3", "搜索词": "bed frame"}],
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_post=http_post,
    )

    bundle = client.fetch(
        asins=["B086M58PQ3", "B0TEST1234"],
        start_date="2026-07-01",
        end_date="2026-07-15",
        source_keys=["sqp"],
    )

    assert calls[0]["url"] == "https://ops.example.com/api/v1/brand-analytics-search-query/query"
    assert calls[0]["json"] == {
        "asins": "B086M58PQ3,B0TEST1234",
        "start_date": "2026-07-01",
        "end_date": "2026-07-15",
    }
    assert bundle["sources"]["sqp"]["status"] == "success"
    assert bundle["sources"]["sqp"]["rows"] == [{"ASIN": "B086M58PQ3", "搜索词": "bed frame"}]


def test_bi_report_data_client_fetches_listing_basic_asins_in_parallel():
    state = {"active": 0, "max_active": 0, "site_codes": {}}
    lock = threading.Lock()

    def http_get(url, **kwargs):
        if url.endswith("/listing/getAmazonListing"):
            asin = kwargs["params"]["asin"]
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
                state["site_codes"][asin] = kwargs["params"].get("site_code")
            try:
                time.sleep(0.05)
            finally:
                with lock:
                    state["active"] -= 1
            return httpx.Response(200, json={"code": 0, "data": [{"id": f"list-{asin}", "asin": asin}]})
        listid = kwargs["params"]["listid"]
        asin = str(listid).replace("list-", "")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "listid": listid,
                    "item_name.value": f"Title {asin}",
                    "generic_keyword.value": "bed frame",
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        http_get=http_get,
    )

    bundle = client.fetch(
        asins=["B0TEST1234", "B0TEST5678"],
        source_keys=["listing_basic"],
        site_by_asin={"B0TEST5678": "CA"},
        default_site="US",
    )

    assert bundle["status"] == "success"
    assert state["max_active"] >= 2
    assert [row["asin"] for row in bundle["sources"]["listing_basic"]["rows"]] == [
        "B0TEST1234",
        "B0TEST5678",
    ]
    assert state["site_codes"] == {"B0TEST1234": "US", "B0TEST5678": "CA"}


def test_bi_report_data_client_uses_vc_account_type_per_asin():
    list_params_by_asin = {}

    def http_get(url, **kwargs):
        if url.endswith("/listing/getAmazonListing"):
            asin = kwargs["params"]["asin"]
            list_params_by_asin[asin] = dict(kwargs["params"])
            return httpx.Response(200, json={"code": 0, "data": [{"id": f"list-{asin}", "asin": asin}]})
        listid = kwargs["params"]["listid"]
        asin = str(listid).replace("list-", "")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "listid": listid,
                    "item_name.value": f"Title {asin}",
                    "generic_keyword.value": "bed frame",
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        http_get=http_get,
    )

    bundle = client.fetch(
        asins=["B0FY4QV7DR", "B0TEST1234"],
        source_keys=["listing_basic"],
        listing_account_type_by_asin={"B0FY4QV7DR": 2},
    )

    assert bundle["status"] == "success"
    assert list_params_by_asin["B0FY4QV7DR"]["asin"] == "B0FY4QV7DR"
    assert list_params_by_asin["B0FY4QV7DR"]["account_type"] == 2
    assert "item_name" not in list_params_by_asin["B0FY4QV7DR"]
    assert list_params_by_asin["B0TEST1234"]["asin"] == "B0TEST1234"
    assert list_params_by_asin["B0TEST1234"]["account_type"] == 1


def test_bi_report_data_client_listing_only_uses_remote_polaris_bjx_token(monkeypatch, tmp_path):
    monkeypatch.setenv(LISTING_AUTH_MODE_ENV, "managed")
    monkeypatch.delenv("BI_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("BI_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("BI_LOGIN_ENDPOINT", raising=False)
    monkeypatch.delenv("BI_LOGIN_COOKIE", raising=False)
    monkeypatch.setattr(bi_report_data, "CONFIG_DIR", tmp_path)
    get_calls = []

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        if url.endswith("/polaris-bjx-token"):
            assert kwargs["headers"]["Authorization"] == "Bearer test"
            assert kwargs["cookies"] == {"ops_token": "test"}
            return httpx.Response(
                200,
                json={"code": 200, "msg": "获取北极星token成功", "data": {"id": 1, "polaris_bjx_token": "bjx-token"}},
            )
        assert kwargs["headers"]["Authorization"] == "Bearer bjx-token"
        if url.endswith("/listing/getAmazonListing"):
            return httpx.Response(
                200,
                json={"code": 0, "data": [{"id": 3418337, "asin": "B0TEST1234"}]},
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "item_name.value": "Listing Endpoint Title",
                    "generic_keyword.value": "storage bed frame search terms",
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])

    assert bundle["status"] == "success"
    assert list(bundle["sources"]) == ["listing_basic"]
    assert [call["url"] for call in get_calls] == [
        "https://ops.example.com/dataMetrics/v1/asin-report-files/polaris-bjx-token",
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/amazonlisdet",
    ]


def test_bi_report_data_client_refreshes_current_polaris_user_when_listing_auth_expired(monkeypatch, tmp_path):
    monkeypatch.delenv(LISTING_AUTH_MODE_ENV, raising=False)
    monkeypatch.delenv("BI_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("BI_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("BI_LOGIN_ENDPOINT", raising=False)
    monkeypatch.delenv("BI_LOGIN_COOKIE", raising=False)
    monkeypatch.setattr(bi_report_data, "CONFIG_DIR", tmp_path)
    get_calls = []
    post_calls = []
    auth_client = DummyAuthClient()

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        if url.endswith("/listing/getAmazonListing") and kwargs["headers"]["Authorization"] == "Bearer user-token":
            return httpx.Response(200, json={"code": 401, "msg": "\u672a\u767b\u9646"})
        assert kwargs["headers"]["Authorization"] == "Bearer user-token-refreshed"
        if url.endswith("/listing/getAmazonListing"):
            return httpx.Response(200, json={"code": 0, "data": [{"id": 3418337, "asin": "B0TEST1234"}]})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "item_name.value": "Listing Endpoint Title",
                    "generic_keyword.value": "storage bed frame search terms",
                },
            },
        )

    def http_post(url, **kwargs):
        post_calls.append({"url": url, **kwargs})
        raise AssertionError(f"unexpected BI login call: {url}")

    client = AsinBiReportDataClient(
        auth_client=auth_client,
        ops_url="https://ops.example.com/api",
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])

    assert bundle["status"] == "success", bundle
    assert [call["url"] for call in get_calls] == [
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/amazonlisdet",
    ]
    assert post_calls == []
    assert auth_client.refresh_calls == ["polaris"]


def test_listing_auth_user_mode_stops_after_personal_polaris_success(monkeypatch):
    monkeypatch.delenv(LISTING_AUTH_MODE_ENV, raising=False)
    auth_client = DummyAuthClient()

    def http_get(url, **kwargs):
        raise AssertionError(f"managed BJX token endpoint must not be called: {url}")

    client = AsinBiReportDataClient(auth_client=auth_client, http_get=http_get)

    headers, cookies = client._build_listing_request_auth(fallback_headers={}, fallback_cookies={})

    assert headers["Authorization"] == "Bearer user-token"
    assert cookies == {"polarisUserToken": "user-session"}
    assert auth_client.build_calls == ["polaris"]


def test_listing_auth_falls_back_to_bjx_when_polaris_is_unregistered(monkeypatch):
    monkeypatch.delenv(LISTING_AUTH_MODE_ENV, raising=False)
    auth_client = MissingPolarisAuthClient(session_error=RuntimeError("no polaris session"))
    get_calls = []

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        return httpx.Response(200, json={"code": 200, "data": {"polaris_bjx_token": "managed-token"}})

    client = AsinBiReportDataClient(
        auth_client=auth_client,
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    headers, cookies = client._build_listing_request_auth(fallback_headers={}, fallback_cookies={})

    assert headers["Authorization"] == "Bearer managed-token"
    assert cookies == {}
    assert auth_client.build_calls == ["polaris", "ops"]
    assert get_calls[0]["url"].endswith("/polaris-bjx-token")


def test_listing_auth_falls_back_to_bjx_when_direct_exchange_returns_500(monkeypatch):
    monkeypatch.delenv(LISTING_AUTH_MODE_ENV, raising=False)
    monkeypatch.setattr(
        bi_report_data,
        "load_config",
        lambda: {
            "polaris_system_url": "https://polaris.example.com",
            "polaris_token_endpoint": "/api/auth/cli-token",
        },
    )
    auth_client = MissingPolarisAuthClient()
    post_calls = []

    def http_post(url, **kwargs):
        post_calls.append({"url": url, **kwargs})
        request = httpx.Request("POST", url)
        return httpx.Response(500, request=request, json={"message": "exchange unavailable"})

    def http_get(url, **kwargs):
        return httpx.Response(200, json={"code": 200, "data": {"polaris_bjx_token": "managed-token"}})

    client = AsinBiReportDataClient(
        auth_client=auth_client,
        ops_url="https://ops.example.com/api",
        http_get=http_get,
        http_post=http_post,
    )

    headers, cookies = client._build_listing_request_auth(fallback_headers={}, fallback_cookies={})

    assert headers["Authorization"] == "Bearer managed-token"
    assert cookies == {}
    assert post_calls[0]["url"] == "https://polaris.example.com/api/auth/cli-token"
    assert post_calls[0]["json"] == {"session_id": "private-session-id"}


def test_listing_auth_bjx_fallback_is_used_by_listing_request(monkeypatch):
    monkeypatch.delenv(LISTING_AUTH_MODE_ENV, raising=False)
    auth_client = MissingPolarisAuthClient(session_error=RuntimeError("no polaris session"))
    listing_authorizations = []

    def http_get(url, **kwargs):
        if url.endswith("/polaris-bjx-token"):
            return httpx.Response(200, json={"code": 200, "data": {"polaris_bjx_token": "managed-token"}})
        listing_authorizations.append(kwargs["headers"]["Authorization"])
        if url.endswith("/listing/getAmazonListing"):
            return httpx.Response(200, json={"code": 0, "data": [{"id": 3418337, "asin": "B0TEST1234"}]})
        return httpx.Response(200, json={"code": 0, "data": {"item_name.value": "Managed listing"}})

    client = AsinBiReportDataClient(
        auth_client=auth_client,
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])

    assert bundle["status"] == "success"
    assert listing_authorizations == ["Bearer managed-token", "Bearer managed-token"]


def test_listing_auth_reports_three_sanitized_failures(monkeypatch):
    monkeypatch.delenv(LISTING_AUTH_MODE_ENV, raising=False)
    client = AsinBiReportDataClient(auth_client=DummyAuthClient())
    monkeypatch.setattr(
        client,
        "_build_user_polaris_request_auth",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private-user-token")),
    )
    monkeypatch.setattr(
        client,
        "_build_direct_polaris_request_auth",
        lambda: (_ for _ in ()).throw(RuntimeError("private-session-id")),
    )
    monkeypatch.setattr(
        client,
        "_build_remote_polaris_bjx_request_auth",
        lambda: (_ for _ in ()).throw(RuntimeError("private-managed-token")),
    )

    with pytest.raises(AsinBiReportDataBusinessError) as exc_info:
        client._build_listing_request_auth(fallback_headers={}, fallback_cookies={})

    error = exc_info.value
    assert error.business_code == "POLARIS_USER_AUTH_MISSING"
    message = str(error)
    assert "Polaris user auth is missing or invalid" in message
    assert "direct token exchange failed" in message
    assert "managed BJX token fallback failed" in message
    assert "private-user-token" not in message
    assert "private-session-id" not in message
    assert "private-managed-token" not in message


def test_bi_report_data_client_listing_basic_maps_template_alias_fields(monkeypatch, tmp_path):
    monkeypatch.setenv(LISTING_AUTH_MODE_ENV, "managed")
    monkeypatch.delenv("BI_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("BI_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("BI_LOGIN_ENDPOINT", raising=False)
    monkeypatch.delenv("BI_LOGIN_COOKIE", raising=False)
    monkeypatch.setattr(bi_report_data, "CONFIG_DIR", tmp_path)
    get_calls = []

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        if url.endswith("/polaris-bjx-token"):
            return httpx.Response(
                200,
                json={"code": 200, "data": {"polaris_bjx_token": "bjx-token"}},
            )
        assert kwargs["headers"]["Authorization"] == "Bearer bjx-token"
        if url.endswith("/listing/getAmazonListing"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "id": 3528571,
                            "asin": "B0TEST1234",
                            "channel_id": 6224,
                        }
                    ],
                },
            )
        if url.endswith("/listing/amazonlisdet"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "listid": 3528571,
                        "channel_id": 6224,
                        "feed_product_type": "sofa",
                        "feed_product_type_id": 28522,
                        "item_type": "sofas",
                        "feed_type_info": (
                            '{"feed_product_type":"sofa","feed_product_type_id":28522,'
                            '"item_type":"sofas"}'
                        ),
                        "item_name.value": "Listing Endpoint Title",
                        "generic_keyword.value": "storage bed frame search terms",
                        "list_price.value": 299.99,
                        "list_price.currency": "USD",
                        "brand.value": "TemplateBrand",
                    },
                },
            )
        assert url.endswith("/amazon/feed/getTemplate")
        assert kwargs["params"]["feed_product_type"] == "sofa"
        assert kwargs["params"]["feed_product_type_id"] == 28522
        assert kwargs["params"]["item_type"] == "sofas"
        assert kwargs["params"]["channel_id"] == 6224
        assert kwargs["params"]["source_type"] == 1
        assert kwargs["params"]["listid"] == 3528571
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "resolve": {
                        "variation": [
                            {"field": "item_name.value", "alias": "产品标题"},
                            {"field": "brand.value", "alias": "品牌名"},
                            {"field": "list_price.currency", "alias": "厂商建议零售价币种"},
                            {"field": "list_price.value", "alias": "厂商建议零售价"},
                        ]
                    }
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])
    row = bundle["sources"]["listing_basic"]["rows"][0]

    assert row["产品标题"] == "Listing Endpoint Title"
    assert row["品牌名"] == "TemplateBrand"
    assert row["厂商建议零售价"] == 299.99
    assert row["厂商建议零售价币种"] == "USD"
    assert [call["url"] for call in get_calls] == [
        "https://ops.example.com/dataMetrics/v1/asin-report-files/polaris-bjx-token",
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/amazonlisdet",
        "https://bi.api.xenkee.com/amazon/feed/getTemplate",
    ]


def test_bi_report_data_client_listing_only_uses_bi_login_without_ops_auth(monkeypatch):
    monkeypatch.setenv(LISTING_AUTH_MODE_ENV, "bi_login")
    monkeypatch.setenv("BI_LOGIN_USERNAME", "service@example.com")
    monkeypatch.setenv("BI_LOGIN_PASSWORD", "secret-from-env")
    monkeypatch.setenv("BI_LOGIN_COOKIE", "seed_cookie=seed")
    get_calls = []
    post_calls = []

    def http_post(url, **kwargs):
        post_calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            headers={"set-cookie": "aukeypolarissystem_session=session-1; Path=/"},
            json={"code": 0, "data": {"access_token": "login-token"}},
        )

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        assert kwargs["headers"]["Authorization"] == "Bearer login-token"
        assert kwargs["cookies"]["seed_cookie"] == "seed"
        assert kwargs["cookies"]["aukeypolarissystem_session"] == "session-1"
        if url.endswith("/listing/getAmazonListing"):
            return httpx.Response(
                200,
                json={"code": 0, "data": [{"id": 3418337, "asin": "B0TEST1234"}]},
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "item_name.value": "Listing Endpoint Title",
                    "generic_keyword.value": "storage bed frame search terms",
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=NoOpsAuthClient(),
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])

    assert bundle["status"] == "success"
    assert list(bundle["sources"]) == ["listing_basic"]
    assert bundle["sources"]["listing_basic"]["row_count"] == 1
    assert len(post_calls) == 1
    assert post_calls[0]["url"] == "https://bi.api.xenkee.com/auth/login"
    assert post_calls[0]["json"]["username"] == "service@example.com"
    assert post_calls[0]["json"]["password"] == "secret-from-env"
    assert post_calls[0]["cookies"] == {"seed_cookie": "seed"}
    assert len(get_calls) == 2


def test_bi_report_data_client_uses_local_bi_login_config(monkeypatch, tmp_path):
    monkeypatch.setenv(LISTING_AUTH_MODE_ENV, "bi_login")
    monkeypatch.delenv("BI_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("BI_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("BI_LOGIN_ENDPOINT", raising=False)
    monkeypatch.delenv("BI_LOGIN_COOKIE", raising=False)
    monkeypatch.setattr(bi_report_data, "CONFIG_DIR", tmp_path)
    (tmp_path / "config.ini").write_text(
        "\n".join(
            [
                "[bi_login]",
                "username = service@example.com",
                "password = secret-from-local-config",
                "endpoint = https://bi.example.com/auth/login",
                "cookie = seed_cookie=seed-from-config",
            ]
        ),
        encoding="utf-8",
    )
    post_calls = []

    def http_post(url, **kwargs):
        post_calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            headers={"set-cookie": "aukeypolarissystem_session=session-from-config; Path=/"},
            json={"code": 0, "data": {"token": "config-token"}},
        )

    def http_get(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer config-token"
        assert kwargs["cookies"]["seed_cookie"] == "seed-from-config"
        assert kwargs["cookies"]["aukeypolarissystem_session"] == "session-from-config"
        if url.endswith("/listing/getAmazonListing"):
            return httpx.Response(
                200,
                json={"code": 0, "data": [{"id": 3418337, "asin": "B0TEST1234"}]},
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "item_name.value": "Listing Endpoint Title",
                    "generic_keyword.value": "storage bed frame search terms",
                },
            },
        )

    client = AsinBiReportDataClient(
        auth_client=NoOpsAuthClient(),
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])

    assert bundle["status"] == "success"
    assert len(post_calls) == 1
    assert post_calls[0]["url"] == "https://bi.example.com/auth/login"
    assert post_calls[0]["json"]["username"] == "service@example.com"
    assert post_calls[0]["json"]["password"] == "secret-from-local-config"
    assert post_calls[0]["cookies"] == {"seed_cookie": "seed-from-config"}


def test_bi_report_data_client_keeps_partial_failures():
    def http_get(url, **kwargs):
        return httpx.Response(200, json={"code": 0, "data": []})

    def http_post(url, **kwargs):
        return httpx.Response(500, json={"message": "boom"})

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(asins=["B0TEST1234"])

    assert bundle["status"] == "partial"
    assert bundle["sources"]["sp_search_term"]["status"] == "failed"
    assert bundle["sources"]["sp_search_term"]["endpoint"] == "/api/v1/sp-search-term/query"


def test_listing_basic_source_keeps_rows_when_one_asin_is_missing():
    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        http_get=lambda *args, **kwargs: httpx.Response(200, json={}),
        ops_url="https://ops.example.test",
    )

    def fake_fetch_listing_basic_for_asin(self: AsinBiReportDataClient, **kwargs: Any) -> dict[str, Any]:
        asin = kwargs["asin"]
        if asin == "B0MISS":
            raise AsinBiReportDataBusinessError("LISTING_NOT_FOUND", f"listing row not found for {asin}")
        return {
            "asin": asin,
            "row": {"ASIN": asin, "title": "hit"},
            "list_response": {},
            "detail_response": {},
        }

    client._fetch_listing_basic_for_asin = MethodType(fake_fetch_listing_basic_for_asin, client)

    result = client._fetch_listing_basic_source(
        key="listing_basic",
        config=BI_REPORT_DATA_SOURCES["listing_basic"],
        asins=["B0MISS", "B0HIT"],
        headers={},
        cookies={},
        site_by_asin={},
        listing_account_type_by_asin={},
        default_site="US",
    )

    assert result["status"] == "partial"
    assert result["row_count"] == 1
    assert result["rows"] == [{"ASIN": "B0HIT", "title": "hit"}]
    assert result["raw"][0]["status"] == "not_found"
    assert result["raw"][0]["error"]["business_code"] == "LISTING_NOT_FOUND"
    assert result["errors"] == ["B0MISS: listing row not found for B0MISS"]

def test_listing_site_by_asin_normalizes_chinese_country_name():
    assert bi_report_data._normalize_site_by_asin({"B086M58PQ3": "美国"}) == {"B086M58PQ3": "US"}
