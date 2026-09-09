"""AppHub 应用与 Git 源码交付所需的 HTTP 客户端。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from opscli.app.domain.constants import APPHUB_API_PREFIX
from opscli.app.domain.exceptions import AppHubHttpError, AppProjectError
from opscli.app.domain.models import validate_app_id
from opscli.auth import AuthClient
from opscli.auth.config import get_apphub_url
from opscli.config import __version__

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

    def creation_scope(self) -> str:
        """以控制面地址和已登录主体隔离本地创建重试，不保存个人信息。"""
        if self.auth_client is None:
            self.auth_client = AuthClient()
        profile = self.auth_client.get_me()
        data = profile.get("data", profile)
        owner = data.get("id") if isinstance(data, dict) else None
        if isinstance(owner, bool) or not isinstance(owner, (str, int)) or not str(owner).strip():
            raise AppHubHttpError("APPHUB-PROTOCOL", "当前用户响应缺少稳定用户 ID。")
        scope = json.dumps([self.api_base_url, str(owner)], separators=(",", ":"))
        return hashlib.sha256(scope.encode("utf-8")).hexdigest()

    def create_app(self, request_payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        """使用调用方已经持久化的 UUID，避免网络重试重复创建。"""
        try:
            UUID(idempotency_key)
        except (ValueError, TypeError, AttributeError) as exc:
            raise AppProjectError("APP-ARGUMENT", "创建幂等键必须是 UUID。") from exc
        return self._request_json(
            "POST", "/apps", json=request_payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    def get_app(self, app_id: str) -> dict[str, Any]:
        """按大小写敏感的公开 ID 获取唯一应用。"""
        return self._request_json("GET", f"/apps/{_segment(validate_app_id(app_id))}")

    def list_accessible_apps(self) -> dict[str, Any]:
        return self._request_json("GET", "/accessible-apps")

    def get_git_config(self, app_id: str) -> dict[str, Any]:
        """按公开 ID 获取平台保存的仓库绑定，不从 slug 拼接仓库。"""
        return self._request_json("GET", f"/apps/{_segment(validate_app_id(app_id))}/git-config")

    def issue_git_credential(self, *, rotate: bool) -> dict[str, Any]:
        return self._request_json("POST", "/git/credentials", json={"rotate": rotate})

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """构造无 Cookie 的 Bearer 请求并复用现有 JSON 错误处理。"""
        try:
            request = self.http.build_request(
                method,
                self._url(path),
                headers={**self._headers(has_json="json" in kwargs), **kwargs.pop("headers", {})},
                **kwargs,
            )
            request.headers.pop("Cookie", None)
            response = self.http.send(request)
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
        """每次请求复用 AuthClient 的 ops JWT 获取与刷新能力。"""
        if self.auth_client is None:
            self.auth_client = AuthClient()
        token = self.auth_client.get_token("ops")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Opscli-Version": __version__,
        }
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
