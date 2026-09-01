from __future__ import annotations

from pathlib import Path

import httpx

from opscli.app.services.manager import AppManager
from opscli.app.services.session import PublishSessionStore
from opscli.app.transport.client import AppHubClient


def test_offline_init_does_not_require_auth(tmp_path: Path) -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("network"))))
    manager = AppManager(
        client=AppHubClient(base_url="https://apphub.example", http_client=http),
        session_store=PublishSessionStore(base_dir=tmp_path / "config"),
    )
    destination = tmp_path / "demo-app"

    result = manager.init_project("demo-app", path=destination, runtime="fastapi", offline=True)

    assert result["registered"] is False
    assert (destination / "app.yaml").is_file()
    assert (destination / "migrations" / "001_init.sql").is_file()
