"""共享的本地原型 CORS 规则。"""

from __future__ import annotations

import re

from starlette.types import Scope

LOCAL_PROTOTYPE_ORIGINS = (
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)
PRIVATE_LAN_PROTOTYPE_ORIGIN = (
    r"^http://(?:"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"):4173$"
)
_PRIVATE_LAN_PROTOTYPE_ORIGIN_PATTERN = re.compile(PRIVATE_LAN_PROTOTYPE_ORIGIN)


def is_allowed_prototype_origin(origin: str) -> bool:
    """判断 Origin 是否属于本机或私有局域网中的 JSON Lens 原型。"""
    return origin in LOCAL_PROTOTYPE_ORIGINS or bool(
        _PRIVATE_LAN_PROTOTYPE_ORIGIN_PATTERN.fullmatch(origin)
    )


def cors_headers_for_scope(scope: Scope) -> list[tuple[bytes, bytes]]:
    """为鉴权层直接返回的错误响应补充允许来源头。"""
    origin_bytes = next(
        (value for name, value in scope.get("headers", ()) if name.lower() == b"origin"),
        None,
    )
    if origin_bytes is None:
        return []
    origin = origin_bytes.decode("latin-1")
    if not is_allowed_prototype_origin(origin):
        return []
    return [
        (b"access-control-allow-origin", origin_bytes),
        (b"vary", b"Origin"),
    ]
