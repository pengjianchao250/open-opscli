"""Amazon Rufus 远端传输客户端。"""

from __future__ import annotations

import httpx

from opscli.amazon_rufus.domain.exceptions import (
    RufusBadRemoteJsonError,
    RufusRemoteBusinessError,
    RufusRemoteHttpError,
)
from opscli.auth import AuthClient
from opscli.auth.config import get_ops_url
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.http import parse_remote_response


# Rufus 上传接口 path 是后端固定契约，环境切换只覆盖 ops_url。
RUFUS_UPLOAD_ENDPOINT = "/v1/rufus/upload"


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
