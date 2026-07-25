import json

import httpx
import pytest

from opscli.amazon_rufus.domain.exceptions import (
    RufusBadRemoteJsonError,
    RufusPlatformCookieAuthError,
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
    assert captured["timeout"] == 10
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
