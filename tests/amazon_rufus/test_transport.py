import json

import httpx
import pytest

from opscli.amazon_rufus.domain.exceptions import (
    RufusBadRemoteJsonError,
    RufusError,
    RufusPlatformCookieAuthError,
    RufusPlatformCookieUnavailableError,
    RufusRemoteBusinessError,
    RufusRemoteHttpError,
)
from opscli.amazon_rufus.transport.client import RufusTransportClient


class DummyAuthClient:
    def build_request_auth(self, alias: str):
        assert alias == "ops"
        return (
            {"Authorization": "Bearer jwt-token"},
            {
                "polarisUserToken": "session-123",
                "opscliDeviceCode": "dc-abc",
            },
        )


def _sample_upload_payload() -> dict:
    return {
        "records": [
            {
                "asin": "B0TEST1234",
                "country": "US",
                "businessType": "asin_rufus_cli",
            }
        ]
    }


def test_submit_upload_payload_sends_auth_headers_and_cookies(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(200, json={"code": 200, "message": "ok"})

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)

    client = RufusTransportClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    result = client.submit_upload_payload(_sample_upload_payload())

    assert captured["url"] == "https://ops.example.com/api/v1/rufus/upload"
    assert captured["json"] == _sample_upload_payload()
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["timeout"] == 10
    assert result["message"] == "ok"


def test_submit_upload_payload_raises_business_error(monkeypatch):
    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(200, json={"code": 403, "msg": "无权提交"})

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusRemoteBusinessError) as exc_info:
        client.submit_upload_payload(_sample_upload_payload())

    assert exc_info.value.business_code == 403
    assert str(exc_info.value) == "无权提交"


def test_submit_upload_payload_raises_when_remote_json_invalid(monkeypatch):
    class DummyResponse:
        status_code = 200

        def json(self):
            raise json.JSONDecodeError("bad", "x", 0)

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return DummyResponse()

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusBadRemoteJsonError):
        client.submit_upload_payload(_sample_upload_payload())


def test_submit_upload_payload_401_keeps_remote_http_error(monkeypatch):
    """Rufus upload 401 仍保留通用远端 HTTP 语义。"""

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(401, json={"message": "unauthorized"})

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusRemoteHttpError) as exc_info:
        client.submit_upload_payload(_sample_upload_payload())

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "RUFUS_REMOTE_HTTP_ERROR"


def test_save_platform_cookie_sends_platform_country_and_content_only(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "code": 200,
                "msg": "保存成功",
                "data": {
                    "platform": "amazon",
                    "country": "US",
                    "content": "{\"country\":\"US\"}",
                    "cookie_content": "should-not-be-sent",
                },
            },
        )

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)

    client = RufusTransportClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    result = client.save_platform_cookie(
        platform="amazon",
        country="US",
        content="{\"country\":\"US\"}",
    )

    assert captured["url"] == "https://ops.example.com/api/v1/platform-cookies"
    assert captured["json"] == {
        "platform": "amazon",
        "country": "US",
        "content": "{\"country\":\"US\"}",
    }
    assert "cookie_content" not in captured["json"]
    assert "account_identifier" not in captured["json"]
    assert "domain" not in captured["json"]
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["timeout"] == 10
    assert result["msg"] == "保存成功"


def test_save_platform_cookie_401_maps_to_platform_cookie_auth_error(monkeypatch):
    """平台 Cookie 保存 401 必须暴露 OPS 平台接口鉴权错误。"""

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(401, json={"message": "token expired"})

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusPlatformCookieAuthError) as exc_info:
        client.save_platform_cookie(platform="amazon", country="US", content="{}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.to_dict() == {
        "code": "RUFUS_PLATFORM_COOKIE_AUTH_ERROR",
        "message": "OPS 平台 Cookie 接口未授权，请先刷新 OPS/MCP 认证；这不是亚马逊 Rufus 登录态缺失。",
        "status_code": 401,
    }


def test_get_platform_cookie_sends_platform_query(monkeypatch):
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
                "msg": "操作成功",
                "data": {
                    "platform": "amazon",
                    "country": "US",
                    "content": "{\"country\":\"US\"}",
                },
            },
        )

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.get", fake_get)

    client = RufusTransportClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    result = client.get_platform_cookie(platform="amazon")

    assert captured["url"] == "https://ops.example.com/api/v1/platform-cookies"
    assert captured["params"] == {"platform": "amazon"}
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    # 读约 4KB 的登录态只需秒级；网关 30~60 秒就会切断，客户端等 180 秒没有意义（Bug 12133）
    assert captured["timeout"] == 60
    assert result["data"]["content"] == "{\"country\":\"US\"}"


