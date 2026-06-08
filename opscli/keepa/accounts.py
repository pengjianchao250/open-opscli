"""Keepa API Key 来源。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from opscli.keepa.config import KeepaSettings, load_settings
from opscli.keepa.domain.exceptions import KeepaConfigError
from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountClient, IntegrationAccountError


_REMOTE_BUNDLE_CACHE: dict[str, tuple[float, IntegrationAccountBundle]] = {}


@dataclass(frozen=True)
class KeepaApiKey:
    """Keepa API Key 记录。"""

    name: str
    api_key: str
    source: str

    def to_public_dict(self) -> dict[str, Any]:
        """返回不暴露完整 key 的摘要。"""
        return {
            "name": self.name,
            "source": self.source,
            "has_api_key": bool(self.api_key),
        }


class KeepaApiKeyProvider:
    """读取 Keepa API Key，优先远端集成账号，兜底环境变量。"""

    def __init__(
        self,
        settings: KeepaSettings | None = None,
        integration_client: IntegrationAccountClient | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.integration_client = integration_client or IntegrationAccountClient()
        self._remote_bundle: IntegrationAccountBundle | None = None
        self._remote_error: IntegrationAccountError | None = None

    def get_default(self, *, refresh: bool = False) -> KeepaApiKey:
        """读取默认 Keepa API Key。"""
        api_key = self._get_remote_default(refresh=refresh)
        if api_key:
            return api_key

        if self.settings.api_key:
            return KeepaApiKey(
                name=self.settings.account_name,
                api_key=self.settings.api_key,
                source="env",
            )

        if self._remote_error:
            raise KeepaConfigError(
                f"获取 Keepa 集成账号失败：{self._remote_error}。"
                "请检查 OPS 授权，或设置 OPSCLI_KEEPA_API_KEY。"
            )
        raise KeepaConfigError("缺少 Keepa API Key：请配置 OPS 集成账号 keepa，或设置 OPSCLI_KEEPA_API_KEY")

    def _get_remote_default(self, *, refresh: bool = False) -> KeepaApiKey | None:
        bundle = self._load_remote_bundle(refresh=refresh)
        if not bundle or not bundle.accounts:
            return None

        default_name = bundle.default_account or self.settings.account_name
        for item in bundle.accounts:
            if item.name == default_name:
                return KeepaApiKey(name=item.name, api_key=item.password, source="integration_account")

        raise KeepaConfigError(f"Keepa 集成账号中不存在默认账号：{default_name}")

    def _load_remote_bundle(self, *, refresh: bool = False) -> IntegrationAccountBundle | None:
        if not refresh and self._remote_bundle is not None:
            return self._remote_bundle
        cached = _REMOTE_BUNDLE_CACHE.get("keepa")
        if not refresh and cached and time.time() - cached[0] < self.settings.account_cache_ttl_seconds:
            self._remote_bundle = cached[1]
            self._remote_error = None
            return self._remote_bundle
        try:
            self._remote_bundle = self.integration_client.get_accounts("keepa")
            self._remote_error = None
            _REMOTE_BUNDLE_CACHE["keepa"] = (time.time(), self._remote_bundle)
        except IntegrationAccountError as exc:
            self._remote_error = exc
            self._remote_bundle = None
        return self._remote_bundle
