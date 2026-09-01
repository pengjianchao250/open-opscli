"""运行时请求上下文与平台路径。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator, Mapping
from typing import Any

from opscli.app.domain.exceptions import AppProjectError
from opscli.auth import AuthClient


_HEADERS: ContextVar[dict[str, str] | None] = ContextVar("opscli_app_headers", default=None)


@contextmanager
def request_headers(headers: Mapping[str, Any]) -> Iterator[None]:
    """测试、脚本和非标准框架可显式注入请求头。"""
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    token = _HEADERS.set(normalized)
    try:
        yield
    finally:
        _HEADERS.reset(token)


def detect_headers(request: Any | None = None) -> dict[str, str]:
    explicit = _HEADERS.get()
    if explicit is not None:
        return dict(explicit)
    if request is not None and hasattr(request, "headers"):
        return {str(key).lower(): str(value) for key, value in request.headers.items()}
    try:
        import streamlit as st

        return {str(key).lower(): str(value) for key, value in st.context.headers.items()}
    except Exception:
        return {
            key.removeprefix("HTTP_").replace("_", "-").lower(): value
            for key, value in os.environ.items()
            if key.startswith("HTTP_X_")
        }


def current_user(request: Any | None = None) -> dict[str, str | None]:
    """线上读取 X-User-*，本地回退当前 ops 登录用户。"""
    headers = detect_headers(request)
    email = headers.get("x-user-email")
    if email:
        return {
            "id": headers.get("x-user-id"),
            "name": headers.get("x-user-name"),
            "email": email,
        }
    try:
        payload = AuthClient().get_me()
    except Exception as exc:
        raise AppProjectError(
            "AUTH-001",
            "无法识别当前用户。",
            fix_hint="本地执行 opscli auth login；线上确认网关已注入 X-User-*。",
        ) from exc
    user = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return {
        "id": str(user.get("id")) if user.get("id") is not None else None,
        "name": user.get("name") or user.get("username"),
        "email": user.get("email"),
    }


def base_path() -> str:
    """返回平台路径前缀，根路径统一不带尾斜杠。"""
    value = os.getenv("APP_BASE_PATH", "").strip()
    if not value:
        slug = os.getenv("APP_SLUG", "").strip()
        value = f"/apps/{slug}" if slug else ""
    if not value:
        return ""
    return "/" + value.strip("/")