def test_get_platform_cookie_401_maps_to_platform_cookie_auth_error(monkeypatch):
    """平台 Cookie 读取 401 必须阻止后续 Amazon 登录恢复。"""

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(401, json={"message": "unauthorized"})

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.get", fake_get)
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusPlatformCookieAuthError) as exc_info:
        client.get_platform_cookie(platform="amazon")

    payload = exc_info.value.to_dict()
    assert payload["code"] == "RUFUS_PLATFORM_COOKIE_AUTH_ERROR"
    assert payload["status_code"] == 401
    assert "unauthorized" not in payload["message"].lower()


# ---------------------------------------------------------------------------
# Bug 12133：读平台 Cookie（登录态）遇网关瞬时错误自动重试，耗尽后抛可重试错误码
# 样本与 tests/shared/test_http_non_json.py 同源（离线复现的 8 种响应形态）；
# 本目录没有 __init__.py，直接 `pytest` 调用时无法跨测试模块导入，故在此保留一份。
# ---------------------------------------------------------------------------

NGINX_504 = (
    "<html>\r\n<head><title>504 Gateway Time-out</title></head>\r\n<body>\r\n"
    "<center><h1>504 Gateway Time-out</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"
)
NGINX_502 = NGINX_504.replace("504 Gateway Time-out", "502 Bad Gateway")
PHP_FATAL_TEXT = "PHP Fatal error:  Maximum execution time of 30 seconds exceeded in /data/www/x.php on line 120"
# 平台 Cookie 接口 content 是浏览器 cURL 原文，里面就是 Amazon 会话 Cookie
FAKE_CURL = (
    "curl 'https://www.amazon.com/rufus/cl/streaming?tabId=t1' "
    "-H 'cookie: session-id=1; ubid-main=2; at-main=3' --data-raw '{}'"
)
OK_JSON = {"code": 200, "msg": "ok", "data": {"platform": "amazon", "country": "US", "content": FAKE_CURL}}
# 任何错误输出中都不允许出现的敏感/正文片段
SECRET_FRAGMENTS = ("session-id", "ubid-main", "at-main", "curl", "rufus/cl/streaming", "platform=amazon", "Warning")


def make_response(status: int, *, text: str | None = None, js: dict | None = None, ctype: str = "text/html") -> httpx.Response:
    """构造绑定了平台 Cookie 请求的 httpx.Response。"""
    request = httpx.Request("GET", "https://ops.example.com/api/v1/platform-cookies?platform=amazon")
    if js is not None:
        return httpx.Response(status, json=js, request=request)
    return httpx.Response(status, content=(text or "").encode("utf-8"), headers={"content-type": ctype}, request=request)


def remote_samples() -> list[tuple[str, httpx.Response]]:
    """离线复现的 8 种远端响应形态。"""
    warning_body = "<br />\n<b>Warning</b>: x in y\n" + json.dumps(OK_JSON)
    return [
        ("200_json", make_response(200, js=OK_JSON)),
        ("504_nginx_html", make_response(504, text=NGINX_504)),
        ("502_nginx_html", make_response(502, text=NGINX_502)),
        ("500_php_text", make_response(500, text=PHP_FATAL_TEXT, ctype="text/plain")),
        ("200_empty", make_response(200, text="", ctype="application/json")),
        ("200_warning_prefix", make_response(200, text=warning_body, ctype="application/json")),
        ("503_json", make_response(503, js={"code": 503, "message": "服务繁忙"})),
        ("401_json", make_response(401, js={"code": 401, "message": "未授权访问"})),
    ]


def _patch_platform_cookie_get(monkeypatch, responses):
    """按顺序返回预设响应/异常的 httpx.get 桩，并屏蔽重试退避的真实等待。"""
    calls = {"get": 0, "sleeps": []}
    queue = list(responses)

    def fake_get(url, params=None, headers=None, cookies=None, timeout=None):
        calls["get"] += 1
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.get", fake_get)
    monkeypatch.setattr("opscli.amazon_rufus.transport.client.time.sleep", calls["sleeps"].append)
    return calls


