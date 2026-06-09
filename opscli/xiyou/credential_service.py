"""西柚运营后台凭据服务客户端。"""

from __future__ import annotations

import time
from typing import Any

import httpx

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential, normalize_authorization
from opscli.xiyou.domain.exceptions import XiyouConfigError


_CREDENTIAL_CACHE: dict[str, tuple[float, XiyouCredential]] = {}


class XiyouCredentialServiceClient:
    """从运营后台读取西柚最新凭据。"""

    def __init__(self, settings: XiyouSettings, *, http_get: Any | None = None) -> None:
        self.settings = settings
        self.http_get = http_get or httpx.get

    def get_latest(self) -> XiyouCredential:
        """调用运营后台 latest 接口，返回可直接用于西柚 API 的凭据。"""
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
            raise XiyouConfigError(f"获取西柚最新凭据失败 status={status_code} response={text[:500]}")
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
    """读取远程凭据并做进程内缓存，避免同一进程高频请求后台。"""
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
    """解析后台 latest 接口响应，兼容 data.credential 和顶层 credential。"""
    if not isinstance(payload, dict):
        raise XiyouConfigError("西柚最新凭据响应必须是 JSON 对象")
    if payload.get("success") is False:
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        raise XiyouConfigError(f"获取西柚最新凭据失败：{message or 'success=false'}")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    credential_payload = data.get("credential") if isinstance(data.get("credential"), dict) else data
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
        operator=_optional_str(data.get("updated_by") or data.get("operator")),
        updated_at=_optional_str(data.get("updated_at")),
        expires_at=_optional_str(data.get("expires_at")),
        version=data.get("version"),
        headers={str(key): str(value) for key, value in headers.items()},
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
