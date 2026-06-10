"""Remote Xiyou credential service client."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

from opscli.auth import AuthClient
from opscli.mcp.context import get_mcp_request_headers
from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential, normalize_authorization
from opscli.xiyou.domain.exceptions import XiyouConfigError


_CREDENTIAL_CACHE: dict[str, tuple[float, XiyouCredential]] = {}
ENV_DEBUG_CREDENTIAL_REQUEST = "OPSCLI_XIYOU_DEBUG_CREDENTIAL_REQUEST"


class XiyouCredentialServiceClient:
    """Load the latest Xiyou credential from remote ops service."""

    def __init__(
        self,
        settings: XiyouSettings,
        *,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
        http_get: Any | None = None,
    ) -> None:
        self.settings = settings
        self.auth_client = auth_client or AuthClient()
        self.jwt = jwt
        self.session_id = session_id
        self.http_get = http_get or httpx.get

    def get_latest(self) -> XiyouCredential:
        """Fetch the latest credential payload and convert it to runtime format."""
        if not self.settings.credential_latest_url:
            raise XiyouConfigError("缺少 OPSCLI_XIYOU_CREDENTIAL_LATEST_URL")
        headers, cookies = self._get_auth("ops")
        headers.setdefault("accept", "application/json")
        _emit_debug(
            "request",
            {
                "url": self.settings.credential_latest_url,
                "method": "GET",
                "headers": headers,
                "cookies": cookies,
                "timeout": 10.0,
                "auth_mode": _detect_auth_mode(headers, cookies),
            },
        )
        response = self.http_get(
            self.settings.credential_latest_url,
            headers=headers,
            cookies=cookies,
            timeout=10.0,
        )
        status_code = getattr(response, "status_code", 200)
        text = getattr(response, "text", "")
        _emit_debug(
            "response_meta",
            {
                "status_code": status_code,
                "text_preview": text[:1000],
            },
        )
        if status_code >= 400:
            raise XiyouConfigError(f"获取西柚最新凭据失败：status={status_code} response={text[:500]}")
        try:
            payload = response.json()
        except Exception as exc:
            raise XiyouConfigError("获取西柚最新凭据失败：响应不是 JSON") from exc
        _emit_debug("response_json", payload)
        return parse_latest_credential_response(payload)

    def _get_auth(self, alias: str = "ops") -> tuple[dict[str, str], dict[str, str]]:
        mcp_headers = get_mcp_request_headers()
        if self.settings.credential_api_key:
            headers = {"authorization": f"Bearer {self.settings.credential_api_key}"}
            headers.update(mcp_headers)
            return headers, {}
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            headers.update(mcp_headers)
            return headers, {"polarisUserToken": self.session_id}
        if self.jwt:
            headers = {"Authorization": f"Bearer {self.jwt}"}
            headers.update(mcp_headers)
            return headers, {}
        if _has_mcp_api_key(mcp_headers):
            return mcp_headers, {}
        headers, cookies = self.auth_client.build_request_auth(alias)
        headers.update(mcp_headers)
        return headers, cookies


def get_cached_remote_credential(
    settings: XiyouSettings,
    *,
    refresh: bool = False,
    client: XiyouCredentialServiceClient | None = None,
) -> XiyouCredential:
    """Fetch remote credential with in-process caching."""
    if not settings.credential_latest_url:
        raise XiyouConfigError("缺少 OPSCLI_XIYOU_CREDENTIAL_LATEST_URL")
    cache_key = settings.credential_latest_url
    cached = _CREDENTIAL_CACHE.get(cache_key)
    if not refresh and cached and time.time() - cached[0] < settings.credential_cache_ttl_seconds:
        _emit_debug(
            "cache_hit",
            {
                "url": settings.credential_latest_url,
                "ttl_seconds": settings.credential_cache_ttl_seconds,
                "cached_at": cached[0],
            },
        )
        return cached[1]
    active_client = client or XiyouCredentialServiceClient(settings)
    credential = active_client.get_latest()
    _CREDENTIAL_CACHE[cache_key] = (time.time(), credential)
    return credential


def parse_latest_credential_response(payload: Any) -> XiyouCredential:
    """Support both legacy credential payloads and new mcp-accounts responses."""
    if not isinstance(payload, dict):
        raise XiyouConfigError("西柚最新凭据响应必须是 JSON 对象")

    if payload.get("success") is False:
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        raise XiyouConfigError(f"获取西柚最新凭据失败：{message or 'success=false'}")

    code = payload.get("code")
    if code not in (None, 0, 200, "0", "200"):
        msg = _optional_str(payload.get("msg"))
        raise XiyouConfigError(f"获取西柚最新凭据失败：{msg or f'code={code}'}")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    credential_payload = _extract_credential_payload(data)
    authorization = normalize_authorization(
        credential_payload.get("authorization")
        or credential_payload.get("auth")
        or credential_payload.get("token")
    )
    cookie = credential_payload.get("cookie")
    headers = credential_payload.get("headers") if isinstance(credential_payload.get("headers"), dict) else {}
    return XiyouCredential(
        authorization=authorization,
        cookie=str(cookie).strip() if cookie else None,
        source="credential_service",
        operator=_optional_str(data.get("updated_by") or data.get("operator") or data.get("remark")),
        updated_at=_optional_str(data.get("updated_at")),
        expires_at=_optional_str(data.get("expires_at")),
        version=data.get("version") or data.get("id"),
        headers={str(key): str(value) for key, value in headers.items() if value is not None},
    )


def _extract_credential_payload(data: dict[str, Any]) -> dict[str, Any]:
    credential_payload = data.get("credential") if isinstance(data.get("credential"), dict) else data
    cookie_content = credential_payload.get("cookie_content")
    if isinstance(cookie_content, str) and cookie_content.strip():
        return _parse_cookie_content(cookie_content, fallback=credential_payload)
    return credential_payload


def _parse_cookie_content(raw: str, *, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        content = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise XiyouConfigError("西柚最新凭据里的 cookie_content 不是有效 JSON") from exc
    if not isinstance(content, dict):
        raise XiyouConfigError("西柚最新凭据里的 cookie_content 结构错误")

    headers: dict[str, str] = {}
    krs_ver = _optional_str(content.get("OPSCLI_XIYOU_KRS_VER"))
    if krs_ver:
        headers["krs-ver"] = krs_ver

    web_version = _optional_str(content.get("OPSCLI_XIYOU_WEB_VERSION"))
    if web_version:
        headers["web-version"] = web_version

    fallback_headers = fallback.get("headers")
    if isinstance(fallback_headers, dict):
        for key, value in fallback_headers.items():
            if value is not None and str(key).strip():
                headers.setdefault(str(key).strip(), str(value))

    return {
        "authorization": content.get("OPSCLI_XIYOU_AUTHORIZATION"),
        "cookie": content.get("OPSCLI_XIYOU_COOKIE"),
        "headers": headers,
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _has_mcp_api_key(headers: dict[str, str]) -> bool:
    return bool(headers.get("X-MCP-API-Key"))


def _debug_enabled() -> bool:
    value = str(os.getenv(ENV_DEBUG_CREDENTIAL_REQUEST, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _emit_debug(stage: str, payload: Any) -> None:
    if not _debug_enabled():
        return
    message = {
        "module": "xiyou.credential_service",
        "stage": stage,
        "payload": payload,
    }
    sys.stderr.write(f"[xiyou-debug] {json.dumps(message, ensure_ascii=False)}\n")
    sys.stderr.flush()


def _detect_auth_mode(headers: dict[str, str], cookies: dict[str, str]) -> str:
    if headers.get("X-MCP-API-Key"):
        return "mcp_api_key"
    if cookies.get("polarisUserToken"):
        return "session_cookie"
    if headers.get("Authorization") or headers.get("authorization"):
        return "bearer_token"
    return "unknown"
