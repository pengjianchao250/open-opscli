"""AppHub 创建站点占位 HTTP 客户端。"""

from __future__ import annotations

import os
from typing import Any

import httpx

from opscli.app.domain.constants import APPHUB_CREATE_SITE_URL_DEFAULT, APPHUB_CREATE_SITE_URL_ENV
from opscli.app.domain.exceptions import AppHubHttpError
from opscli.auth import AuthClient


class AppHubClient:
    """当前只封装创建站点；正式服务落地后替换此适配层。"""

    def __init__(
        self,
        *,
        create_site_url: str | None = None,
        auth_client: AuthClient | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.create_site_url = (
            create_site_url
            or os.getenv(APPHUB_CREATE_SITE_URL_ENV)
            or APPHUB_CREATE_SITE_URL_DEFAULT
        )
        self.auth_client = auth_client
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def create_site(self, site_name: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            self.create_site_url,
            headers=self._headers(),
            json={"name": site_name},
        )
        payload = self._json(response)
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def _headers(self) -> dict[str, str]:
        if self.auth_client is None:
            self.auth_client = AuthClient()
        headers = self.auth_client.build_session_headers()
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/json"
        return headers

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise AppHubHttpError(
                "UPSTREAM_ERROR",
                "无法连接 AppHub 创建站点服务。",
                fix_hint=f"当前为占位服务，可通过 {APPHUB_CREATE_SITE_URL_ENV} 替换地址。",
            ) from exc

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            self._raise_for_status(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppHubHttpError("APPHUB-PROTOCOL", "AppHub 返回了无效 JSON。") from exc
        if not isinstance(payload, dict):
            raise AppHubHttpError("APPHUB-PROTOCOL", "AppHub JSON 响应必须是对象。")
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        payload: dict[str, Any] = {}
        try:
            raw = response.json()
            if isinstance(raw, dict):
                detail = raw.get("detail")
                payload = detail if isinstance(detail, dict) else raw
        except ValueError:
            pass
        raise AppHubHttpError(
            str(payload.get("code") or f"HTTP-{response.status_code}"),
            str(payload.get("message") or f"AppHub 请求失败（HTTP {response.status_code}）。"),
            fix_hint=payload.get("fix_hint"),
            request_id=payload.get("request_id") or response.headers.get("X-Request-Id"),
        )
