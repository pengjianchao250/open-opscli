"""Scrape.do token 来源。"""

from __future__ import annotations

import time

from opscli.scrape_do.config import ScrapeDoSettings, load_settings
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError
from opscli.scrape_do.domain.models import ScrapeDoCredential
from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountClient, IntegrationAccountError

_REMOTE_BUNDLE_CACHE: dict[str, tuple[float, IntegrationAccountBundle]] = {}


class ScrapeDoCredentialProvider:
    """读取 Scrape.do token，优先远端集成账号，兜底环境变量。"""

    def __init__(
        self,
        settings: ScrapeDoSettings | None = None,
        integration_client: IntegrationAccountClient | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.integration_client = integration_client or IntegrationAccountClient()
        self._remote_bundle: IntegrationAccountBundle | None = None
        self._remote_error: IntegrationAccountError | None = None

    def get_default(self, *, refresh: bool = False) -> ScrapeDoCredential:
        credential = self._get_remote_default(refresh=refresh)
        if credential:
            return credential
        if self.settings.token:
            return ScrapeDoCredential(name=self.settings.account_name, token=self.settings.token, source="env")
        if self._remote_error:
            message = str(self._remote_error)
            if "暂不支持的平台" in message or "platform" in message.lower():
                raise ScrapeDoConfigError(
                    "OPS 集成账号接口暂不支持平台 scrape_do，请先在 OPS 后端开通 scrape_do 平台配置，"
                    "或临时设置 OPSCLI_SCRAPEDO_TOKEN。"
                )
            raise ScrapeDoConfigError(
                f"获取 Scrape.do 集成账号失败：{self._remote_error}。请检查 OPS 授权，或设置 OPSCLI_SCRAPEDO_TOKEN。"
            )
        raise ScrapeDoConfigError("缺少 Scrape.do token：请配置 OPS 集成账号 scrape_do，或设置 OPSCLI_SCRAPEDO_TOKEN")

    def _get_remote_default(self, *, refresh: bool = False) -> ScrapeDoCredential | None:
        bundle = self._load_remote_bundle(refresh=refresh)
        if not bundle or not bundle.accounts:
            return None
        default_name = bundle.default_account or self.settings.account_name
        for item in bundle.accounts:
            if item.name == default_name:
                return ScrapeDoCredential(name=item.name, token=item.password, source="integration_account")
        raise ScrapeDoConfigError(f"Scrape.do 集成账号中不存在默认账号：{default_name}")

    def _load_remote_bundle(self, *, refresh: bool = False) -> IntegrationAccountBundle | None:
        if not refresh and self._remote_bundle is not None:
            return self._remote_bundle
        cached = _REMOTE_BUNDLE_CACHE.get("scrape_do")
        if not refresh and cached and time.time() - cached[0] < self.settings.account_cache_ttl_seconds:
            self._remote_bundle = cached[1]
            self._remote_error = None
            return self._remote_bundle
        try:
            self._remote_bundle = self.integration_client.get_accounts("scrape_do")
            self._remote_error = None
            _REMOTE_BUNDLE_CACHE["scrape_do"] = (time.time(), self._remote_bundle)
        except IntegrationAccountError as exc:
            self._remote_error = exc
            self._remote_bundle = None
        return self._remote_bundle
