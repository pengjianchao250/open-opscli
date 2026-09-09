import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import _default_keepa_runner, create_app


def verify_apphub_auth_context() -> None:
    """Viewer JWT must stay in the AppHub credential path without a Session."""
    observed = {}

    async def fake_keepa_run(**kwargs):
        from opscli.mcp.context import get_current_auth_mode, mcp_request_ctx

        context = mcp_request_ctx.get() or {}

        observed.update(
            {
                "auth_mode": get_current_auth_mode(),
                "email": context.get("email"),
                "session_id": context.get("session_id"),
                "jwt": context.get("jwt"),
                "kwargs": kwargs,
            }
        )
        return {"success": True, "data": [], "error": None}

    passthrough = lambda fn, **_kwargs: fn
    with (
        patch("opscli.mcp.instrumentation.quota_wrap", passthrough),
        patch("opscli.mcp.instrumentation.telemetry_wrap", passthrough),
        patch("opscli.mcp.tools.keepa.keepa_run", fake_keepa_run),
    ):
        result = asyncio.run(
            _default_keepa_runner(
                scenario="product-search",
                params={"keyword": "flashlight"},
                site="US",
                export_format="json",
                wait=True,
                session_id=None,
                jwt="viewer-jwt",
                user_email="viewer@example.com",
            )
        )

    assert result["success"] is True
    assert observed["auth_mode"] == "apphub_viewer"
    assert observed["email"] == "viewer@example.com"
    assert observed["session_id"] is None
    assert observed["jwt"] == "viewer-jwt"
    assert "user_email" not in observed["kwargs"]


def main() -> None:
    verify_apphub_auth_context()
    captured = {}

    async def fake_keepa_runner(**kwargs):
        captured.update(kwargs)
        return {"success": True, "data": [{"asin": "B000TEST"}], "error": None}

    with TemporaryDirectory() as directory:
        dist = Path(directory)
        (dist / "index.html").write_text("<h1>test-keepa</h1>", encoding="utf-8")
        app = create_app(frontend_dist=dist, keepa_runner=fake_keepa_runner)

        with TestClient(app) as client:
            health = client.get("/__apphub_healthz")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}

            page = client.get("/")
            assert page.status_code == 200
            assert "test-keepa" in page.text

            missing_api = client.get("/api/unknown")
            assert missing_api.status_code == 404

            unauthenticated = client.post(
                "/api/v1/keepa/run",
                json={"scenario": "product", "params": {"asin": "B000TEST"}},
            )
            assert unauthenticated.status_code == 401
            assert unauthenticated.json()["error"]["code"] == "authentication_required"

            keepa = client.post(
                "/api/v1/keepa/run",
                headers={
                    "X-Ops-Token": "test-jwt",
                    "X-User-Email": "viewer@example.com",
                },
                json={
                    "scenario": "product",
                    "site": "US",
                    "params": {"asin": "B000TEST"},
                    "export_format": "json",
                    "wait": True,
                },
            )
            assert keepa.status_code == 200
            assert keepa.json()["data"] == [{"asin": "B000TEST"}]
            assert captured == {
                "scenario": "product",
                "params": {"asin": "B000TEST"},
                "site": "US",
                "export_format": "json",
                "force": False,
                "wait": True,
                "session_id": None,
                "jwt": "test-jwt",
                "user_email": "viewer@example.com",
            }


if __name__ == "__main__":
    main()
