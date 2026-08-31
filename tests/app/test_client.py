"""AppHub HTTP 客户端认证与错误映射测试。"""

from __future__ import annotations

import httpx
import pytest

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.transport.client import AppHubClient


class FakeAuth:
    def build_session_headers(self):
        return {"X-Session-Id": "session", "X-Opscli-Version": "0.0.1"}


def test_client_sends_headers_without_cookie() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["headers"] = request.headers
        return httpx.Response(
            200,
            json={"repo_url": "https://git.example/apps/demo-app.git", "bound": False, "username": None},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(base_url="https://apphub.example", auth_client=FakeAuth(), http_client=http)

    client.get_git_config("demo-app")

    assert observed["headers"]["X-Session-Id"] == "session"
    assert "cookie" not in observed["headers"]


def test_http_error_envelope_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": {"code": "CONFLICT", "message": "busy", "fix_hint": "retry"}},
            headers={"X-Request-Id": "req-1"},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(base_url="https://apphub.example", auth_client=FakeAuth(), http_client=http)

    with pytest.raises(AppHubHttpError) as caught:
        client.list_releases("demo-app")

    assert caught.value.code == "CONFLICT"
    assert caught.value.fix_hint == "retry"
    assert caught.value.request_id == "req-1"

