"""SerpApi Google Trends HTTP 客户端测试。"""

from pathlib import Path

import httpx
import pytest
import respx

from opscli.google_trends.api.key_store import SerpApiKeyStore
from opscli.google_trends.api.serpapi_client import SerpApiGoogleTrendsClient
from opscli.google_trends.domain.exceptions import (
    GoogleTrendsApiError,
    GoogleTrendsApiKeysExhaustedError,
)


def _store_with_keys(tmp_path: Path, *keys: str) -> SerpApiKeyStore:
    store = SerpApiKeyStore(tmp_path / "serpapi.sqlite3")
    for index, key in enumerate(keys, start=1):
        store.add_key(name=f"key-{index}", api_key=key)
    return store


@respx.mock(assert_all_called=False)
def test_client_checks_named_key_account_without_search(tmp_path: Path, respx_mock):
    """指定账号测试应只同步 Account API，不消耗搜索次数。"""
    store = _store_with_keys(tmp_path, "secret-one")
    key = store.list_keys()[0]
    account_route = respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(
            200,
            json={"total_searches_left": 10, "this_month_usage": 2},
        )
    )
    search_route = respx_mock.get(path="/search").mock(
        return_value=httpx.Response(200, json={})
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    summary = client.check_account(key.key_id)

    assert summary["total_searches_left"] == 10
    assert summary["this_month_usage"] == 2
    assert "secret-one" not in str(summary)
    assert account_route.called
    assert not search_route.called


@respx.mock(assert_all_called=False)
def test_client_account_check_marks_zero_quota_exhausted_without_restoring_positive_quota(
    tmp_path: Path,
    respx_mock,
):
    """账号测试应标记零额度，但正额度不能隐式恢复人工状态。"""
    store = _store_with_keys(tmp_path, "secret-empty", "secret-disabled")
    empty, disabled = store.list_keys()
    store.set_status(disabled.key_id, "disabled")

    def handler(request: httpx.Request) -> httpx.Response:
        remaining = 0 if request.url.params.get("api_key") == "secret-empty" else 8
        return httpx.Response(200, json={"total_searches_left": remaining})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    empty_summary = client.check_account(empty.key_id)
    disabled_summary = client.check_account(disabled.key_id)

    assert empty_summary["status"] == "exhausted"
    assert disabled_summary["status"] == "disabled"
    assert disabled_summary["total_searches_left"] == 8


@respx.mock(assert_all_called=False)
def test_client_checks_account_before_every_search(tmp_path: Path, respx_mock):
    """每次业务调用前都应读取免费 Account API。"""
    store = _store_with_keys(tmp_path, "secret-one")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.url.params.get("api_key")))
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"total_searches_left": 10, "this_month_usage": 1})
        return httpx.Response(200, json={"suggestions": [{"q": "/m/apple", "title": "Apple"}]})

    respx_mock.get(path="/account.json").mock(
        side_effect=handler
    )
    respx_mock.get(path="/search").mock(
        side_effect=handler
    )
    client = SerpApiGoogleTrendsClient(key_store=store)
    first = client.run("autocomplete", {"q": "Apple"})
    second = client.run("autocomplete", {"q": "Apple"})

    assert first["suggestions"][0]["title"] == "Apple"
    assert second["suggestions"][0]["title"] == "Apple"
    assert [path for path, _key in calls] == [
        "/account.json",
        "/search",
        "/account.json",
        "/search",
    ]


@respx.mock(assert_all_called=False)
def test_client_rotates_when_first_key_is_exhausted(tmp_path: Path, respx_mock):
    """预检确认 Key 耗尽后应标记并自动使用下一个 Key。"""
    store = _store_with_keys(tmp_path, "secret-empty", "secret-live")
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            remaining = 0 if api_key == "secret-empty" else 5
            return httpx.Response(200, json={"total_searches_left": remaining})
        search_keys.append(api_key)
        return httpx.Response(200, json={"trending_searches": [{"query": "flashlight"}]})

    respx_mock.get(path="/account.json").mock(
        side_effect=handler
    )
    respx_mock.get(path="/search").mock(
        side_effect=handler
    )
    client = SerpApiGoogleTrendsClient(key_store=store)
    payload = client.run("trending-now", {"geo": "US", "hours": "24"})

    assert payload["trending_searches"][0]["query"] == "flashlight"
    assert search_keys == ["secret-live"]
    keys = {item.name: item for item in store.list_keys()}
    assert keys["key-1"].status == "exhausted"
    assert keys["key-2"].status == "active"


