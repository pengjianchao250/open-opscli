from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import create_app


def main() -> None:
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
