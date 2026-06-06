"""Rufus 后端请求凭证服务。

该模块只负责在服务层内部读取 Rufus 请求所需的敏感状态，禁止把 cookie、
headers 或 payload_template 暴露到 MCP 返回、报告或 feedback 中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opscli.amazon_rufus.domain.exceptions import RufusSecretNotReadyError
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

        storage_state = record.get("storage_state")
        if not isinstance(storage_state, dict):
            raise RufusSecretNotReadyError("Rufus 后端凭证缺少有效 storage_state，请重新完成授权状态初始化。")

        # 默认从已加密保存的 Playwright storage_state 派生 cookie，避免 MCP 入参暴露敏感信息。
        cookies = self.browser_state_store.build_cookie_header(storage_state, marketplace.base_url)
        headers = record.get("headers")
        payload_template = record.get("payload_template")
        url = str(record.get("url") or record.get("streaming_url") or "").strip()
        return RufusSecret(
            url=url,
            headers={str(k): str(v) for k, v in headers.items()} if isinstance(headers, dict) else {},
            cookies=cookies,
            payload_template=payload_template if isinstance(payload_template, dict) else None,
            storage_state=storage_state,
        )