# 期望：(错误码或 None=成功, HTTP 请求次数, status_code)
_PLATFORM_COOKIE_EXPECTED = {
    "200_json": (None, 1, None),
    "504_nginx_html": ("RUFUS_PLATFORM_COOKIE_UNAVAILABLE", 3, 504),
    "502_nginx_html": ("RUFUS_PLATFORM_COOKIE_UNAVAILABLE", 3, 502),
    "500_php_text": ("RUFUS_PLATFORM_COOKIE_UNAVAILABLE", 3, 500),
    "200_empty": ("RUFUS_BAD_REMOTE_JSON", 1, None),
    "200_warning_prefix": ("RUFUS_BAD_REMOTE_JSON", 1, None),
    "503_json": ("RUFUS_PLATFORM_COOKIE_UNAVAILABLE", 3, 503),
    "401_json": ("RUFUS_PLATFORM_COOKIE_AUTH_ERROR", 1, 401),
}


@pytest.mark.parametrize("name,response", remote_samples(), ids=[name for name, _ in remote_samples()])
def test_get_platform_cookie_classifies_remote_samples(monkeypatch, name, response):
    """8 种远端响应形态：网关类瞬时错误重试后抛可重试错误码，其余保持原语义，且不泄露 Cookie。"""
    expected_code, expected_calls, expected_status = _PLATFORM_COOKIE_EXPECTED[name]
    calls = _patch_platform_cookie_get(monkeypatch, [response])
    client = RufusTransportClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    if expected_code is None:
        assert client.get_platform_cookie(platform="amazon")["data"]["country"] == "US"
        assert calls["get"] == expected_calls
        return

    with pytest.raises(RufusError) as exc_info:
        client.get_platform_cookie(platform="amazon")

    payload = exc_info.value.to_dict()
    assert payload["code"] == expected_code
    assert calls["get"] == expected_calls
    if expected_status is not None:
        assert payload["status_code"] == expected_status
    if expected_code == "RUFUS_PLATFORM_COOKIE_UNAVAILABLE":
        assert payload["retryable"] is True
        assert payload["attempts"] == 3
        assert calls["sleeps"] == [2, 5]
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in SECRET_FRAGMENTS:
        assert secret not in serialized, (name, secret, serialized)


def test_get_platform_cookie_retries_504_then_succeeds(monkeypatch):
    """先 504 网关超时、后 200 正常：自动重试一次后成功，不向上抛错。"""
    calls = _patch_platform_cookie_get(
        monkeypatch,
        [make_response(504, text=NGINX_504), make_response(200, js=OK_JSON)],
    )
    client = RufusTransportClient(auth_client=DummyAuthClient())

    result = client.get_platform_cookie(platform="amazon")

    assert result["data"]["country"] == "US"
    assert calls["get"] == 2
    assert calls["sleeps"] == [2]


def test_get_platform_cookie_consecutive_504_raises_retryable_unavailable(monkeypatch):
    """连续 3 次 504：抛 RUFUS_PLATFORM_COOKIE_UNAVAILABLE，标明可重试且不是 Amazon 的问题。"""
    calls = _patch_platform_cookie_get(monkeypatch, [make_response(504, text=NGINX_504)])
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusPlatformCookieUnavailableError) as exc_info:
        client.get_platform_cookie(platform="amazon")

    payload = exc_info.value.to_dict()
    assert calls["get"] == 3
    assert payload["code"] == "RUFUS_PLATFORM_COOKIE_UNAVAILABLE"
    assert payload["retryable"] is True
    assert payload["status_code"] == 504
    assert payload["attempts"] == 3
    assert "OPS 后端读取亚马逊登录态临时不可用" in payload["message"]
    assert "不是 Amazon 的问题" in payload["message"]
    assert "可稍后重试" in payload["message"]
    # 诊断信息保留在 message 中，反馈与埋点只记录 code+message 也能定位网关超时
    assert "504 Gateway Time-out" in payload["message"]


@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.ReadTimeout("read timeout"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.ConnectError("[Errno 61] Connection refused"),
        httpx.ReadError("connection reset by peer"),
        httpx.WriteError("broken pipe"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ],
)
def test_get_platform_cookie_retries_transient_network_errors(monkeypatch, transport_error):
    """瞬时网络故障：重试耗尽后抛可重试错误码，文案说明是接口无法访问而非后端 5xx，不带 HTTP 状态码。"""
    calls = _patch_platform_cookie_get(monkeypatch, [transport_error])
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusPlatformCookieUnavailableError) as exc_info:
        client.get_platform_cookie(platform="amazon")

    payload = exc_info.value.to_dict()
    assert calls["get"] == 3
    assert payload["retryable"] is True
    assert "status_code" not in payload
    assert "OPS 登录态接口无法访问（可能是 OPS 后端、网关或本机网络/代理问题）" in payload["message"]
    assert "OPS 后端读取亚马逊登录态临时不可用" not in payload["message"]
    assert type(transport_error).__name__ in payload["message"]
    # 保留原始异常文本，便于区分拒绝连接、断连、超时等不同根因
    assert str(transport_error) in payload["message"]