@respx.mock(assert_all_called=False)
def test_client_marks_key_exhausted_after_search_error_and_retries(
    tmp_path: Path, respx_mock
):
    """搜索失败后复查到额度归零时，应切换 Key 重试当前请求。"""
    store = _store_with_keys(tmp_path, "secret-first", "secret-second")
    account_calls = {"secret-first": 0, "secret-second": 0}
    search_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            account_calls[api_key] += 1
            remaining = 1
            if api_key == "secret-first" and account_calls[api_key] > 1:
                remaining = 0
            return httpx.Response(200, json={"total_searches_left": remaining})
        search_calls.append(api_key)
        if api_key == "secret-first":
            return httpx.Response(200, json={"error": "Your searches are exhausted"})
        return httpx.Response(200, json={"interest_over_time": {"timeline_data": []}})

    respx_mock.get(path="/account.json").mock(
        side_effect=handler
    )
    respx_mock.get(path="/search").mock(
        side_effect=handler
    )
    client = SerpApiGoogleTrendsClient(key_store=store)
    client.run("trends", {"q": "flashlight", "data_type": "TIMESERIES"})

    assert search_calls == ["secret-first", "secret-second"]
    assert store.list_keys()[0].status == "exhausted"


@respx.mock(assert_all_called=False)
def test_client_fails_when_all_keys_are_exhausted(tmp_path: Path, respx_mock):
    """全部 Key 耗尽时应返回稳定的专用错误。"""
    store = _store_with_keys(tmp_path, "secret-empty")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_searches_left": 0})

    respx_mock.get(path="/account.json").mock(
        side_effect=handler
    )
    respx_mock.get(path="/search").mock(
        side_effect=handler
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    with pytest.raises(GoogleTrendsApiKeysExhaustedError):
        client.run("trends", {"q": "flashlight"})


@respx.mock(assert_all_called=False)
def test_client_does_not_exhaust_key_when_account_api_is_unavailable(
    tmp_path: Path, respx_mock
):
    """Account API 网络失败不能误判 Key 已耗尽。"""
    store = _store_with_keys(tmp_path, "secret-safe")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline secret-safe", request=request)

    respx_mock.get(path="/account.json").mock(
        side_effect=handler
    )
    respx_mock.get(path="/search").mock(
        side_effect=handler
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    with pytest.raises(GoogleTrendsApiError) as captured:
        client.run("trends", {"q": "flashlight"})

    assert "secret-safe" not in str(captured.value)
    saved_key = store.list_keys()[0]
    assert saved_key.status == "active"
    assert saved_key.last_error is not None
    assert "secret-safe" not in saved_key.last_error


@respx.mock(assert_all_called=False)
def test_client_strips_api_key_from_payload_and_errors(tmp_path: Path, respx_mock):
    """SerpApi 响应和异常都不能泄露 API Key。"""
    store = _store_with_keys(tmp_path, "secret-redact")
    search_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal search_count
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"total_searches_left": 3})
        search_count += 1
        if search_count == 1:
            return httpx.Response(
                200,
                json={"api_key": "secret-redact", "suggestions": [{"q": "secret-redact"}]},
            )
        return httpx.Response(400, json={"error": "bad key secret-redact"})

    respx_mock.get(path="/account.json").mock(
        side_effect=handler
    )
    respx_mock.get(path="/search").mock(
        side_effect=handler
    )
    client = SerpApiGoogleTrendsClient(key_store=store)
    payload = client.run("autocomplete", {"q": "Apple"})
    assert "secret-redact" not in str(payload)

    with pytest.raises(GoogleTrendsApiError) as captured:
        client.run("autocomplete", {"q": "Apple"})
    assert "secret-redact" not in str(captured.value)
