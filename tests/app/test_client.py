"""AppHub 应用与 Git HTTP 客户端测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.domain.models import AppCreateRequest
from opscli.app.transport.client import AppHubClient
from opscli.config import __version__


class FakeAuth:
    def __init__(self, tokens: list[str] | None = None) -> None:
        self.token_aliases: list[str] = []
        self.tokens = iter(tokens or ["ops-jwt"])

    def get_token(self, alias: str) -> str:
        """按调用顺序返回 JWT，模拟 AuthClient 刷新结果。"""
        self.token_aliases.append(alias)
        return next(self.tokens)


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
    auth = FakeAuth()

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
        auth_client=auth,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    payload = client.create_app(
        AppCreateRequest.from_app_name("销售看板", slug="sales-dashboard").to_dict()
    )

    request = observed["request"]
    assert request.url == "https://apphub.example/api/v1/apps"
    assert request.headers["Authorization"] == "Bearer ops-jwt"
    assert request.headers["X-Opscli-Version"] == __version__
    assert "x-session-id" not in request.headers
    assert "cookie" not in request.headers
    assert auth.token_aliases == ["ops"]
    body = json.loads(request.content)
    assert body["apiVersion"] == "apps.aukeys/v1"
    assert body["database"] == {"path": None}
    assert body["opscli"] == {"auth_mode": "viewer", "datasets": []}
    assert "runtime" not in body
    assert "python" not in body
    assert "entrypoint" not in body
    assert "services" not in body
    assert payload["app_id"] == "app-1"


def test_client_fetches_latest_jwt_for_every_request() -> None:
    authorizations = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["Authorization"])
        return httpx.Response(200, json={"apps": []})

    auth = FakeAuth(["jwt-before-refresh", "jwt-after-refresh"])
    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=auth,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.list_accessible_apps()
    client.list_accessible_apps()

    assert authorizations == ["Bearer jwt-before-refresh", "Bearer jwt-after-refresh"]
    assert auth.token_aliases == ["ops", "ops"]


def test_client_does_not_replay_response_cookie() -> None:
    cookies = []

    def handler(request: httpx.Request) -> httpx.Response:
        cookies.append(request.headers.get("Cookie"))
        headers = {"Set-Cookie": "apphub_session=server-cookie; Path=/"}
        return httpx.Response(200, json={"apps": []}, headers=headers)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AppHubClient(
        base_url="https://apphub.example",
        auth_client=FakeAuth(["jwt-first", "jwt-second"]),
        http_client=http,
    )

    client.list_accessible_apps()
    client.list_accessible_apps()

    assert http.cookies.get("apphub_session") == "server-cookie"
    assert cookies == [None, None]


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
