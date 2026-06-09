"""Remote Xiyou credential service client."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential, normalize_authorization
from opscli.xiyou.domain.exceptions import XiyouConfigError


_CREDENTIAL_CACHE: dict[str, tuple[float, XiyouCredential]] = {}


class XiyouCredentialServiceClient:
    """Load the latest Xiyou credential from remote ops service."""

    def __init__(self, settings: XiyouSettings, *, http_get: Any | None = None) -> None:
        self.settings = settings
        self.http_get = http_get or httpx.get

    def get_latest(self) -> XiyouCredential:
        """Fetch the latest credential payload and convert it to runtime format."""
        if not self.settings.credential_latest_url:
            raise XiyouConfigError("缺少 OPSCLI_XIYOU_CREDENTIAL_LATEST_URL")
        headers = {"accept": "application/json"}
        if self.settings.credential_api_key:
            headers["authorization"] = f"Bearer {self.settings.credential_api_key}"
        response = self.http_get(
            self.settings.credential_latest_url,
            headers=headers,
            timeout=10.0,
        )
        status_code = getattr(response, "status_code", 200)
        text = getattr(response, "text", "")
        if status_code >= 400:
            raise XiyouConfigError(f"获取西柚最新凭据失败：status={status_code} response={text[:500]}")
        try:
            payload = response.json()
        except Exception as exc:
            raise XiyouConfigError("获取西柚最新凭据失败：响应不是 JSON") from exc
        return parse_latest_credential_response(payload)


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
