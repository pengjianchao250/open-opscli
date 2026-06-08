"""Rufus 后端请求凭证服务。

该模块只负责在服务层内部读取 Rufus 请求所需的敏感状态，禁止把 cookie、
headers 或 payload_template 暴露到 MCP 返回、报告或 feedback 中。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from opscli.amazon_rufus.domain.exceptions import RufusSecretNotReadyError
from opscli.amazon_rufus.domain.models import SeedRequestRecord
from opscli.amazon_rufus.runtime.country_map import resolve_marketplace
from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore


@dataclass(frozen=True)
class RufusSecret:
    """Rufus 后端请求凭证。"""

    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: str = ""
    payload_template: dict[str, Any] | None = None
    storage_state: dict | None = None
    seed_request: SeedRequestRecord | None = None
    curl_data: dict[str, Any] | None = None


class RufusBackendSecretProvider:
    """读取 Rufus 后端请求凭证。"""

    def __init__(self, *, browser_state_store: RufusBrowserStateStore | None = None) -> None:
        """初始化 provider。

        Args:
            browser_state_store: 浏览器状态存储；测试可注入 fake store。
        """
        self.browser_state_store = browser_state_store or RufusBrowserStateStore()

    def load(self, *, country: str) -> RufusSecret:
        """读取指定国家站点可用的 Rufus 请求凭证。"""
        normalized_country = country.strip().upper()
        marketplace = resolve_marketplace(normalized_country)
        record = self.browser_state_store.load(normalized_country)
        if not isinstance(record, dict):
            raise RufusSecretNotReadyError("未找到可用 Rufus 后端凭证，请先完成 Rufus 授权状态初始化。")

        curl_data = self._normalize_curl_data(record.get("curl_data"))
        storage_state = record.get("storage_state")
        if not isinstance(storage_state, dict) and curl_data is None:
            raise RufusSecretNotReadyError("Rufus 后端凭证缺少有效 storage_state，请重新完成授权状态初始化。")

        cookies = self._resolve_cookies(curl_data=curl_data, storage_state=storage_state, marketplace_url=marketplace.base_url)
        headers = curl_data.get("headers") if curl_data else record.get("headers")
        payload_template = curl_data.get("payload_template") if curl_data else record.get("payload_template")
        url = str(
            (curl_data.get("url") if curl_data else "")
            or record.get("url")
            or record.get("streaming_url")
            or ""
        ).strip()
        return RufusSecret(
            url=url,
            headers={str(k): str(v) for k, v in headers.items()} if isinstance(headers, dict) else {},
            cookies=cookies,
            payload_template=payload_template if isinstance(payload_template, dict) else None,
            storage_state=storage_state if isinstance(storage_state, dict) else None,
            seed_request=self._load_seed_request(record),
            curl_data=curl_data,
        )

    def _load_seed_request(self, record: dict[str, Any]) -> SeedRequestRecord | None:
        """从本地状态中还原可复用的 streaming seed。"""
        seed = record.get("seed_request")
        curl_data = self._normalize_curl_data(record.get("curl_data"))
        payload_template = curl_data.get("payload_template") if curl_data else record.get("payload_template")
        if not isinstance(seed, dict) or not isinstance(payload_template, dict):
            return None
        request_url = str(seed.get("request_url") or (curl_data.get("url") if curl_data else "") or record.get("streaming_url") or "").strip()
        if "/rufus/cl/streaming" not in request_url:
            return None
        headers = curl_data.get("headers") if curl_data else record.get("headers")
        return SeedRequestRecord(
            request_url=request_url,
            request_headers={str(k): str(v) for k, v in (headers or {}).items()}
            if isinstance(headers, dict)
            else {},
            request_body=self._safe_json_dump(payload_template),
            page_url=str(seed.get("page_url") or ""),
            tab_id=str(seed.get("tab_id") or ""),
            asin=str(seed.get("asin") or "").strip().upper(),
            country=str(seed.get("country") or "").strip().upper(),
            captured_at=int(seed.get("captured_at") or 0),
        )

    def _safe_json_dump(self, value: dict[str, Any]) -> str:
        """把 payload template 还原为 seed body 文本。"""
        return json.dumps(value, ensure_ascii=False)

    def _normalize_curl_data(self, value: Any) -> dict[str, Any] | None:
        """校验并规范化本地保存的 curl 数据。"""
        if not isinstance(value, dict):
            return None
        url = str(value.get("url") or "").strip()
        headers = value.get("headers")
        cookies = str(value.get("cookies") or "").strip()
        payload_template = value.get("payload_template")
        if not url or not isinstance(headers, dict) or not cookies or not isinstance(payload_template, dict):
            return None
        return {
            "url": url,
            "headers": {str(k): str(v) for k, v in headers.items()},
            "cookies": cookies,
            "payload_template": payload_template,
        }

    def _resolve_cookies(self, *, curl_data: dict[str, Any] | None, storage_state: Any, marketplace_url: str) -> str:
        """优先使用本地 curl_data.cookies，旧结构回退从 storage_state 派生。"""
        if curl_data is not None:
            return str(curl_data.get("cookies") or "").strip()
        if isinstance(storage_state, dict):
            return self.browser_state_store.build_cookie_header(storage_state, marketplace_url)
        raise RufusSecretNotReadyError("Rufus 后端凭证缺少有效 cookies，请重新完成授权状态初始化。")
