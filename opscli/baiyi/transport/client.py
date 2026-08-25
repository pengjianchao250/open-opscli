"""通过运营系统读取佰易产品信息。"""

from __future__ import annotations

import httpx

from opscli.auth import AuthClient
from opscli.auth.config import load_config
from opscli.baiyi.domain.exceptions import (
    BaiyiProductInfoBadJsonError,
    BaiyiProductInfoBusinessError,
    BaiyiProductInfoHttpError,
    BaiyiProductInfoNetworkError,
)
from opscli.shared.http import parse_remote_response


PRODUCT_INFO_ENDPOINT = "/dataMetrics/v1/binding-sku-product-info"


class BaiyiProductInfoClient:
    """封装佰易产品信息接口的认证、请求和错误映射。"""

    def __init__(self, auth_client: AuthClient | None = None) -> None:
        """构造客户端并读取当前环境的 OPS 服务地址。"""
        self.auth_client = auth_client or AuthClient()
        self.base_url = str(load_config()["ops_system_url"]).rstrip("/")

    def fetch_product_info(self, payload: dict) -> dict:
        """按公司 SKU 请求产品信息，并返回已校验的 JSON 对象。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        try:
            response = httpx.post(
                f"{self.base_url}{PRODUCT_INFO_ENDPOINT}",
                json=payload,
                headers=headers,
                cookies=cookies,
                timeout=10,
            )
        except httpx.TimeoutException as exc:
            raise BaiyiProductInfoNetworkError("佰易产品信息服务请求超时") from exc
        except httpx.RequestError as exc:
            raise BaiyiProductInfoNetworkError("无法连接佰易产品信息服务") from exc

        # 共享解析器优先解析 JSON；先兜住 HTML/空正文错误页，避免把 404 误报为 JSON 错误。
        if response.status_code >= 400:
            try:
                response.json()
            except Exception as exc:
                raise BaiyiProductInfoHttpError(
                    response.status_code,
                    f"远端请求失败，HTTP {response.status_code}",
                ) from exc

        return parse_remote_response(
            response,
            http_error_cls=BaiyiProductInfoHttpError,
            business_error_cls=BaiyiProductInfoBusinessError,
            bad_json_error_cls=BaiyiProductInfoBadJsonError,
        )
