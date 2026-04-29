"""amazon 模块远端提交客户端。

当前阶段仅做 API 预留，默认不在 CLI 主流程中使用。
"""

from __future__ import annotations

import httpx

from opscli.amazon.domain.exceptions import BadRemoteJsonError, RemoteBusinessError, RemoteHttpError, SubmissionConfigError
from opscli.amazon.domain.models import AmazonProductSnapshot
from opscli.auth import AuthClient, OPS_URL
from opscli.auth.config import get_amazon_submit_endpoint
from opscli.shared.http import parse_remote_response


class AmazonOpsClient:
    """统一封装 Amazon 数据提交预留能力。"""

    def __init__(self, auth_client: AuthClient | None = None) -> None:
        self.auth_client = auth_client or AuthClient()
        self.ops_url = OPS_URL.rstrip("/")
        self.default_submit_endpoint = get_amazon_submit_endpoint()

    def submit_snapshot(self, snapshot: AmazonProductSnapshot, *, endpoint: str | None = None) -> dict:
        """将抓取结果提交到 ops。

        该能力已就绪，但本期默认仅保留作为接口预留。
        """
        submit_endpoint = (endpoint or self.default_submit_endpoint or "").strip()
        if not submit_endpoint:
            raise SubmissionConfigError(
                "未配置 Amazon 提交 endpoint，请在 config.ini 的 [systems] 段配置 amazon_submit_endpoint，或通过 --endpoint 指定"
            )
        if not submit_endpoint.startswith("/"):
            raise SubmissionConfigError("提交 endpoint 必须以 / 开头，并相对 OPS_URL 解析")

        headers, cookies = self.auth_client.build_request_auth("ops")
        response = httpx.post(
            f"{self.ops_url}{submit_endpoint}",
            json={
                "source": "opscli.amazon",
                "snapshot": snapshot.to_dict(include_raw=True),
            },
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