@pytest.mark.parametrize(
    "config_error",
    [httpx.UnsupportedProtocol("Request URL is missing an 'http://' or 'https://' protocol."), httpx.InvalidURL("Invalid port")],
)
def test_get_platform_cookie_does_not_retry_config_errors(monkeypatch, config_error):
    """URL/协议这类配置错误重试无益：只请求一次，原异常直接抛出。"""
    calls = _patch_platform_cookie_get(monkeypatch, [config_error])
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(type(config_error)):
        client.get_platform_cookie(platform="amazon")

    assert calls["get"] == 1
    assert calls["sleeps"] == []


def test_get_platform_cookie_keeps_ssl_error_text_without_url(monkeypatch):
    """SSL 证书校验失败的原文必须保留（审查探针曾发现被抹成类型名），URL 与 query 必须去掉并截断。"""
    ssl_error = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate "
        "(_ssl.c:1006) while connecting to https://ops.example.com/api/v1/platform-cookies?platform=amazon&token=abc "
        + "x" * 300
    )
    _patch_platform_cookie_get(monkeypatch, [ssl_error])
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusPlatformCookieUnavailableError) as exc_info:
        client.get_platform_cookie(platform="amazon")

    message = exc_info.value.to_dict()["message"]
    assert "CERTIFICATE_VERIFY_FAILED" in message
    for leaked in ("https://", "ops.example.com", "platform=amazon", "token=abc"):
        assert leaked not in message
    # 原始异常文本截断到约 120 字，避免超长异常把终端与反馈刷屏
    assert "x" * 130 not in message


def test_get_platform_cookie_does_not_retry_application_500_json(monkeypatch):
    """应用层返回的 500 JSON 不是网关瞬时错误：不重试，保持 RUFUS_REMOTE_HTTP_ERROR。"""
    calls = _patch_platform_cookie_get(monkeypatch, [make_response(500, js={"code": 500, "message": "内部错误"})])
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusRemoteHttpError) as exc_info:
        client.get_platform_cookie(platform="amazon")

    assert calls["get"] == 1
    assert exc_info.value.to_dict()["code"] == "RUFUS_REMOTE_HTTP_ERROR"


def test_save_platform_cookie_does_not_retry_gateway_error(monkeypatch):
    """自动重试只覆盖读登录态；保存（覆盖写）遇 504 仍一次失败并保留 HTTP 状态码。"""
    calls = {"post": 0}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        calls["post"] += 1
        return make_response(504, text=NGINX_504)

    monkeypatch.setattr("opscli.amazon_rufus.transport.client.httpx.post", fake_post)
    client = RufusTransportClient(auth_client=DummyAuthClient())

    with pytest.raises(RufusRemoteHttpError) as exc_info:
        client.save_platform_cookie(platform="amazon", country="US", content="{}")

    assert calls["post"] == 1
    assert exc_info.value.status_code == 504


def test_cli_get_backend_reports_platform_cookie_unavailable(monkeypatch):
    """CLI 端到端：get-backend 读登录态持续 504 时输出可重试错误码，而不是 RUFUS_BAD_REMOTE_JSON。"""
    from typer.testing import CliRunner

    from opscli.amazon_rufus.commands.cli import app
    from opscli.amazon_rufus.services.manager import RufusManager

    calls = _patch_platform_cookie_get(monkeypatch, [make_response(504, text=NGINX_504)])
    transport = RufusTransportClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    class TestManager(RufusManager):
        def __init__(self):
            super().__init__(transport_client=transport)

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", TestManager)

    result = CliRunner().invoke(app, ["get-backend", "B0GVNKNFND", "US", "-q", "这个商品适合送礼吗？"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "RUFUS_PLATFORM_COOKIE_UNAVAILABLE"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["status_code"] == 504
    assert "不是 Amazon 的问题" in payload["error"]["message"]
    assert calls["get"] == 3
