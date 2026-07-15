import httpx

from opscli.asin_data.services.report_files import AsinReportFileClient


class DummyAuthClient:
    def build_request_auth(self, scope: str):
        assert scope == "ops"
        return {"Authorization": "Bearer test"}, {"ops_token": "test"}


def test_report_file_client_fetches_matching_asin_site_url():
    calls = []

    def http_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "asin": "B0OTHER123",
                            "site": "US",
                            "file_url": "https://example.oss.aliyuncs.com/other.txt",
                        },
                        {
                            "asin": "B0TEST1234",
                            "site": "US",
                            "fileUrl": "https://example.oss.aliyuncs.com/report.txt",
                        },
                    ]
                },
            },
        )

    client = AsinReportFileClient(
        auth_client=DummyAuthClient(),
        endpoint="https://ops.example.com/dataMetrics/v1/asin-report-files",
        http_get=http_get,
    )

    result = client.fetch(asin=" b0test1234 ", site="us")

    assert result.asin == "B0TEST1234"
    assert result.site == "US"
    assert result.url == "https://example.oss.aliyuncs.com/report.txt"
    assert result.record["asin"] == "B0TEST1234"
    assert calls[0]["url"] == "https://ops.example.com/dataMetrics/v1/asin-report-files"
    assert calls[0]["params"] == {"asin": "B0TEST1234", "site": "US"}


def test_report_file_client_supports_top_level_file_url():
    def http_get(url, **kwargs):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "asin": "B0TEST1234",
                "site": "US",
                "file_url": "https://example.oss.aliyuncs.com/top-level.txt",
            },
        )

    client = AsinReportFileClient(
        auth_client=DummyAuthClient(),
        endpoint="https://ops.example.com/dataMetrics/v1/asin-report-files",
        http_get=http_get,
    )

    result = client.fetch(asin="B0TEST1234", site="US")

    assert result.url == "https://example.oss.aliyuncs.com/top-level.txt"


def test_report_file_client_resolves_endpoint_without_ops_api_prefix():
    calls = []

    def http_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "asin": "B0TEST1234",
                    "site": "US",
                    "file_url": "https://example.oss.aliyuncs.com/report.txt",
                },
            },
        )

    client = AsinReportFileClient(
        auth_client=DummyAuthClient(),
        ops_url="https://ops.api.qa.aukeyit.com/api",
        http_get=http_get,
    )

    result = client.fetch(asin="B0TEST1234", site="US")

    assert result.url == "https://example.oss.aliyuncs.com/report.txt"
    assert calls[0]["url"] == "https://ops.api.qa.aukeyit.com/dataMetrics/v1/asin-report-files"
    assert calls[0]["params"] == {"asin": "B0TEST1234", "site": "US"}


def test_report_file_client_upserts_report_file_records():
    calls = []

    def http_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "data": {
                    "inserted": 1,
                    "updated": 0,
                    "failed": 0,
                    "items": [{"asin": "B0TEST1234", "site": "US", "action": "inserted"}],
                },
            },
        )

    client = AsinReportFileClient(
        auth_client=DummyAuthClient(),
        endpoint="https://ops.example.com/dataMetrics/v1/asin-report-files",
        http_post=http_post,
    )

    result = client.upsert(
        request_id="run-1",
        source="asin_data_collect",
        idempotency_key="run-1",
        items=[
            {
                "asin": "B0TEST1234",
                "site": "US",
                "report_type": "asin_data_report_txt",
                "report_date": "2026-06-10",
            }
        ],
    )

    assert result["data"]["inserted"] == 1
    assert calls[0]["url"] == "https://ops.example.com/dataMetrics/v1/asin-report-files"
    assert calls[0]["json"]["request_id"] == "run-1"
    assert calls[0]["json"]["source"] == "asin_data_collect"
    assert calls[0]["json"]["idempotency_key"] == "run-1"
    assert calls[0]["json"]["items"][0]["asin"] == "B0TEST1234"
