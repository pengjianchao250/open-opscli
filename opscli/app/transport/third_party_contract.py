"""AppHub 建站第三方 REST 场景合同客户端。"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import httpx

from opscli.app.domain.exceptions import AppThirdPartyContractError
from opscli.auth import AuthClient

THIRD_PARTY_DATA_API_BASE_URL_ENV = "OPSCLI_THIRD_PARTY_DATA_API_BASE_URL"

_SCENARIO_ENDPOINTS = {
    "keepa": "/api/v1/keepa/scenarios",
    "seller-sprite": "/api/v1/seller-sprite/scenarios",
}


class ThirdPartyContractClient:
    """通过正式 REST API 验证 AppHub 第三方场景合同。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_client: AuthClient | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        configured_base_url = base_url or os.getenv(THIRD_PARTY_DATA_API_BASE_URL_ENV)
        self.base_url = _normalize_origin(configured_base_url)
        self.auth_client = auth_client
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def scenarios(self, provider: str) -> dict[str, Any]:
        normalized_provider = provider.strip().lower()
        endpoint = _SCENARIO_ENDPOINTS.get(normalized_provider)
        if endpoint is None:
            supported = ", ".join(_SCENARIO_ENDPOINTS)
            raise AppThirdPartyContractError(
                "APP-THIRD-PARTY-PROVIDER",
                f"不支持的第三方数据源：{provider}",
                fix_hint=f"provider 只能是：{supported}",
            )

        payload = self._request_json("GET", endpoint)
        scenarios = payload.get("data")
        if not isinstance(scenarios, list):
            raise AppThirdPartyContractError(
                "APP-THIRD-PARTY-PROTOCOL",
                "第三方场景接口 data 必须是数组。",
                fix_hint="检查当前环境的第三方 REST 服务版本和场景接口合同。",
            )

        return {
            "provider": normalized_provider,
            "transport": "rest",
            "auth_mode": "local-session",
            "endpoint": endpoint,
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
        }

    def _request_json(self, method: str, path: str) -> dict[str, Any]:
        try:
            request = self.http.build_request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
            )
            request.headers.pop("Cookie", None)
            response = self.http.send(request)
        except AppThirdPartyContractError:
            raise
        except httpx.HTTPError as exc:
            raise AppThirdPartyContractError(
                "APP-THIRD-PARTY-UPSTREAM",
                "无法连接第三方数据 REST 服务。",
                fix_hint=(
                    f"检查 {THIRD_PARTY_DATA_API_BASE_URL_ENV}、网络和当前环境服务状态。"
                ),
            ) from exc

        payload = _response_json(response)
        if response.status_code >= 400:
            _raise_response_error(response, payload)
        if payload.get("success") is False:
            _raise_business_error(payload)
        return payload

    def _headers(self) -> dict[str, str]:
        if self.auth_client is None:
            self.auth_client = AuthClient()
        try:
            session_headers = self.auth_client.build_session_headers("ops")
            request_headers, _cookies = self.auth_client.build_request_auth("ops")
        except Exception as exc:
            raise AppThirdPartyContractError(
                "APP-THIRD-PARTY-AUTH",
                "无法从当前 opscli 登录态构造第三方 REST 鉴权头。",
                fix_hint="请先执行 opscli auth login，再重试建站第三方合同验证。",
                detail={"error_type": type(exc).__name__},
            ) from exc

        session_id = session_headers.get("X-Session-Id")
        if not session_id:
            raise AppThirdPartyContractError(
                "APP-THIRD-PARTY-AUTH",
                "当前登录态缺少 X-Session-Id。",
                fix_hint="请先执行 opscli auth login，再重试建站第三方合同验证。",
            )

        headers = {
            "Accept": "application/json",
            "X-Session-Id": session_id,
        }
        authorization = request_headers.get("Authorization")
        if authorization:
            headers["Authorization"] = authorization
        return headers


def _normalize_origin(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise AppThirdPartyContractError(
            "APP-THIRD-PARTY-CONFIG",
            f"缺少 {THIRD_PARTY_DATA_API_BASE_URL_ENV}。",
            fix_hint="由当前生产或预发布环境显式注入第三方数据服务纯根域名。",
        )

    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AppThirdPartyContractError(
            "APP-THIRD-PARTY-CONFIG",
            f"{THIRD_PARTY_DATA_API_BASE_URL_ENV} 必须是 http/https 纯 origin。",
            fix_hint="移除接口路径、查询参数、片段、用户名、密码和末尾多余内容。",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppThirdPartyContractError(
            "APP-THIRD-PARTY-PROTOCOL",
            "第三方场景接口返回了无效 JSON。",
            fix_hint="检查当前环境的第三方 REST 服务版本和响应合同。",
        ) from exc
    if not isinstance(payload, dict):
        raise AppThirdPartyContractError(
            "APP-THIRD-PARTY-PROTOCOL",
            "第三方场景接口 JSON 响应必须是对象。",
            fix_hint="检查当前环境的第三方 REST 服务版本和响应合同。",
        )
    return payload


def _raise_response_error(response: httpx.Response, payload: dict[str, Any]) -> None:
    error = payload.get("error")
    error_payload = error if isinstance(error, dict) else payload
    status = response.status_code
    raise AppThirdPartyContractError(
        str(error_payload.get("code") or payload.get("code") or f"HTTP-{status}"),
        str(
            error_payload.get("message")
            or payload.get("msg")
            or f"第三方场景接口请求失败（HTTP {status}）。"
        ),
        fix_hint=_status_fix_hint(status),
        request_id=response.headers.get("X-Request-Id"),
    )


def _raise_business_error(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    error_payload = error if isinstance(error, dict) else {}
    raise AppThirdPartyContractError(
        str(error_payload.get("code") or payload.get("code") or "UPSTREAM_ERROR"),
        str(
            error_payload.get("message")
            or payload.get("msg")
            or "第三方场景接口返回业务失败。"
        ),
        fix_hint="检查当前用户权限、第三方场景服务状态和响应合同。",
    )


def _status_fix_hint(status: int) -> str:
    return {
        401: "请先执行 opscli auth login 重新登录。",
        403: "当前用户无第三方场景访问权限，请联系服务管理员。",
        404: "当前环境未部署对应的第三方 REST 场景接口。",
    }.get(status, "检查第三方 REST 服务状态后重试；不要回退 MCP。")
