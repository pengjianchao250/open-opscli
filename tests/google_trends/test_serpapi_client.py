"""SerpApi Google Trends HTTP 客户端测试。"""

import sqlite3
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


def _set_exhausted_renewal(
    store: SerpApiKeyStore,
    key_id: str,
    *,
    renewal_date: str | None,
    last_checked_at: str | None = None,
) -> None:
    """为续期恢复测试写入耗尽账号的时间状态。"""
    store.mark_exhausted(key_id, reason="额度耗尽")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            """
            UPDATE google_trends_serpapi_keys
            SET plan_renewal_date = ?, last_checked_at = ?
            WHERE key_id = ?
            """,
            (renewal_date, last_checked_at, key_id),
        )


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


@respx.mock(assert_all_called=False)
def test_client_accepts_successful_empty_result_with_error_message(tmp_path: Path, respx_mock):
    """SerpApi 成功空结果带 error 时不应误判为请求失败。"""
    store = _store_with_keys(tmp_path, "secret-empty-result")
    respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(200, json={"total_searches_left": 5})
    )
    respx_mock.get(path="/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "search_information": {"organic_results_state": "Fully empty"},
                "error": "Google hasn't returned any results for this query.",
            },
        )
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    payload = client.run("trends", {"q": "missing-query"})

    assert payload["search_metadata"]["status"] == "Success"
    assert "hasn't returned any results" in payload["error"]


@respx.mock(assert_all_called=False)
def test_client_rotates_when_account_check_rejects_key(tmp_path: Path, respx_mock):
    """Account API 预检拒绝 Key 时应禁用当前账号并继续故障转移。"""
    store = _store_with_keys(tmp_path, "secret-invalid", "secret-live")
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            if api_key == "secret-invalid":
                return httpx.Response(401, json={"error": "No valid API key provided."})
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        return httpx.Response(200, json={"suggestions": [{"title": "Apple"}]})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    client.run("autocomplete", {"q": "Apple"})

    assert search_keys == ["secret-live"]
    assert store.list_keys()[0].status == "disabled"


@pytest.mark.parametrize("status_code", [401, 403])
@respx.mock(assert_all_called=False)
def test_client_disables_invalid_account_and_rotates(
    tmp_path: Path,
    respx_mock,
    status_code: int,
):
    """无效 Key 或无权限账号应禁用，并切换到下一个账号。"""
    store = _store_with_keys(tmp_path, "secret-invalid", "secret-live")
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        if api_key == "secret-invalid":
            return httpx.Response(status_code, json={"error": f"invalid secret-invalid ({status_code})"})
        return httpx.Response(200, json={"suggestions": [{"title": "Apple"}]})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    payload = client.run("autocomplete", {"q": "Apple"})

    assert payload["suggestions"][0]["title"] == "Apple"
    assert search_keys == ["secret-invalid", "secret-live"]
    invalid = store.list_keys()[0]
    assert invalid.status == "disabled"
    assert "secret-invalid" not in str(invalid.to_public_dict())


@respx.mock(assert_all_called=False)
def test_client_marks_429_quota_exhausted_and_rotates(tmp_path: Path, respx_mock):
    """429 后复查额度为零时应标记耗尽并切换账号。"""
    store = _store_with_keys(tmp_path, "secret-empty", "secret-live")
    account_calls = {"secret-empty": 0, "secret-live": 0}
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            account_calls[api_key] += 1
            remaining = 0 if api_key == "secret-empty" and account_calls[api_key] > 1 else 5
            return httpx.Response(200, json={"total_searches_left": remaining})
        search_keys.append(api_key)
        if api_key == "secret-empty":
            return httpx.Response(429, json={"error": "Too many requests"})
        return httpx.Response(200, json={"interest_over_time": {"timeline_data": []}})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    client.run("trends", {"q": "flashlight"})

    assert search_keys == ["secret-empty", "secret-live"]
    assert store.list_keys()[0].status == "exhausted"


@respx.mock(assert_all_called=False)
def test_client_rotates_429_throughput_limit_without_disabling_key(tmp_path: Path, respx_mock):
    """429 且仍有额度时只跳过本轮，不应永久停用账号。"""
    store = _store_with_keys(tmp_path, "secret-limited", "secret-live")
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        if api_key == "secret-limited":
            return httpx.Response(429, json={"error": "Hourly throughput limit reached"})
        return httpx.Response(200, json={"trending_searches": []})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    client.run("trending-now", {"geo": "US"})

    limited = store.list_keys()[0]
    assert search_keys == ["secret-limited", "secret-live"]
    assert limited.status == "active"
    assert limited.last_error == "Hourly throughput limit reached"


@pytest.mark.parametrize("status_code", [400, 404, 410, 500, 503])
@respx.mock(assert_all_called=False)
def test_client_does_not_rotate_for_non_account_errors(
    tmp_path: Path,
    respx_mock,
    status_code: int,
):
    """参数、资源和服务端错误不能通过切换账号解决。"""
    store = _store_with_keys(tmp_path, "secret-first", "secret-second")
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        return httpx.Response(status_code, json={"error": f"request failed ({status_code})"})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    with pytest.raises(GoogleTrendsApiError) as captured:
        client.run("trends", {"q": "flashlight"})

    assert captured.value.status_code == status_code
    assert search_keys == ["secret-first"]
    assert all(key.status == "active" for key in store.list_keys())


