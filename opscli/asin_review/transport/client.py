"""asin_review 模块远端请求客户端。

通过运营系统 POST /api/v1/asin-review/query 接口获取复盘数据。
复用 opscli 现有的鉴权机制（AuthClient + JWT Bearer）。
"""

from __future__ import annotations

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.asin_review.domain.exceptions import (
    ReviewBadJsonError,
    ReviewBusinessError,
    ReviewHttpError,
)
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.http import parse_remote_response


class AsinReviewClient:
    """复盘数据远端请求客户端。

    支持无状态模式：通过外部传入 jwt/session_id 构造请求头，
    不依赖本地 CredentialStore。
    """

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.jwt = jwt
        self.session_id = session_id
        self.ops_url = OPS_URL.rstrip("/")

    def _get_auth(self, alias: str = "ops") -> tuple[dict[str, str], dict[str, str]]:
        """获取请求认证头。优先使用外部传入的凭证，否则回退到本地存储。"""
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                # 无状态模式：用 session_id 实时向后端换取 JWT
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            headers.update(get_mcp_request_headers())
            cookies = {"polarisUserToken": self.session_id}
            return headers, cookies
        headers, cookies = self.auth_client.build_request_auth(alias)
        headers.update(get_mcp_request_headers())
        return headers, cookies

    def fetch_review(self, payload: dict) -> dict:
        """调用运营系统复盘查询接口。

        Args:
            payload: 请求体，格式如 {"asins": [...], "date_start": "...", "date_end": "..."}

        Returns:
            后端返回的 JSON 数据（已通过 parse_remote_response 校验）

        Raises:
            ReviewHttpError: HTTP 层错误
            ReviewBusinessError: 业务层错误
            ReviewBadJsonError: JSON 解析失败
        """
        headers, cookies = self._get_auth("ops")
        response = httpx.post(
            f"{self.ops_url}/v1/asin-review/query",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=30,
        )
        return parse_remote_response(
            response,
            http_error_cls=ReviewHttpError,
            business_error_cls=ReviewBusinessError,
            bad_json_error_cls=ReviewBadJsonError,
        )
