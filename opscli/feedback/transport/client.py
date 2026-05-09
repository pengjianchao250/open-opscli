"""feedback 模块远端请求客户端。"""

from __future__ import annotations

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.feedback.domain.exceptions import BadRemoteJsonError, RemoteBusinessError, RemoteHttpError
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.http import parse_remote_response


class FeedbackClient:
    """统一封装 feedback 模块的远端请求。"""

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
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            headers.update(get_mcp_request_headers())
            return headers, {"polarisUserToken": self.session_id}
        headers, cookies = self.auth_client.build_request_auth(alias)
        headers.update(get_mcp_request_headers())
        return headers, cookies

    def submit(self, payload: dict) -> dict:
        """提交用户反馈。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.post(
            f"{self.ops_url}/v1/data-metrics/feedback",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        return parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )

    def detail(self, feedback_uuid: str) -> dict:
        """按 feedback_uuid 查询当前用户的反馈详情。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/data-metrics/feedback/{feedback_uuid}",
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        return parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