@respx.mock(assert_all_called=False)
def test_client_rejects_search_metadata_error(tmp_path: Path, respx_mock):
    """HTTP 200 但搜索状态为 Error 时仍应返回 API 错误。"""
    store = _store_with_keys(tmp_path, "secret-error")
    respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(200, json={"total_searches_left": 5})
    )
    respx_mock.get(path="/search").mock(
        return_value=httpx.Response(
            200,
            json={"search_metadata": {"status": "Error"}, "error": "Proxy timeout"},
        )
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    with pytest.raises(GoogleTrendsApiError, match="Proxy timeout"):
        client.run("trends", {"q": "flashlight"})

    assert store.list_keys()[0].status == "active"


@respx.mock(assert_all_called=False)
def test_client_restores_exhausted_key_after_plan_renewal(tmp_path: Path, respx_mock):
    """续期日已到且额度恢复时，应自动启用账号并完成当前搜索。"""
    store = _store_with_keys(tmp_path, "secret-renewed")
    key = store.list_keys()[0]
    _set_exhausted_renewal(store, key.key_id, renewal_date="2000-01-01")
    account_route = respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(
            200,
            json={"total_searches_left": 100, "plan_renewal_date": "2099-01-01"},
        )
    )
    respx_mock.get(path="/search").mock(
        return_value=httpx.Response(200, json={"suggestions": [{"title": "Apple"}]})
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    payload = client.run("autocomplete", {"q": "Apple"})

    restored = store.get(key.key_id)
    assert payload["suggestions"][0]["title"] == "Apple"
    assert account_route.call_count == 1
    assert restored is not None
    assert restored.status == "active"
    assert restored.exhausted_at is None
    assert restored.last_error is None


@respx.mock(assert_all_called=False)
def test_client_does_not_recheck_exhausted_key_before_renewal(tmp_path: Path, respx_mock):
    """续期日未到的耗尽账号不应提前调用 Account API。"""
    store = _store_with_keys(tmp_path, "secret-future")
    key = store.list_keys()[0]
    _set_exhausted_renewal(store, key.key_id, renewal_date="2999-01-01")
    account_route = respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(200, json={"total_searches_left": 100})
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    with pytest.raises(GoogleTrendsApiKeysExhaustedError):
        client.run("trends", {"q": "flashlight"})

    assert not account_route.called


@respx.mock(assert_all_called=False)
def test_client_cools_down_when_renewed_key_still_has_no_quota(tmp_path: Path, respx_mock):
    """续期复查仍无额度时，一小时内不应重复检查。"""
    store = _store_with_keys(tmp_path, "secret-still-empty")
    key = store.list_keys()[0]
    _set_exhausted_renewal(store, key.key_id, renewal_date="2000-01-01")
    account_route = respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(
            200,
            json={"total_searches_left": 0, "plan_renewal_date": "2999-01-01"},
        )
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    with pytest.raises(GoogleTrendsApiKeysExhaustedError):
        client.run("trends", {"q": "flashlight"})
    with pytest.raises(GoogleTrendsApiKeysExhaustedError):
        client.run("trends", {"q": "flashlight"})

    saved = store.get(key.key_id)
    assert account_route.call_count == 1
    assert saved.status == "exhausted"
    assert saved.plan_renewal_date == "2000-01-01"


@pytest.mark.parametrize("status_code", [401, 403, 503])
@respx.mock(assert_all_called=False)
def test_client_renewal_check_error_falls_back_to_active_key(
    tmp_path: Path,
    respx_mock,
    status_code: int,
):
    """耗尽账号复查失败时不应阻断其他 active 账号。"""
    store = _store_with_keys(tmp_path, "secret-renewal-error", "secret-live")
    exhausted, live = store.list_keys()
    _set_exhausted_renewal(store, exhausted.key_id, renewal_date="2000-01-01")
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            if api_key == "secret-renewal-error":
                return httpx.Response(status_code, json={"error": f"account error {status_code}"})
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        return httpx.Response(200, json={"trending_searches": []})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    client.run("trending-now", {"geo": "US"})

    failed = store.get(exhausted.key_id)
    assert search_keys == [live.api_key]
    assert failed is not None
    assert failed.status == ("disabled" if status_code in {401, 403} else "exhausted")
    assert failed.last_error == f"account error {status_code}"


@respx.mock(assert_all_called=False)
def test_client_renewal_network_error_uses_active_key_and_enters_cooldown(
    tmp_path: Path,
    respx_mock,
):
    """续期复查网络失败时应使用其他账号，且本轮只检查一次。"""
    store = _store_with_keys(tmp_path, "secret-offline", "secret-live")
    exhausted, live = store.list_keys()
    _set_exhausted_renewal(store, exhausted.key_id, renewal_date="2000-01-01")
    offline_calls = 0
    search_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal offline_calls
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            if api_key == "secret-offline":
                offline_calls += 1
                raise httpx.ConnectError("offline secret-offline", request=request)
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        return httpx.Response(200, json={"trending_searches": []})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    client.run("trending-now", {"geo": "US"})

    failed = store.get(exhausted.key_id)
    assert offline_calls == 1
    assert search_keys == [live.api_key]
    assert failed is not None
    assert failed.status == "exhausted"
    assert "secret-offline" not in str(failed.to_public_dict())
