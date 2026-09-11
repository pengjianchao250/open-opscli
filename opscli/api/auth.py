"""AppHub authentication for the product REST API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator, Literal

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from opscli.api.errors import ApiAuthError
from opscli.mcp.context import mcp_request_ctx


AuthMode = Literal["viewer", "session", "local"]


@dataclass(frozen=True)
class AppHubPrincipal:
    """Verified AppHub caller and credentials scoped to the current request."""

    mode: AuthMode
    email: str
    user_id: str | None = None
    name: str | None = None
    session_id: str | None = None
    jwt: str | None = None


def _clean(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _bearer(request: Request) -> str | None:
    authorization = _clean(request.headers.get("Authorization"))
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return _clean(authorization[7:])


def _identity_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        user = data.get("user")
        return user if isinstance(user, dict) else data
    user = payload.get("user")
    return user if isinstance(user, dict) else payload


def _identity_email(identity: dict) -> str | None:
    for key in ("email", "username", "user_email", "inherit_email"):
        value = _clean(identity.get(key))
        if value:
            return value.lower()
    return None


def _identity_value(identity: dict, *keys: str) -> str | None:
    for key in keys:
        value = _clean(identity.get(key))
        if value:
            return value
    return None


def _local_fallback_enabled() -> bool:
    return os.environ.get("LOCAL_AUTH_FALLBACK_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _resolve_principal(request: Request) -> AppHubPrincipal:
    session_id = _clean(request.cookies.get("polarisUserToken")) or _clean(
        request.headers.get("X-Session-Id")
    )
    ops_token = _clean(request.headers.get("X-Ops-Token"))
    jwt = _bearer(request) or ops_token

    if session_id:
        try:
            from opscli.auth import AuthClient

            payload = await run_in_threadpool(
                AuthClient().get_me,
                session_id=session_id,
                jwt=jwt,
            )
        except Exception as exc:
            raise ApiAuthError(
                code="authentication_required",
                message="AppHub session is invalid or expired",
            ) from exc
        identity = _identity_payload(payload)
        email = _identity_email(identity)
        if not email:
            raise ApiAuthError(
                code="authentication_required",
                message="AppHub session did not resolve a user identity",
            )
        return AppHubPrincipal(
            mode="session",
            email=email,
            user_id=_identity_value(identity, "user_id", "id", "uuid"),
            name=_identity_value(identity, "name", "display_name", "username"),
            session_id=session_id,
            jwt=jwt,
        )

    if ops_token:
        email = _clean(request.headers.get("X-User-Email"))
        if not email:
            raise ApiAuthError(
                code="authentication_required",
                message="AppHub viewer identity is incomplete",
            )
        return AppHubPrincipal(
            mode="viewer",
            email=email.lower(),
            user_id=_clean(request.headers.get("X-User-Id")),
            name=_clean(request.headers.get("X-User-Name")),
            jwt=ops_token,
        )

    if _local_fallback_enabled():
        return AppHubPrincipal(
            mode="local",
            email=(
                _clean(os.environ.get("OPSCLI_LOCAL_AUTH_EMAIL"))
                or "local@opscli.invalid"
            ).lower(),
            user_id=_clean(os.environ.get("OPSCLI_LOCAL_AUTH_USER_ID")) or "local",
            name=_clean(os.environ.get("OPSCLI_LOCAL_AUTH_USER_NAME")) or "Local User",
        )

    raise ApiAuthError()


async def require_apphub_principal(request: Request) -> AsyncIterator[AppHubPrincipal]:
    """Resolve AppHub auth and expose it through the existing request context."""
    principal = await _resolve_principal(request)
    token = mcp_request_ctx.set(
        {
            "api_key": None,
            "auth_mode": f"apphub_{principal.mode}",
            "user_id": principal.user_id,
            "email": principal.email,
            "session_id": principal.session_id,
            "jwt": principal.jwt,
            "allowed_tools": None,
            "permission_enabled": False,
        }
    )
    try:
        yield principal
    finally:
        mcp_request_ctx.reset(token)
