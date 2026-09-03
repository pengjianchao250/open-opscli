"""AppHub 第一阶段 HTTP/SSE 客户端测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.domain.models import AppYaml
from opscli.app.transport.client import AppHubClient


class FakeAuth:
    def build_session_headers(self):
        return {"X-Session-Id": "session", "X-Opscli-Version": "0.0.1"}


def test_client_uses_shared_apphub_environment_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "opscli.app.transport.client.get_apphub_url",
        lambda: "http://10.1.13.143:8080",
    )
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"repo_url": "https://gitea.example/apps/demo.git"},
            )
        )
    )

    client = AppHubClient(auth_client=FakeAuth(), http_client=http)

    assert client.api_base_url == "http://10.1.13.143:8080/api/apphub/v1"


def test_create_app_sends_full_appyaml_without_cookie() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["request"] = request
        return httpx.Response(
            201,
            json={
                "data": {
                    "app_id": "app-1",
                    "slug": "sales-dashboard",
                    "repo_url": "https://gitea.example/apps/sales-dashboard.git",
                }
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=http,
    )
    app_yaml = AppYaml.from_site_name("sales-dashboard").to_dict()

    payload = client.create_app(app_yaml)

    request = observed["request"]
    assert request.url == "https://apphub.example/api/apphub/v1/apps"
    assert request.headers["X-Session-Id"] == "session"
    assert "cookie" not in request.headers
    body = json.loads(request.content)
    assert body["apiVersion"] == "apps.aukeys/v1"
    assert body["runtime"] == "streamlit"
    assert body["services"] == {"sqlite": False}
    assert body["opscli"] == {"auth_mode": "viewer", "datasets": []}
    assert payload["app_id"] == "app-1"


def test_publish_release_resumes_sse_from_last_sequence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "text/event-stream",
                    "X-Apphub-Release-Id": "41",
                },
                content=(
                    'event: progress\n'
                    'data: {"seq":0,"release_id":41,"level":"info","message":"received"}\n\n'
                ).encode(),
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                'event: done\n'
                'data: {"seq":1,"level":"info","message":"healthy","status":"healthy"}\n\n'
            ).encode(),
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=http,
    )

    result = client.publish_release(
        "sales-dashboard",
        commit_sha="a" * 40,
        message="优化首页",
    )

    assert result["release_id"] == 41
    assert result["last_seq"] == 1
    assert result["terminal_event"]["status"] == "healthy"
    assert requests[1].url.params["since_seq"] == "0"
    assert requests[1].url.path.endswith("/apps/sales-dashboard/releases/41/events")


def test_http_error_envelope_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": {"code": "CONFLICT", "message": "busy", "fix_hint": "rename"}},
            headers={"X-Request-Id": "req-1"},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=http,
    )

    with pytest.raises(AppHubHttpError) as caught:
        client.create_app(AppYaml.from_site_name("demo").to_dict())

    assert caught.value.code == "CONFLICT"
    assert caught.value.fix_hint == "rename"
    assert caught.value.request_id == "req-1"
