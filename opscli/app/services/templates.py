"""AppHub 三种 MVP runtime 的标准模板。"""

from __future__ import annotations

from pathlib import Path

from opscli.app.domain.exceptions import AppProjectError


_APP_YAML = """apiVersion: apps.aukeys/v1
name: {slug}
title: {title}
description: ""
runtime: {runtime}
python: "3.11"
entrypoint: app.py
services:
  sqlite: true
opscli:
  auth_mode: viewer
  datasets: []
llm:
  enabled: false
access:
  visibility: members
"""

_STREAMLIT = """import streamlit as st

from opscli.app import base_path, current_user, get_engine

st.title({title!r})
st.write({{"user": current_user(), "base_path": base_path()}})
with get_engine().begin() as connection:
    connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS visits(id INTEGER PRIMARY KEY)")
"""

_FASTAPI = """from fastapi import FastAPI, Request

from opscli.app import base_path, current_user

app = FastAPI()


@app.get("/")
def index(request: Request):
    return {{"title": {title!r}, "user": current_user(request), "base_path": base_path()}}
"""

_GRADIO = """import gradio as gr

from opscli.app import base_path, current_user


def whoami(request: gr.Request):
    return str({{"user": current_user(request), "base_path": base_path()}})


with gr.Blocks() as demo:
    gr.Markdown("# {title}")
    output = gr.Textbox()
    gr.Button("当前用户").click(whoami, outputs=output)

demo.launch()
"""

_REQUIREMENTS = {
    "streamlit": "streamlit==1.49.1\naukeys-opscli>=0.0.129\n",
    "fastapi": "fastapi==0.116.1\nuvicorn==0.35.0\naukeys-opscli>=0.0.129\n",
    "gradio": "gradio==5.44.1\naukeys-opscli>=0.0.129\n",
}

_APP_CODE = {
    "streamlit": _STREAMLIT,
    "fastapi": _FASTAPI,
    "gradio": _GRADIO,
}

_IGNORE = """.env
.venv/
venv/
__pycache__/
*.pyc
*.db
*.sqlite
*.sqlite3
"""


def manifest_data(*, slug: str, runtime: str, title: str | None = None) -> dict:
    return {
        "apiVersion": "apps.aukeys/v1",
        "name": slug,
        "title": title or slug,
        "description": "",
        "runtime": runtime,
        "python": "3.11",
        "entrypoint": "app.py",
        "services": {"sqlite": True},
        "opscli": {"auth_mode": "viewer", "datasets": []},
        "llm": {"enabled": False},
        "access": {"visibility": "members"},
    }


def render_template(root: Path, *, slug: str, runtime: str, title: str | None = None) -> list[str]:
    """在空目录生成 AppHub 标准工程。"""
    if runtime not in _APP_CODE:
        raise AppProjectError("APP-RUNTIME-UNSUPPORTED", f"不支持的模板 runtime：{runtime}")
    root.mkdir(parents=True, exist_ok=True)
    existing = [path.name for path in root.iterdir() if path.name != ".git"]
    if existing:
        raise AppProjectError(
            "APP-INIT-NOT-EMPTY",
            f"目标目录非空：{root}",
            fix_hint="请使用空目录，或在已有项目根目录手工补齐 app.yaml 后重试。",
        )
    display_title = title or slug
    files = {
        "app.yaml": _APP_YAML.format(slug=slug, title=display_title, runtime=runtime),
        "app.py": _APP_CODE[runtime].format(title=display_title),
        "requirements.txt": _REQUIREMENTS[runtime],
        ".gitignore": _IGNORE,
        ".appignore": _IGNORE,
        "migrations/001_init.sql": "CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT);\n",
        "docs/README.md": "# AppHub 应用\n\n使用 `opscli app run` 本地运行，使用 `opscli app publish -m \"说明\"` 发布。\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return sorted(files)
