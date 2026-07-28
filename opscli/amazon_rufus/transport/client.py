"""Amazon Rufus 远端传输客户端。"""

from __future__ import annotations

import httpx

from opscli.amazon_rufus.domain.exceptions import (
    RufusBadRemoteJsonError,
    RufusPlatformCookieAuthError,
    RufusRemoteBusinessError,
    RufusRemoteHttpError,
)
from opscli.auth import AuthClient
from opscli.auth.config import get_ops_url
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.http import parse_remote_response


# Rufus 上传接口 path 是后端固定契约，环境切换只覆盖 ops_url。
RUFUS_UPLOAD_ENDPOINT = "/v1/rufus/upload"
PLATFORM_COOKIE_ENDPOINT = "/v1/platform-cookies"


class RufusTransportClient:
    """封装 Rufus 结果上传能力。"""

    def __init__(self, auth_client: AuthClient | None = None, ops_url: str | None = None) -> None:
        self.auth_client = auth_client or AuthClient()
        self.ops_url = (ops_url or get_ops_url()).rstrip("/")

    def build_disabled_upload_hint(self) -> dict:
        """返回上传禁用说明。"""
        return {"enabled": False, "reason": "默认只构造 upload_payload；显式启用后才发送上传接口"}

    def submit_upload_payload(self, upload_payload: dict) -> dict:
        """提交 Rufus upload_payload 到 ops 后端。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = httpx.post(
            f"{self.ops_url}{RUFUS_UPLOAD_ENDPOINT}",
            json=upload_payload,
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return parse_remote_response(
            response,
            http_error_cls=RufusRemoteHttpError,
            business_error_cls=RufusRemoteBusinessError,
            bad_json_error_cls=RufusBadRemoteJsonError,
        )

    def save_platform_cookie(self, *, platform: str, country: str, content: str) -> dict:
        """保存或覆盖当前用户指定平台的 Cookie content。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = httpx.post(
            f"{self.ops_url}{PLATFORM_COOKIE_ENDPOINT}",
            json={
                "platform": platform,
                "country": country,
                "content": content,
            },
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return self._parse_platform_cookie_response(response)

    def get_platform_cookie(self, *, platform: str) -> dict:
        """读取当前用户指定平台保存的 Cookie content。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = httpx.get(
            f"{self.ops_url}{PLATFORM_COOKIE_ENDPOINT}",
            params={"platform": platform},
            headers=headers,
            cookies=cookies,
            timeout=180,
        )
        return self._parse_platform_cookie_response(response)

    def _parse_platform_cookie_response(self, response: httpx.Response) -> dict:
        """解析平台 Cookie 响应，并把 401 固定归类为 OPS 鉴权失败。"""
        try:
            return parse_remote_response(
                response,
                http_error_cls=RufusRemoteHttpError,
                business_error_cls=RufusRemoteBusinessError,
                bad_json_error_cls=RufusBadRemoteJsonError,
            )
        except RufusRemoteHttpError as exc:
            if exc.status_code == 401:
                # 平台 Cookie API 401 代表 OPS/MCP 鉴权失败，不代表亚马逊 Rufus 登录态缺失。
                raise RufusPlatformCookieAuthError(status_code=exc.status_code) from exc
            raise
