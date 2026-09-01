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


def test_config_and_member_endpoints_use_contract_paths() -> None:
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.path))
        if request.url.path.endswith("/env") and request.method == "GET":
            return httpx.Response(200, json={"env": {}, "platform_env": {}})
        return httpx.Response(200, json={"ok": True})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(base_url="https://apphub.example", auth_client=FakeAuth(), http_client=http)
    client.get_env("demo-app")
    client.put_env("demo-app", {"MODE": "prod"})
    client.add_member("demo-app", "user@example.com")
    client.remove_member("demo-app", "user@example.com")

    assert observed == [
        ("GET", "/api/apps/demo-app/env"),
        ("PUT", "/api/apps/demo-app/env"),
        ("POST", "/api/apps/demo-app/members"),
        ("DELETE", "/api/apps/demo-app/members/user@example.com"),
    ]
