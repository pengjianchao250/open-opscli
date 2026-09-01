from __future__ import annotations

import httpx

from opscli.app.sdk.context import base_path, current_user, request_headers
from opscli.app.sdk.ops_client import OpsClient


def test_context_uses_injected_headers(monkeypatch) -> None:
    monkeypatch.setenv("APP_BASE_PATH", "/apps/demo-app/")
    with request_headers({"X-User-Id": "7", "X-User-Name": "Demo", "X-User-Email": "demo@example.com"}):
        assert current_user()["email"] == "demo@example.com"
    assert base_path() == "/apps/demo-app"


def test_viewer_client_uses_ops_token() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["token"] = request.headers.get("X-Ops-Token")
        return httpx.Response(200, json={"rows": [{"value": 1}]})

    client = OpsClient(
        viewer_token="viewer-token",
        ops_url="https://ops.example/api",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.query(table_id=1, metrics=["ds_x.value"])
    assert result["rows"] == [{"value": 1}]
    assert observed["token"] == "viewer-token"
