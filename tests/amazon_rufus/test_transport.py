import json

import httpx
import pytest

from opscli.amazon_rufus.domain.exceptions import (
    RufusBadRemoteJsonError,
    RufusRemoteBusinessError,
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
