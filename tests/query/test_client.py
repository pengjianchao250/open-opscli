import json

import httpx
import pytest

from opscli.query.client import QueryClient
from opscli.query.exceptions import BadRemoteJsonError, RemoteBusinessError


class DummyAuthClient:
    def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        assert alias == "ops"
        return (
            {"Authorization": "Bearer jwt-token"},
            {
                "polarisUserToken": "session-123",
                "opscliDeviceCode": "dc-abc",
            },
        )


def test_cli_query_sends_auth_headers_and_cookies(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={"rows": [], "meta": {"rowCount": 0}},
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.post", fake_post)
    client = QueryClient(auth_client=DummyAuthClient())
    payload = {"tableId": 1103, "query": {"select": []}}

    result = client.cli_query(payload)

    assert captured["url"].endswith("/v1/data-metrics/cli-query")
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["cookies"]["opscliDeviceCode"] == "dc-abc"
    assert captured["timeout"] == 30
    assert result["meta"]["rowCount"] == 0


def test_cli_query_raises_business_error(monkeypatch):
    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(200, json={"code": 403, "msg": "无该数据集访问权限"})

    monkeypatch.setattr("opscli.query.transport.client.httpx.post", fake_post)
    client = QueryClient(auth_client=DummyAuthClient())

    with pytest.raises(RemoteBusinessError) as exc_info:
        client.cli_query({"tableId": 1103, "query": {"select": []}})

    assert exc_info.value.business_code == 403
    assert str(exc_info.value) == "无该数据集访问权限"


def test_cli_query_raises_when_remote_json_invalid(monkeypatch):
    class DummyResponse:
        status_code = 200

        def json(self):
            raise json.JSONDecodeError("bad", "x", 0)

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return DummyResponse()

    monkeypatch.setattr("opscli.query.transport.client.httpx.post", fake_post)
    client = QueryClient(auth_client=DummyAuthClient())

    with pytest.raises(BadRemoteJsonError):
        client.cli_query({"tableId": 1103, "query": {"select": []}})


def test_fetch_chart_queries_sends_get_request(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["cookies"] = cookies
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": [
                    {"query": {"select": []}, "dataSource": "doris", "tableId": 1}
                ],
            },
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    result = client.fetch_chart_queries("chart-123")

    assert captured["url"].endswith("/api/v1/data-metrics/cli-query/latest-request-data")
    assert captured["params"] == {"chart_uuid": "chart-123"}
    assert len(result) == 1
    assert result[0]["tableId"] == 1


def test_fetch_chart_bundle_supports_new_structured_response(monkeypatch):
    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "chart_uuid": "chart-123",
                    "request_id": "req-1",
                    "datasets": [
                        {
                            "dataset_alias": "ds_sales",
                            "tableId": 3,
                            "dataSource": "doris_analytics",
                            "filterable_fields": [{"column_name": "date_id", "verbose_name": "日期", "source_column_name": None}],
                            "fields": [
                                {
                                    "field_type": "dimension",
                                    "verbose_name": "日期",
                                    "field_name": "date_id",
                                    "origin_name": "ds_sales.date_id",
                                    "global_alias": "f_date_id",
                                    "query_aliases": [],
                                    "aggregations": [],
                                    "sources": ["where"],
                                }
                            ],
                        }
                    ],
                    "queries": [
                        {
                            "query_index": 0,
                            "dataset_alias": "ds_sales",
                            "tableId": 3,
                            "dataSource": "doris_analytics",
                            "query": {"select": []},
                            "field_refs": {
                                "select": [],
                                "conditions": [
                                    {
                                        "source": "where",
                                        "query_field": "ds_sales.date_id",
                                        "global_alias": "f_date_id",
                                    }
                                ],
                            },
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    bundle = client.fetch_chart_bundle("chart-123")

    assert bundle["chart_uuid"] == "chart-123"
    assert len(bundle["datasets"]) == 1
    assert bundle["queries"][0]["filterable_fields"][0]["column_name"] == "date_id"
    assert bundle["queries"][0]["field_mappings"][0]["verbose_name"] == "日期"


def test_fetch_chart_queries_raises_when_data_invalid(monkeypatch):
    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(200, json={"code": 200, "data": {"unexpected": "dict"}})

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    with pytest.raises(BadRemoteJsonError):
        client.fetch_chart_queries("chart-123")
