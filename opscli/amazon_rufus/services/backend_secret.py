"""Rufus 后端请求凭证服务。

该模块只负责在服务层内部读取 Rufus 请求所需的敏感状态，禁止把 cookie、
headers 或 payload_template 暴露到 MCP 返回、报告或 feedback 中。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from opscli.amazon_rufus.domain.exceptions import InvalidRufusCurlError, RufusSecretNotReadyError
from opscli.amazon_rufus.domain.models import SeedRequestRecord
from opscli.amazon_rufus.runtime.country_map import build_product_url, resolve_marketplace
from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore
from opscli.amazon_rufus.services.curl_parser import RufusCurlParser
from opscli.amazon_rufus.transport.client import RufusTransportClient


@dataclass(frozen=True)
class RufusSecret:
    """Rufus 后端请求凭证。"""

    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: str = ""
    payload_template: dict[str, Any] | None = None
    storage_state: dict | None = None
    seed_request: SeedRequestRecord | None = None
    curl: str = ""


class RufusBackendSecretProvider:
    """读取 Rufus 后端请求凭证。"""

    def __init__(
        self,
        *,
        browser_state_store: RufusBrowserStateStore | None = None,
        platform_cookie_client=None,
        curl_parser: RufusCurlParser | None = None,
    ) -> None:
        """初始化 provider。

        Args:
            browser_state_store: 浏览器状态存储；测试可注入 fake store。
            platform_cookie_client: 独立实例化 provider 时使用的线上 Cookie client。
            curl_parser: cURL 命令解析器；测试可注入 fake parser。
        """
        self.browser_state_store = browser_state_store or RufusBrowserStateStore(
            platform_cookie_client=platform_cookie_client or RufusTransportClient(),
        )
        self.curl_parser = curl_parser or RufusCurlParser()

    def load(self, *, country: str) -> RufusSecret:
        """读取指定国家站点可用的 Rufus 请求凭证。"""
        normalized_country = country.strip().upper()
        resolve_marketplace(normalized_country)
        record = self.browser_state_store.load(normalized_country)
        if not isinstance(record, dict):
            raise RufusSecretNotReadyError("未找到可用 Rufus 后端凭证，请先完成 Rufus 授权状态初始化。")

        raw_curl = self._normalize_curl(record.get("curl"))
        parsed = self._parse_curl(raw_curl)
        return RufusSecret(
            url=parsed.url,
            headers=parsed.headers,
            cookies=parsed.cookies,
            payload_template=parsed.payload_template,
            storage_state=None,
            seed_request=self._load_seed_request(record, parsed, country=normalized_country),
            curl=raw_curl,
        )

    def _load_seed_request(self, record: dict[str, Any], parsed: Any, *, country: str) -> SeedRequestRecord | None:
        """从本地状态中还原可复用的 streaming seed。"""
        seed = record.get("seed_request")
        if not isinstance(seed, dict) or not isinstance(parsed.payload_template, dict):
            return self._build_seed_request_from_curl(parsed, country=country)
        request_url = str(seed.get("request_url") or parsed.url or "").strip()
        if "/rufus/cl/streaming" not in request_url:
            return None
        return SeedRequestRecord(
            request_url=request_url,
            request_headers={str(k): str(v) for k, v in parsed.headers.items()},
            request_body=self._safe_json_dump(parsed.payload_template),
            page_url=str(seed.get("page_url") or ""),
            tab_id=str(seed.get("tab_id") or ""),
            asin=str(seed.get("asin") or "").strip().upper(),
            country=str(seed.get("country") or "").strip().upper(),
            captured_at=int(seed.get("captured_at") or 0),
        )

    def _build_seed_request_from_curl(self, parsed: Any, *, country: str) -> SeedRequestRecord | None:
        """从裸 cURL content 合成内部 seed，避免远端格式依赖 JSON 摘要。"""
        if "/rufus/cl/streaming" not in str(parsed.url or "") or not isinstance(parsed.payload_template, dict):
            return None
        asin = self._extract_asin(parsed.payload_template)
        page_url = self._extract_page_url(parsed.payload_template)
        if not page_url and asin:
            page_url = build_product_url(asin, country)
        return SeedRequestRecord(
            request_url=str(parsed.url or "").strip(),
            request_headers={str(k): str(v) for k, v in parsed.headers.items()},
            request_body=self._safe_json_dump(parsed.payload_template),
            page_url=page_url,
            tab_id=self._extract_tab_id(str(parsed.url or "")),
            asin=asin,
            country=country,
            captured_at=0,
        )

    def _safe_json_dump(self, value: dict[str, Any]) -> str:
        """把 payload template 还原为 seed body 文本。"""
        return json.dumps(value, ensure_ascii=False)

    def _extract_tab_id(self, request_url: str) -> str:
        """从 streaming URL 中提取 tabId。"""
        values = parse_qs(urlsplit(str(request_url or "").strip()).query).get("tabId")
        return str(values[0]).strip() if values else ""

    def _extract_page_url(self, payload_template: dict[str, Any]) -> str:
        """从 Rufus payload template 中提取商品页 URL。"""
        page_context = payload_template.get("pageContext") if isinstance(payload_template, dict) else None
        if not isinstance(page_context, dict):
            return ""
        for key in ("targetUrl", "originUrl"):
            value = str(page_context.get(key) or "").strip()
            if value:
                return value
        return ""

    def _extract_asin(self, payload_template: dict[str, Any]) -> str:
        """从 Rufus payload template 的页面上下文提取 ASIN。"""
        page_context = payload_template.get("pageContext") if isinstance(payload_template, dict) else None
        if not isinstance(page_context, dict):
            return ""
        for key in ("targetPageMetadata", "pageMetadata", "originPageMetadata"):
            items = page_context.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "").strip().upper() == "ASIN":
                    asin = str(item.get("value") or "").strip().upper()
                    if asin:
                        return asin
        for key in ("targetUrl", "originUrl"):
            matched = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)", str(page_context.get(key) or ""), re.I)
            if matched:
                return matched.group(1).upper()
        return ""

    def _normalize_curl(self, value: Any) -> str:
        """读取并校验新结构 cURL 命令。"""
        raw_curl = str(value or "").strip()
        if not raw_curl:
            raise RufusSecretNotReadyError("Rufus 后端凭证缺少 curl 命令，请重新完成授权状态初始化。")
        if not raw_curl.lower().startswith("curl "):
            raise RufusSecretNotReadyError("Rufus 后端凭证 curl 命令格式无效，请重新完成授权状态初始化。")
        return raw_curl

    def _parse_curl(self, raw_curl: str) -> Any:
        """解析 cURL 命令并统一映射为后端凭证错误。"""
        try:
            return self.curl_parser.parse(raw_curl)
        except InvalidRufusCurlError as exc:
            raise RufusSecretNotReadyError("Rufus 后端凭证 curl 命令不可用，请重新完成授权状态初始化。") from exc
