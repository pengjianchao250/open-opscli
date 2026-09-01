"""AppHub 本地同构运行器。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import AppProject
from opscli.app.services.migrations import run_migrations


def platform_env(project: AppProject, *, port: int) -> dict[str, str]:
    env = {
        "PORT": str(port),
        "APP_BASE_PATH": f"/apps/{project.slug}",
        "APP_SLUG": project.slug,
    }
    if project.manifest.sqlite_enabled:
        data_dir = Path.home() / ".config" / "opscli" / "app-data" / project.slug
        env["APP_DB_PATH"] = str(data_dir / "app.db")
    return env


def start_command(project: AppProject, *, port: int) -> list[str]:
    entrypoint = project.manifest.entrypoint
    base_path = f"/apps/{project.slug}"
    if project.manifest.runtime == "streamlit":
        return [
            "streamlit", "run", entrypoint,
            "--server.address", "127.0.0.1",
            "--server.port", str(port),
            "--server.baseUrlPath", base_path,
            "--server.headless", "true",
        ]
    if project.manifest.runtime == "fastapi":
        module = entrypoint.removesuffix(".py").replace("/", ".").replace("\\", ".")
        return ["uvicorn", f"{module}:app", "--host", "127.0.0.1", "--port", str(port), "--root-path", base_path]
    if project.manifest.runtime == "gradio":
        return [sys.executable, entrypoint]
    raise AppProjectError("APP-RUNTIME-UNSUPPORTED", f"不支持 runtime：{project.manifest.runtime}")


def run_project(project: AppProject, *, port: int = 8000) -> dict:
    env = os.environ.copy()
    env.update(platform_env(project, port=port))
    if project.manifest.runtime == "gradio":
        env["GRADIO_ROOT_PATH"] = f"/apps/{project.slug}"
        env["GRADIO_SERVER_PORT"] = str(port)
        env["GRADIO_SERVER_NAME"] = "127.0.0.1"
    run_migrations(project.root, db_path=env.get("APP_DB_PATH"))
    command = start_command(project, port=port)
    try:
        completed = subprocess.run(command, cwd=project.root, env=env, check=False)
    except OSError as exc:
        raise AppProjectError(
            "APP-RUN-FAILED",
            f"无法启动 {project.manifest.runtime}：{exc}",
            fix_hint="安装 requirements.txt 后重试。",
        ) from exc
    if completed.returncode != 0:
        raise AppProjectError("APP-RUN-FAILED", f"应用进程退出码：{completed.returncode}")
    return {"slug": project.slug, "returncode": completed.returncode, "command": command}
