from __future__ import annotations

from pathlib import Path

from opscli.app.services.project import ProjectLoader
from opscli.app.services.runner import platform_env, start_command
from opscli.app.services.templates import render_template


def test_fastapi_command_and_platform_env(tmp_path: Path) -> None:
    render_template(tmp_path, slug="demo-app", runtime="fastapi")
    project = ProjectLoader().load(tmp_path)

    command = start_command(project, port=8123)
    env = platform_env(project, port=8123)

    assert command == [
        "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8123", "--root-path", "/apps/demo-app",
    ]
    assert env["APP_BASE_PATH"] == "/apps/demo-app"
    assert env["APP_DB_PATH"].endswith("demo-app\\app.db") or env["APP_DB_PATH"].endswith("demo-app/app.db")
