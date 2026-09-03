"""AppHub 第一阶段必需 API 的 HTTP/SSE 客户端。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from opscli.app.domain.constants import (
    APPHUB_API_PREFIX,
    SSE_MAX_RECONNECTS,
)
from opscli.app.domain.exceptions import AppHubHttpError
from opscli.app.services.sse import parse_sse_lines
from opscli.auth import AuthClient
from opscli.auth.config import get_apphub_url

EventCallback = Callable[[dict[str, Any]], None]


class AppHubClient:
    """仅封装 create/init/push 闭环所需的 AppHub API。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_client: AuthClient | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
        max_sse_reconnects: int = SSE_MAX_RECONNECTS,
    ) -> None:
        root = base_url or get_apphub_url()
        self.api_base_url = f"{root.rstrip('/')}{APPHUB_API_PREFIX}"
        self.auth_client = auth_client
        self.max_sse_reconnects = max_sse_reconnects
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def create_app(self, app_yaml: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/apps", json=app_yaml)

    def get_app(self, slug: str) -> dict[str, Any]:
        return self._request_json("GET", f"/apps/{_segment(slug)}")

    def get_git_config(self, slug: str) -> dict[str, Any]:
        return self._request_json("GET", f"/apps/{_segment(slug)}/git-config")

    def issue_git_credential(self, *, rotate: bool) -> dict[str, Any]:
        return self._request_json("POST", "/git/credentials", json={"rotate": rotate})

    def list_releases(
        self,
        slug: str,
        *,
        page: int = 1,
        size: int = 1,
        is_rollback: bool = False,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/apps/{_segment(slug)}/releases",
            params={"page": page, "size": size, "is_rollback": str(is_rollback).lower()},
        )

    def publish_release(
        self,
        slug: str,
        *,
        commit_sha: str,
        message: str,
        on_event: EventCallback | None = None,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "release_id": None,
            "last_seq": -1,
            "events": [],
            "terminal_event": None,
        }
        done = self._stream_once(
            "POST",
            f"/apps/{_segment(slug)}/releases",
            state=state,
            json={"commit_sha": commit_sha, "message": message},
            on_event=on_event,
        )
        reconnects = 0
        while not done and reconnects < self.max_sse_reconnects:
            release_id = state.get("release_id")
            if release_id in (None, ""):
                break
            reconnects += 1
            done = self._stream_once(
                "GET",
                f"/apps/{_segment(slug)}/releases/{release_id}/events",
                state=state,
                params={"since_seq": max(int(state["last_seq"]), 0)},
                on_event=on_event,
            )
        if not done:
            raise AppHubHttpError(
                "APPHUB-SSE-INTERRUPTED",
                "发布事件流中断，自动续订后仍未收到终态。",
                fix_hint="重新执行同一条 app push；服务端会按 commit_sha 幂等续跑。",
                detail={
                    "release_id": state.get("release_id"),
                    "last_seq": state.get("last_seq"),
                },
            )
        return state

    def _stream_once(
        self,
        method: str,
        path: str,
        *,
        state: dict[str, Any],
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        on_event: EventCallback | None = None,
    ) -> bool:
        try:
            with self.http.stream(
                method,
                self._url(path),
                headers=self._headers(accept="text/event-stream", has_json=json is not None),
                params=params,
                json=json,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    self._raise_for_status(response)
                header_release_id = response.headers.get("X-Apphub-Release-Id")
                if header_release_id:
                    state["release_id"] = _numeric_or_text(header_release_id)
                for event in parse_sse_lines(response.iter_lines()):
                    seq = event.get("seq")
                    if isinstance(seq, int) and seq <= int(state["last_seq"]):
                        continue
                    if isinstance(seq, int):
                        state["last_seq"] = seq
                    if event.get("release_id") not in (None, ""):
                        state["release_id"] = _numeric_or_text(event["release_id"])
                    state["events"].append(event)
                    if on_event is not None:
                        on_event(event)
                    if event.get("status"):
                        state["terminal_event"] = event
                    if event.get("event") == "done":
                        return True
                return False
        except AppHubHttpError:
            raise
        except httpx.HTTPError as exc:
            if state.get("release_id") not in (None, ""):
                return False
            raise AppHubHttpError(
                "UPSTREAM_ERROR",
                "无法连接 AppHub 发布事件流。",
                fix_hint="稍后重试；重复 commit_sha 会幂等续跑。",
            ) from exc

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


def _numeric_or_text(value: Any) -> int | str:
    text = str(value)
    return int(text) if text.isdigit() else text


def _status_fix_hint(status: int) -> str | None:
    return {
        401: "请先执行 opscli auth login 重新登录。",
        403: "当前账号没有该应用权限，请联系应用 owner。",
        426: "当前 opscli 版本过低，请升级后重试。",
        502: "AppHub 上游暂不可用，请稍后幂等重试。",
        503: "AppHub 服务暂不可用，请稍后幂等重试。",
    }.get(status)
