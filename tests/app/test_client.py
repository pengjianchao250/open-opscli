"""AppHub 应用与 Git HTTP 客户端测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.domain.models import AppCreateRequest
from opscli.app.transport.client import AppHubClient


class FakeAuth:
    def build_session_headers(self):
        return {"X-Session-Id": "session", "X-Opscli-Version": "0.0.1"}


def test_client_uses_current_apphub_api_prefix(monkeypatch) -> None:
    monkeypatch.setattr(
        "opscli.app.transport.client.get_apphub_url",
        lambda: "https://apphub.qa.aukeyit.com",
    )
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"apps": []})
        )
    )

    client = AppHubClient(auth_client=FakeAuth(), http_client=http)

    assert client.api_base_url == "https://apphub.qa.aukeyit.com/api/v1"


def test_create_app_sends_current_contract_without_cookie() -> None:
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

    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    payload = client.create_app(
        AppCreateRequest.from_app_name("销售看板", slug="sales-dashboard").to_dict()
    )

    request = observed["request"]
    assert request.url == "https://apphub.example/api/v1/apps"
    assert request.headers["X-Session-Id"] == "session"
    assert "cookie" not in request.headers
    body = json.loads(request.content)
    assert body["apiVersion"] == "apps.aukeys/v1"
    assert body["database"] == {"path": None}
    assert body["opscli"] == {"auth_mode": "viewer", "datasets": []}
    assert "runtime" not in body
    assert "python" not in body
    assert "entrypoint" not in body
    assert "services" not in body
    assert payload["app_id"] == "app-1"


def test_list_accessible_apps_uses_current_path() -> None:
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"apps": []})

    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_accessible_apps() == {"apps": []}
    assert observed[0].url.path == "/api/v1/accessible-apps"


def test_client_does_not_expose_release_apis() -> None:
    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ),
    )

    assert not hasattr(client, "list_releases")
    assert not hasattr(client, "publish_release")


def test_http_error_envelope_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "detail": {
                    "code": "CONFLICT",
                    "message": "busy",
                    "fix_hint": "rename",
                }
            },
            headers={"X-Request-Id": "req-1"},
        )

    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AppHubHttpError) as caught:
        client.create_app(AppCreateRequest.from_app_name("demo").to_dict())

    assert caught.value.code == "CONFLICT"
    assert caught.value.fix_hint == "rename"
    assert caught.value.request_id == "req-1"
