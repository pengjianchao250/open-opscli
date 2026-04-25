"""query 模块远端请求客户端。"""

from __future__ import annotations

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.query.domain.exceptions import BadRemoteJsonError, RemoteBusinessError, RemoteHttpError


class QueryClient:
    """统一封装 query 模块的远端请求。

    支持无状态模式：通过外部传入的 jwt 和 session_id 构造请求头，
    不依赖本地 CredentialStore。适用于远程共享 MCP 服务器场景。
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
        """获取请求认证头。优先使用外部传入的凭证，否则回退到本地存储。

        无状态模式下：只要有 session_id，就优先使用它；如果 jwt 缺失，
        自动用 session_id 向后端换取，不依赖本地 CredentialStore。
        """
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                # 无状态模式：用 session_id 实时向后端换取 JWT
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            cookies = {"polarisUserToken": self.session_id}
            return headers, cookies
        return self.auth_client.build_request_auth(alias)

    def fetch_chart_queries(self, chart_uuid: str) -> list[dict]:
        """通过 chart_uuid 获取图表的查询结构列表。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/data-metrics/cli-query/latest-request-data",
            params={"chart_uuid": chart_uuid},
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        payload = self._parse_response(response)
        data = payload.get("data")
        if not isinstance(data, list):
            raise BadRemoteJsonError("远端返回的 chart query 数据结构不是数组")
        return data

    def cli_query(self, payload: dict) -> dict:
        """转发查询请求到 auto-scheduler 的 cli-query 接口。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.post(
            f"{self.ops_url}/v1/data-metrics/cli-query",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=30,
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
