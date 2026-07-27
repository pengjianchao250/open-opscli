import time

import httpx

from opscli.asin_data.services.bi_report_data import AsinBiReportDataClient


class OpsAuthClient:
    def __init__(self) -> None:
        self.build_calls: list[str] = []

    def build_request_auth(self, scope: str):
        self.build_calls.append(scope)
        assert scope == "ops"
        return {"Authorization": "Bearer ops-token"}, {"ops-cookie": "session"}


def _response(asin: str, *, rows: list[dict] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 200,
            "msg": "操作成功",
            "data": {
                "asin": asin,
                "site": "US",
                "total": len(rows or []),
                "list": rows or [],
            },
        },
    )


def test_listing_basic_posts_to_ops_proxy_and_preserves_response_contract():
    calls: list[dict] = []
    auth = OpsAuthClient()

    def http_get(*args, **kwargs):
        raise AssertionError("listing runtime must not call legacy GET endpoints")

    def http_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _response(
            "B0GN8LBPW9",
            rows=[
                {
                    "asin": "B0GN8LBPW9",
                    "ASIN": "B0GN8LBPW9",
                    "商品标题": "ONBRILL Round Coffee Table",
                    "商品亮点": ["Dual hidden storage"],
                }
            ],
        )

    client = AsinBiReportDataClient(
        auth_client=auth,
        ops_url="http://ops.example.com/api",
        ops_system_url="http://ops.example.com",
        http_get=http_get,
        http_post=http_post,
    )

    bundle = client.fetch(
        asins=["B0GN8LBPW9"],
        source_keys=["listing_basic"],
        site_by_asin={"B0GN8LBPW9": "US"},
    )

    assert auth.build_calls == ["ops"]
    assert len(calls) == 1
    assert calls[0]["url"] == "http://ops.example.com/api/v1/data-metrics/amazon-listing/basic"
    assert calls[0]["json"] == {"asin": "B0GN8LBPW9", "site": "US"}
    assert calls[0]["headers"]["Authorization"] == "Bearer ops-token"
    assert calls[0]["cookies"] == {"ops-cookie": "session"}
    assert calls[0]["timeout"] == 30
    source = bundle["sources"]["listing_basic"]
    assert source["status"] == "success"
    assert source["row_count"] == 1
    assert source["rows"] == [
        {
            "asin": "B0GN8LBPW9",
            "商品标题": "ONBRILL Round Coffee Table",
            "商品亮点": ["Dual hidden storage"],
            "site": "US",
        }
    ]
    assert list(source["raw"]) == ["B0GN8LBPW9"]


def test_listing_basic_batch_preserves_input_order_and_reports_partial_failures():
    auth = OpsAuthClient()

    def http_post(url, **kwargs):
        asin = kwargs["json"]["asin"]
        if asin == "B0FAIL1234":
            raise httpx.ConnectError("proxy unavailable")
        if asin == "B0SLOW1234":
            time.sleep(0.03)
        return _response(asin, rows=[{"ASIN": asin, "商品标题": f"Title {asin}"}])

    client = AsinBiReportDataClient(
        auth_client=auth,
        ops_system_url="http://ops.example.com",
        http_post=http_post,
    )

    source = client.fetch(
        asins=["B0SLOW1234", "B0FAIL1234", "B0FAST1234"],
        source_keys=["listing_basic"],
        default_site="US",
    )["sources"]["listing_basic"]

    assert source["status"] == "partial"
    assert [row["asin"] for row in source["rows"]] == ["B0SLOW1234", "B0FAST1234"]
    assert list(source["raw"]) == ["B0SLOW1234", "B0FAST1234"]
    assert list(source["errors_by_asin"]) == ["B0FAIL1234"]


def test_listing_basic_all_failures_return_failed_source():
    def http_post(url, **kwargs):
        raise httpx.ConnectError("proxy unavailable")

    client = AsinBiReportDataClient(
        auth_client=OpsAuthClient(),
        ops_system_url="http://ops.example.com",
        http_post=http_post,
    )

    source = client.fetch(
        asins=["B0FAIL1234"],
        source_keys=["listing_basic"],
    )["sources"]["listing_basic"]

    assert source["status"] == "failed"
    assert source["row_count"] == 0
    assert source["rows"] == []
    assert list(source["errors_by_asin"]) == ["B0FAIL1234"]


def test_listing_basic_empty_list_is_successful():
    client = AsinBiReportDataClient(
        auth_client=OpsAuthClient(),
        ops_system_url="http://ops.example.com",
        http_post=lambda url, **kwargs: _response(kwargs["json"]["asin"]),
    )

    source = client.fetch(
        asins=["B0EMPTY123"],
        source_keys=["listing_basic"],
    )["sources"]["listing_basic"]

    assert source["status"] == "success"
    assert source["row_count"] == 0
    assert source["rows"] == []
    assert source["errors_by_asin"] == {}
