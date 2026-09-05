"""AppHub 应用与 Git 源码交付所需的 HTTP 客户端。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from opscli.app.domain.constants import APPHUB_API_PREFIX
from opscli.app.domain.exceptions import AppHubHttpError
from opscli.auth import AuthClient
from opscli.auth.config import get_apphub_url

class AppHubClient:
    """封装应用创建、查询和 Git 凭据所需的 AppHub API。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_client: AuthClient | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        root = base_url or get_apphub_url()
        self.api_base_url = f"{root.rstrip('/')}{APPHUB_API_PREFIX}"
        self.auth_client = auth_client
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def create_app(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/apps", json=request_payload)

    def get_app(self, slug: str) -> dict[str, Any]:
        return self._request_json("GET", f"/apps/{_segment(slug)}")

    def list_accessible_apps(self) -> dict[str, Any]:
        return self._request_json("GET", "/accessible-apps")

    def get_git_config(self, slug: str) -> dict[str, Any]:
        return self._request_json("GET", f"/apps/{_segment(slug)}/git-config")

    def issue_git_credential(self, *, rotate: bool) -> dict[str, Any]:
        return self._request_json("POST", "/git/credentials", json={"rotate": rotate})

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.http.request(
                method,
                self._url(path),
                headers=self._headers(has_json="json" in kwargs),
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise AppHubHttpError(
                "UPSTREAM_ERROR",
                "无法连接 AppHub 服务。",
                fix_hint="检查当前 opscli 环境的 apphub_url 配置后重试。",
            ) from exc
        payload = self._json(response)
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def _headers(self, *, accept: str = "application/json", has_json: bool = False) -> dict[str, str]:
        if self.auth_client is None:
            self.auth_client = AuthClient()
        headers = self.auth_client.build_session_headers()
        headers["Accept"] = accept
        if has_json:
            headers["Content-Type"] = "application/json"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.api_base_url}{path}"

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
        status = response.status_code
        fix_hint = payload.get("fix_hint") or _status_fix_hint(status)
        raise AppHubHttpError(
            str(payload.get("code") or f"HTTP-{status}"),
            str(payload.get("message") or f"AppHub 请求失败（HTTP {status}）。"),
            fix_hint=fix_hint,
            request_id=payload.get("request_id") or response.headers.get("X-Request-Id"),
        )


def _segment(value: str) -> str:
    return quote(value, safe="")


def _status_fix_hint(status: int) -> str | None:
    return {
        401: "请先执行 opscli auth login 重新登录。",
        403: "当前账号没有该应用权限，请联系应用 owner。",
        426: "当前 opscli 版本过低，请升级后重试。",
        502: "AppHub 上游暂不可用，请稍后幂等重试。",
        503: "AppHub 服务暂不可用，请稍后幂等重试。",
    }.get(status)
