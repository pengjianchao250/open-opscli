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


def test_fetch_dataset_catalog_sends_get_request(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {"version": "v1.0.0", "intent_count": 1, "intents": [{"intent_code": "sales"}]},
            },
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    result = client.fetch_dataset_catalog()

    assert captured["url"].endswith("/v1/data-metrics/datasets/skill/catalog")
    assert captured["params"] is None
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["timeout"] == 20
    assert result["intent_count"] == 1


def test_fetch_dataset_catalog_raises_business_error(monkeypatch):
    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(200, json={"code": 403, "msg": "无 catalog 访问权限"})

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    with pytest.raises(RemoteBusinessError):
        client.fetch_dataset_catalog()


def test_fetch_query_metadata_sends_get_request(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "datasets": [{"table_id": 1103, "dataset_alias": "ds_sales"}],
                    "fields": [{"table_id": 1103, "field_name": "date_id"}],
                },
            },
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    result = client.fetch_query_metadata()

    assert captured["url"].endswith("/v1/data-metrics/datasets/query-metadata")
    assert captured["params"] is None  # 裸调用时不带 query params，与原行为兼容
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["timeout"] == 20
    assert result["datasets"][0]["dataset_alias"] == "ds_sales"
    assert len(result["fields"]) == 1


def test_fetch_query_metadata_with_dataset_alias_param(monkeypatch):
    """指定 dataset_alias 时应作为 query params 传给后端。"""
    captured = {}

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "datasets": [{"table_id": 1103, "dataset_alias": "ds_sales"}],
                    "fields": [{"table_id": 1103, "field_name": "date_id"}],
                },
            },
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    client.fetch_query_metadata(dataset_alias="ds_sales")

    assert captured["params"] == {"dataset_alias": "ds_sales"}


def test_fetch_query_metadata_with_table_id_param(monkeypatch):
    """指定 table_id 时应作为 query params 传给后端，整数被转为字符串。"""
    captured = {}

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        captured["params"] = params
        return httpx.Response(
            200,
            json={"code": 200, "data": {"datasets": [], "fields": []}},
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    client.fetch_query_metadata(table_id=1103)

    assert captured["params"] == {"table_id": "1103"}


def test_fetch_query_metadata_with_both_params(monkeypatch):
    """同时传入 dataset_alias 和 table_id 时两者都应进入 query params。"""
    captured = {}

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        captured["params"] = params
        return httpx.Response(
            200,
            json={"code": 200, "data": {"datasets": [], "fields": []}},
        )

    monkeypatch.setattr("opscli.query.transport.client.httpx.get", fake_get)
    client = QueryClient(auth_client=DummyAuthClient())

    client.fetch_query_metadata(dataset_alias="ds_sales", table_id=1103)

    assert captured["params"] == {"dataset_alias": "ds_sales", "table_id": "1103"}


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


def test_cli_query_forwards_mcp_api_key_when_context_present(monkeypatch):
    """MCP 上下文存在时，请求头应透传 X-MCP-API-Key。"""
    from opscli.mcp.context import mcp_request_ctx

    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["headers"] = headers
        return httpx.Response(200, json={"rows": [], "meta": {"rowCount": 0}})

    monkeypatch.setattr("opscli.query.transport.client.httpx.post", fake_post)
    client = QueryClient(auth_client=DummyAuthClient())

    token = mcp_request_ctx.set({"api_key": "mcp_key_123"})
    try:
        client.cli_query({"tableId": 1, "query": {"select": []}})
        assert captured["headers"]["X-MCP-API-Key"] == "mcp_key_123"
        assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    finally:
        mcp_request_ctx.reset(token)


def test_cli_query_no_mcp_header_when_context_absent(monkeypatch):
    """无 MCP 上下文时，不应附加 X-MCP-API-Key。"""
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["headers"] = headers
        return httpx.Response(200, json={"rows": [], "meta": {"rowCount": 0}})

    monkeypatch.setattr("opscli.query.transport.client.httpx.post", fake_post)
    client = QueryClient(auth_client=DummyAuthClient())

    client.cli_query({"tableId": 1, "query": {"select": []}})
    assert "X-MCP-API-Key" not in captured["headers"]
