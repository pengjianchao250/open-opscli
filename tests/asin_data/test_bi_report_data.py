import threading
import time

import httpx

from opscli.asin_data.services import bi_report_data
from opscli.asin_data.services.bi_report_data import (
    AsinBiReportDataClient,
    select_bi_report_data_for_asin,
)


class DummyAuthClient:
    def build_request_auth(self, scope: str):
        assert scope == "ops"
        return {"Authorization": "Bearer test"}, {"ops_token": "test"}


class NoOpsAuthClient:
    def build_request_auth(self, scope: str):
        raise AssertionError(f"unexpected auth scope: {scope}")


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
    assert len(get_calls) == 9
    assert len(post_calls) == 2
    assert get_calls[0]["url"] == "https://ops.api.qa.aukeyit.com/dataMetrics/v1/asin-report-files/polaris-bjx-token"
    assert get_calls[1]["url"] == "https://bi.api.xenkee.com/listing/getAmazonListing"
    assert get_calls[1]["headers"]["Authorization"] == "Bearer remote-listing-token"
    assert get_calls[1]["params"]["asin"] == "B0TEST1234"
    assert get_calls[1]["params"]["site_code"] == "US"
    assert get_calls[2]["url"] == "https://bi.api.xenkee.com/listing/amazonlisdet"
    assert get_calls[2]["params"]["listid"] == 3418337
    assert "_t" in get_calls[2]["params"]
    assert get_calls[5]["url"] == "https://ops.api.qa.aukeyit.com/dataMetrics/v1/asin-report-files/sales-traffic-data"
    assert get_calls[5]["params"] == {"asins": "B0TEST1234,B0OTHER123"}
    assert post_calls[0]["url"] == "https://ops.api.qa.aukeyit.com/api/v1/sp-search-term/query"
    assert post_calls[0]["json"]["asin"] == "B0TEST1234"
    assert get_calls[-1]["url"] == "https://ops.api.qa.aukeyit.com/dataMetrics/v1/asin-report-files/crawler-details"
    assert get_calls[-1]["params"] == {"asins": "B0TEST1234,B0OTHER123"}
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


def test_bi_report_data_client_fetches_listing_basic_asins_in_parallel():
    state = {"active": 0, "max_active": 0, "site_codes": {}}
    lock = threading.Lock()

    def http_get(url, **kwargs):
        if url.endswith("/polaris-bjx-token"):
            return httpx.Response(
                200,
                json={"code": 200, "data": {"polaris_bjx_token": "bjx-token"}},
            )
        if url.endswith("/listing/getAmazonListing"):
            assert kwargs["headers"]["Authorization"] == "Bearer bjx-token"
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


def test_bi_report_data_client_listing_only_uses_remote_polaris_bjx_token(monkeypatch, tmp_path):
    monkeypatch.setenv("BI_AUTH", "Bearer stale-env-token")
    monkeypatch.setenv("BI_COOKIE", "stale_cookie=stale")
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

    assert bundle["status"] == "success", bundle
    assert list(bundle["sources"]) == ["listing_basic"]
    assert [call["url"] for call in get_calls] == [
        "https://ops.example.com/dataMetrics/v1/asin-report-files/polaris-bjx-token",
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/amazonlisdet",
    ]


def test_bi_report_data_client_logs_in_with_default_account_when_listing_auth_expired(monkeypatch, tmp_path):
    monkeypatch.delenv("BI_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("BI_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("BI_LOGIN_ENDPOINT", raising=False)
    monkeypatch.delenv("BI_LOGIN_COOKIE", raising=False)
    monkeypatch.setattr(bi_report_data, "CONFIG_DIR", tmp_path)
    get_calls = []
    post_calls = []

    def http_get(url, **kwargs):
        get_calls.append({"url": url, **kwargs})
        if url.endswith("/polaris-bjx-token"):
            return httpx.Response(200, json={"code": 200, "data": {"polaris_bjx_token": "stale-token"}})
        if url.endswith("/listing/getAmazonListing") and kwargs["headers"]["Authorization"] == "Bearer stale-token":
            return httpx.Response(200, json={"code": 401, "msg": "\u672a\u767b\u9646"})
        assert kwargs["headers"]["Authorization"] == "Bearer login-token"
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
        return httpx.Response(
            200,
            headers={"set-cookie": "aukeypolarissystem_session=session-1; Path=/"},
            json={"code": 0, "data": {"access_token": "login-token"}},
        )

    client = AsinBiReportDataClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.example.com/api",
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(asins=["B0TEST1234"], source_keys=["listing_basic"])

    assert bundle["status"] == "success", bundle
    assert [call["url"] for call in get_calls] == [
        "https://ops.example.com/dataMetrics/v1/asin-report-files/polaris-bjx-token",
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/getAmazonListing",
        "https://bi.api.xenkee.com/listing/amazonlisdet",
    ]
    assert len(post_calls) == 1
    assert post_calls[0]["url"] == "https://bi.api.xenkee.com/auth/login"
    assert post_calls[0]["json"]["username"] == "wanglintao@aukeys.com"
    assert post_calls[0]["json"]["password"] == "wlt123456"


def test_bi_report_data_client_listing_basic_maps_template_alias_fields(monkeypatch, tmp_path):
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
