"""仅使用 session 请求头的 AppHub HTTP 客户端。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import httpx

from opscli.app.domain.constants import APPHUB_URL_DEFAULT, APPHUB_URL_ENV
from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.domain.models import GitConfig
from opscli.auth import AuthClient


class AppHubClient:
    """AppHub CLI API 客户端；明确禁止携带 cookie。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_client: AuthClient | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or os.getenv(APPHUB_URL_ENV) or APPHUB_URL_DEFAULT).rstrip("/")
        self.auth_client = auth_client
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        """关闭内部创建的 httpx client。"""
        if self._owns_client:
            self.http.close()

    def get_git_config(self, slug: str) -> GitConfig:
        """读取仓库地址和当前用户绑定状态。"""
        response = self._request(
            "GET",
            f"{self.base_url}/api/apps/{slug}/git-config",
            headers=self._headers("application/json"),
        )
        data = self._json(response)
        return GitConfig(
            repo_url=str(data["repo_url"]),
            username=data.get("username"),
            bound=bool(data.get("bound")),
            token_hint=data.get("token_hint"),
            issued_at=data.get("issued_at"),
        )

    def create_app(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self._json(self._request(
            "POST", f"{self.base_url}/api/apps",
            headers=self._headers("application/json"), json=manifest,
        ))

    def get_app(self, slug: str) -> dict[str, Any]:
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}", headers=self._headers("application/json"),
        ))

    def issue_git_credential(self, *, rotate: bool) -> tuple[str, str, str]:
        """签发一次性 Git 凭据，不保留完整响应对象。"""
        response = self._request(
            "POST",
            f"{self.base_url}/api/git/credentials",
            headers=self._headers("application/json"),
            json={"rotate": rotate},
        )
        data = self._json(response)
        return str(data["username"]), str(data["token"]), str(data["token_hint"])

    def revoke_git_credential(self) -> int:
        """吊销当前用户全部 AppHub Git 凭据。"""
        response = self._request(
            "DELETE",
            f"{self.base_url}/api/git/credentials",
            headers=self._headers("application/json"),
        )
        data = self._json(response)
        return int(data.get("revoked_count", 0))

    def list_releases(
        self,
        slug: str,
        *,
        page: int = 1,
        size: int = 20,
        is_rollback: bool | None = False,
    ) -> dict[str, Any]:
        """获取版本列表和服务端选择的 NOOP baseline。"""
        response = self._request(
            "GET",
            f"{self.base_url}/api/apps/{slug}/releases",
            headers=self._headers("application/json"),
            params={
                "page": page,
                "size": size,
                **({"is_rollback": str(is_rollback).lower()} if is_rollback is not None else {}),
            },
        )
        return self._json(response)

    def rollback_preflight(self, slug: str, version: int) -> dict[str, Any]:
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}/rollback/preflight",
            headers=self._headers("application/json"), params={"version": version},
        ))

    def start_rollback(self, slug: str, version: int) -> dict[str, Any]:
        return self._json(self._request(
            "POST", f"{self.base_url}/api/apps/{slug}/rollback",
            headers=self._headers("application/json"), json={"version": version},
        ))

    def get_logs(
        self,
        slug: str,
        *,
        log_type: str = "runtime",
        tail: int = 200,
        release: str | None = None,
    ) -> dict[str, Any]:
        params = {"type": log_type, "tail": tail, "follow": 0}
        if release:
            params["release"] = release
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}/logs",
            headers=self._headers("application/json"), params=params,
        ))

    @contextmanager
    def logs_stream(
        self,
        slug: str,
        *,
        log_type: str = "runtime",
        tail: int = 200,
        release: str | None = None,
    ) -> Iterator[httpx.Response]:
        params: dict[str, Any] = {"type": log_type, "tail": tail, "follow": 1}
        if release:
            params["release"] = release
        with self.http.stream(
            "GET", f"{self.base_url}/api/apps/{slug}/logs",
            headers=self._headers("text/event-stream"), params=params, timeout=None,
        ) as response:
            self._raise_for_status(response)
            yield response

    def get_env(self, slug: str) -> dict[str, Any]:
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}/env", headers=self._headers("application/json"),
        ))

    def put_env(self, slug: str, env: dict[str, str]) -> dict[str, Any]:
        return self._json(self._request(
            "PUT", f"{self.base_url}/api/apps/{slug}/env",
            headers=self._headers("application/json"), json={"env": env},
        ))

    def list_secrets(self, slug: str) -> dict[str, Any]:
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}/secrets", headers=self._headers("application/json"),
        ))

    def put_secrets(self, slug: str, secrets: dict[str, str]) -> dict[str, Any]:
        return self._json(self._request(
            "PUT", f"{self.base_url}/api/apps/{slug}/secrets",
            headers=self._headers("application/json"), json={"secrets": secrets},
        ))

    def delete_secret(self, slug: str, key: str) -> dict[str, Any]:
        return self._json(self._request(
            "DELETE", f"{self.base_url}/api/apps/{slug}/secrets/{key}",
            headers=self._headers("application/json"),
        ))

    def list_members(self, slug: str) -> dict[str, Any]:
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}/members", headers=self._headers("application/json"),
        ))

    def add_member(self, slug: str, email: str) -> dict[str, Any]:
        return self._json(self._request(
            "POST", f"{self.base_url}/api/apps/{slug}/members",
            headers=self._headers("application/json"), json={"email": email, "role": "member"},
        ))

    def remove_member(self, slug: str, email: str) -> dict[str, Any]:
        return self._json(self._request(
            "DELETE", f"{self.base_url}/api/apps/{slug}/members/{email}",
            headers=self._headers("application/json"),
        ))

    def get_db(self, slug: str) -> dict[str, Any]:
        return self._json(self._request(
            "GET", f"{self.base_url}/api/apps/{slug}/db", headers=self._headers("application/json"),
        ))

    def restore_db(
        self,
        slug: str,
        *,
        backup_date: str,
        confirm: str,
        filename: str | None = None,
    ) -> dict[str, Any]:
        return self._json(self._request(
            "POST", f"{self.base_url}/api/apps/{slug}/db/restore",
            headers=self._headers("application/json"),
            params={"file": filename} if filename else None,
            json={"backup_date": backup_date, "confirm": confirm},
        ))

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise AppHubHttpError(
                "UPSTREAM_ERROR",
                "无法连接 AppHub。",
                fix_hint="检查网络后重试。",
            ) from exc

    @contextmanager
    def release_stream(self, slug: str, commit_sha: str, message: str) -> Iterator[httpx.Response]:
        """创建 release 并打开 SSE 流。"""
        with self.http.stream(
            "POST",
            f"{self.base_url}/api/apps/{slug}/releases",
            headers=self._headers("text/event-stream"),
            json={"commit_sha": commit_sha, "message": message},
            timeout=None,
        ) as response:
            self._raise_for_status(response)
            yield response

    @contextmanager
    def resume_stream(self, slug: str, release_id: int, last_seq: int) -> Iterator[httpx.Response]:
        """从 last_seq 后续订同一 release。"""
        with self.http.stream(
            "GET",
            f"{self.base_url}/api/apps/{slug}/releases/{release_id}/events",
            headers=self._headers("text/event-stream"),
            params={"since_seq": last_seq},
            timeout=None,
        ) as response:
            self._raise_for_status(response)
            yield response

    def _headers(self, accept: str) -> dict[str, str]:
        if self.auth_client is None:
            self.auth_client = AuthClient()
        headers = self.auth_client.build_session_headers()
        headers["Accept"] = accept
        return headers

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        self._raise_for_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise AppHubHttpError(
                "APPHUB-PROTOCOL",
                "AppHub 返回了无效 JSON。",
                request_id=response.headers.get("X-Request-Id"),
            ) from exc
        if not isinstance(data, dict):
            raise AppHubHttpError("APPHUB-PROTOCOL", "AppHub JSON 响应必须是对象。")
        return data

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        payload: dict[str, Any] = {}
        try:
            raw = response.json()
            if isinstance(raw, dict):
                nested = raw.get("detail")
                payload = nested if isinstance(nested, dict) else raw
        except ValueError:
            payload = {}
        code = str(payload.get("code") or f"HTTP-{response.status_code}")
        message = str(payload.get("message") or f"AppHub 请求失败（HTTP {response.status_code}）。")
        fix_hint = payload.get("fix_hint")
        if response.status_code == 426 and not fix_hint:
            fix_hint = "执行 opscli self-update 后重试。"
        raise AppHubHttpError(
            code,
            message,
            fix_hint=fix_hint,
            request_id=payload.get("request_id") or response.headers.get("X-Request-Id"),
            detail=payload.get("detail") if isinstance(payload.get("detail"), dict) else None,
        )
