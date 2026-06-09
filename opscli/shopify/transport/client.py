"""Shopify 刊登查询客户端。

只负责查询（店铺/商品），工单提交委托给 FeedTaskClient。
复用 polaris 系统认证（与 QueryClient 同模式）。
"""

from __future__ import annotations

import time

import httpx

from opscli.auth import AuthClient
from opscli.auth.config import load_config
from opscli.config import get_platform_id
from opscli.feedtask.domain.exceptions import (
    BadRemoteJsonError,
    RemoteBusinessError,
    RemoteHttpError,
)


class ShopifyClient:
    """北极星 Shopify 刊登查询客户端。

    封装两个查询接口：
    - POST /feedTaskTemplate/customSource/getSourceChannels  获取店铺列表
    - GET  /shopify/listing/list                              获取商品列表
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
        """获取 polaris 认证头。"""
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                jwt = self.auth_client.get_token_by_session(self.session_id, "polaris")
            headers = {"Authorization": f"Bearer {jwt}"}
            cookies = {"polarisUserToken": self.session_id}
            return headers, cookies
        return self.auth_client.build_request_auth("polaris")

    def list_shops(self, platform: int | None = None) -> list[dict]:
        """获取用户有权限的店铺列表。

        POST {base_url}/feedTaskTemplate/customSource/getSourceChannels

        Args:
            platform: 平台标识，不传则从配置文件读取 shopify 的 platform ID
        """
        if platform is None:
            platform = get_platform_id("shopify")
        headers, cookies = self._get_auth()
        url = f"{self._base_url}/feedTaskTemplate/customSource/getSourceChannels"
        body = {"platform": platform, "_t": int(time.time())}
        response = httpx.post(
            url,
            json=body,
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        payload = self._parse_response(response)
        data = payload.get("data")
        # 响应结构：data.options = [{"value": site_id, "label": "店铺名"}, ...]
        if isinstance(data, dict):
            options = data.get("options") or data.get("list") or []
            if isinstance(options, list):
                return options
        if isinstance(data, list):
            return data
        return []

    def search_listings(
        self,
        sellsku: str | None = None,
        channel_id: int | None = None,
        sku: str | None = None,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        """通过 seller_sku 或平台 SKU 搜索商品。

        GET {base_url}/api/listing/list

        与 list_products 不同，此接口支持按 seller_sku 精确搜索，
        返回结果包含 site_id 等工单所需字段。

        Args:
            sellsku:    卖家自定义 SKU（如 QD74024-4）
            channel_id: 渠道 ID（站点 ID），不传则搜索所有渠道
            sku:        平台 SKU
            page:       分页页码（默认 1）
            limit:      每页条数（默认 20）
        """
        headers, cookies = self._get_auth()
        params: dict = {
            "page": page,
            "limit": limit,
            "_t": int(time.time()),
        }
        if sellsku:
            params["sellsku"] = sellsku
        if sku:
            params["sku"] = sku
        if channel_id is not None:
            # 接口要求 channel[] 数组参数格式
            params["channel[]"] = channel_id

        response = httpx.get(
            f"{self._base_url}/api/listing/list",
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=10,
        )
        return self._parse_response(response)

    def list_products(
        self,
        site_id: int | None = None,
        *,
        page: int = 1,
        limit: int = 20,
        keyword: str | None = None,
        abnormal_state: int = 1,
        view_type: str = "parent",
    ) -> dict:
        """获取商品列表。

        GET {base_url}/shopify/listing/list

        Args:
            site_id:        站点 ID（不传则查询所有）
            page:           分页页码（默认 1）
            limit:          每页条数（默认 20）
            keyword:        关键词搜索
            abnormal_state: 异常状态过滤（1 = 正常）
            view_type:      视图类型（parent = 父商品维度）
        """
        headers, cookies = self._get_auth()
        params: dict = {
            "abnormal_state": abnormal_state,
            "page": page,
            "limit": limit,
            "view_type": view_type,
            "_t": int(time.time()),
        }
        if site_id is not None:
            params["site_id"] = site_id
        if keyword:
            params["keyword"] = keyword

        response = httpx.get(
            f"{self._base_url}/shopify/listing/list",
            params=params,
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
