"""通用工单远端请求客户端。

封装北极星工单系统的 HTTP 接口：
- POST /feedTask/customTaskManage/createCustomTask  创建工单
- POST /feedTask/taskManage/detail                  查询工单详情
"""

from __future__ import annotations

import time

import httpx

from opscli.auth import AuthClient
from opscli.auth.config import load_config
from opscli.feedtask.domain.exceptions import (
    BadRemoteJsonError,
    RemoteBusinessError,
    RemoteHttpError,
)


class FeedTaskClient:
    """北极星工单系统通用 API 客户端。

    职责单一：提交 createCustomTask 请求 + 查询工单详情。
    不关心 payload 内容（由调用方构造）。

    复用 polaris 系统认证（与 QueryClient 同模式）：
    - CLI 模式：AuthClient.build_request_auth("polaris") 从本地存储读取凭证
    - MCP 模式：通过 session_id + jwt 无状态认证
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
        self._base_url = load_config()["polaris_system_url"].rstrip("/")

    def _get_auth(self) -> tuple[dict[str, str], dict[str, str]]:
        """获取 polaris 认证头。

        优先使用外部传入的凭证，否则回退到本地存储。
        """
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                # 无状态模式：用 session_id 实时向后端换取 JWT
                jwt = self.auth_client.get_token_by_session(self.session_id, "polaris")
            headers = {"Authorization": f"Bearer {jwt}"}
            cookies = {"polarisUserToken": self.session_id}
            return headers, cookies
        return self.auth_client.build_request_auth("polaris")

    def create(self, payload: dict) -> dict:
        """创建工单（通用入口）。

        Args:
            payload: 完整的 createCustomTask 请求体（由调用方构造）
        """
        headers, cookies = self._get_auth()
        response = httpx.post(
            f"{self._base_url}/feedTask/customTaskManage/createCustomTask",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=30,
        )
        return self._parse_response(response)

    def get_detail(self, task_id: str) -> dict:
        """查询工单详情。

        POST {base_url}/feedTask/taskManage/detail
        请求体：{"id": "<task_id>", "_t": <timestamp>}
        """
        headers, cookies = self._get_auth()
        response = httpx.post(
            f"{self._base_url}/feedTask/taskManage/detail",
            json={"id": str(task_id), "_t": int(time.time())},
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict:
        """统一解析 HTTP 响应，识别业务层错误。"""
        try:
            payload = response.json()
        except Exception as exc:
            raise BadRemoteJsonError("远端返回了无法解析的 JSON") from exc

        if response.status_code >= 400:
            message = self._extract_message(payload) or f"远端请求失败，HTTP {response.status_code}"
            raise RemoteHttpError(response.status_code, message)

        if isinstance(payload, dict):
            business_code = payload.get("code")
            if business_code not in (None, 0, 200):
                message = self._extract_message(payload) or "远端业务执行失败"
                raise RemoteBusinessError(business_code, message)

        if not isinstance(payload, dict):
            raise BadRemoteJsonError("远端返回结构不是 JSON 对象")

        return payload

    def _extract_message(self, payload: dict) -> str | None:
        """从远端返回中提取最有价值的错误信息。"""
        for key in ("msg", "message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
