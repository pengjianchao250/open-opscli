import json

import httpx
import pytest

from opscli.amazon.client import AmazonOpsClient
from opscli.amazon.exceptions import BadRemoteJsonError, RemoteBusinessError, SubmissionConfigError
from opscli.amazon.models import AmazonProductSnapshot


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


def _sample_snapshot() -> AmazonProductSnapshot:
    return AmazonProductSnapshot(
        asin="B0TEST1234",
        zip_code="10001",
        marketplace="amazon.com",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        page_title="Sample",
        product_name="Sample Product",
        price_text="$19.99",
        price_amount=19.99,
        currency="USD",
        rating_text="4.6 out of 5 stars",
        rating_value=4.6,
        review_count_text="1,234 ratings",
        review_count_value=1234,
        location="New York 10001",
        collected_at="2026-04-23 10:00:00",
        valid=True,
        raw={"foo": "bar"},
    )


def test_submit_snapshot_sends_auth_headers_and_cookies(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(200, json={"code": 200, "message": "ok"})

    monkeypatch.setattr("opscli.amazon.transport.client.httpx.post", fake_post)
    monkeypatch.setattr("opscli.amazon.transport.client.get_amazon_submit_endpoint", lambda: "/v1/amazon/collect")

    client = AmazonOpsClient(auth_client=DummyAuthClient())
    result = client.submit_snapshot(_sample_snapshot())

    assert captured["url"].endswith("/v1/amazon/collect")
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert captured["timeout"] == 10
    assert captured["json"]["source"] == "opscli.amazon"
    assert result["message"] == "ok"


def test_submit_snapshot_requires_endpoint(monkeypatch):
    monkeypatch.setattr("opscli.amazon.transport.client.get_amazon_submit_endpoint", lambda: "")
    client = AmazonOpsClient(auth_client=DummyAuthClient())

    with pytest.raises(SubmissionConfigError):
        client.submit_snapshot(_sample_snapshot())


def test_submit_snapshot_raises_business_error(monkeypatch):
    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return httpx.Response(200, json={"code": 403, "msg": "无权提交"})

    monkeypatch.setattr("opscli.amazon.transport.client.httpx.post", fake_post)
    monkeypatch.setattr("opscli.amazon.transport.client.get_amazon_submit_endpoint", lambda: "/v1/amazon/collect")

    client = AmazonOpsClient(auth_client=DummyAuthClient())

    with pytest.raises(RemoteBusinessError) as exc_info:
        client.submit_snapshot(_sample_snapshot())

    assert exc_info.value.business_code == 403
    assert str(exc_info.value) == "无权提交"


def test_submit_snapshot_raises_when_remote_json_invalid(monkeypatch):
    class DummyResponse:
        status_code = 200

        def json(self):
            raise json.JSONDecodeError("bad", "x", 0)

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        return DummyResponse()

    monkeypatch.setattr("opscli.amazon.transport.client.httpx.post", fake_post)
    monkeypatch.setattr("opscli.amazon.transport.client.get_amazon_submit_endpoint", lambda: "/v1/amazon/collect")

    client = AmazonOpsClient(auth_client=DummyAuthClient())

    with pytest.raises(BadRemoteJsonError):
        client.submit_snapshot(_sample_snapshot())
