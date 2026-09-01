"""AppHub 创建站点占位客户端测试。"""

from __future__ import annotations

import httpx
import pytest

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.transport.client import AppHubClient


class FakeAuth:
    def build_session_headers(self):
        return {"X-Session-Id": "session", "X-Opscli-Version": "0.0.1"}


def test_create_site_sends_minimal_payload_without_cookie() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["request"] = request
        return httpx.Response(
            201,
            json={
                "data": {
                    "site_id": "site-1",
                    "name": "销售看板",
                    "slug": "sales-dashboard",
                    "repo_url": "https://gitlab.example/sites/sales-dashboard.git",
                }
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(
        create_site_url="https://apphub.example/api/sites",
        auth_client=FakeAuth(),
        http_client=http,
    )

    payload = client.create_site("销售看板")

    request = observed["request"]
    assert request.url == "https://apphub.example/api/sites"
    assert request.headers["X-Session-Id"] == "session"
    assert "cookie" not in request.headers
    assert request.content == b'{"name":"\xe9\x94\x80\xe5\x94\xae\xe7\x9c\x8b\xe6\x9d\xbf"}'
    assert payload["site_id"] == "site-1"


def test_http_error_envelope_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": {"code": "CONFLICT", "message": "busy", "fix_hint": "rename"}},
            headers={"X-Request-Id": "req-1"},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(
        create_site_url="https://apphub.example/api/sites",
        auth_client=FakeAuth(),
        http_client=http,
    )

    with pytest.raises(AppHubHttpError) as caught:
        client.create_site("demo")

    assert caught.value.code == "CONFLICT"
    assert caught.value.fix_hint == "rename"
    assert caught.value.request_id == "req-1"
