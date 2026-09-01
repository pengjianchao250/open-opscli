"""AppHub CLI 与应用运行时 SDK 公共出口。"""

from __future__ import annotations

from typing import Any

from opscli.app.services.publish import PublishManager


def current_user(request: Any | None = None):
    from opscli.app.sdk.context import current_user as implementation

    return implementation(request)


def ops_client(request: Any | None = None):
    from opscli.app.sdk.ops_client import ops_client as implementation

    return implementation(request)


def get_engine():
    from opscli.app.sdk.engine import get_engine as implementation

    return implementation()


def base_path() -> str:
    from opscli.app.sdk.context import base_path as implementation

    return implementation()


__all__ = ["PublishManager", "base_path", "current_user", "get_engine", "ops_client"]
