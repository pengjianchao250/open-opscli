"""Sif account sources."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountClient
from opscli.sif.config import SifSettings, load_settings
from opscli.sif.domain.exceptions import SifConfigError


DEFAULT_ACCOUNT_CACHE_TTL_SECONDS = 600
INTEGRATION_PLATFORM = "sif"

_REMOTE_BUNDLE_CACHE: dict[str, tuple[float, IntegrationAccountBundle]] = {}


@dataclass(frozen=True)
class SifAccount:
    """Sif account summary used by service code."""

    name: str
    username: str
    password: str

    def to_public_dict(self) -> dict[str, Any]:
        """Return account info without password."""
        return {
            "name": self.name,
            "username": _mask_username(self.username),
            "has_password": bool(self.password),
        }


class SifAccountProvider:
    """Load Sif account from OPS integration accounts, then env fallback."""

    def __init__(
        self,
        settings: SifSettings | None = None,
        integration_client: IntegrationAccountClient | None = None,
        *,
        cache_ttl_seconds: int = DEFAULT_ACCOUNT_CACHE_TTL_SECONDS,
    ) -> None:
        self.settings = settings or load_settings()
        self.integration_client = integration_client or IntegrationAccountClient()
        self.cache_ttl_seconds = cache_ttl_seconds
        self._remote_bundle: IntegrationAccountBundle | None = None
        self._remote_error: Exception | None = None

    def get_default(self, *, refresh: bool = False) -> SifAccount:
        """Return the default Sif account."""
        account = self._get_remote_default(refresh=refresh)
        if account:
            return account

        if self.settings.username and self.settings.password:
            return SifAccount(
                name="default",
                username=self.settings.username,
                password=self.settings.password,
            )

        if self._remote_error:
            raise SifConfigError(
                f"获取 Sif 集成账号失败：{self._remote_error}。"
                "MCP 模式请确认 OPS 授权可用，或在服务配置中设置 OPSCLI_SIF_USERNAME/OPSCLI_SIF_PASSWORD。"
            )
        raise SifConfigError("缺少 Sif 账号配置：请在 OPS 集成账号平台 sif 中配置账号，或设置 OPSCLI_SIF_USERNAME/OPSCLI_SIF_PASSWORD。")

    def list_public(self) -> list[dict[str, Any]]:
        """List available account summaries without passwords."""
        remote_accounts = self._list_remote_accounts()
        if remote_accounts:
            return [account.to_public_dict() for account in remote_accounts]

        if not self.settings.username:
            return []
        return [
            {
                "name": "default",
                "username": _mask_username(self.settings.username),
                "has_password": bool(self.settings.password),
            }
        ]

    def _get_remote_default(self, *, refresh: bool = False) -> SifAccount | None:
        bundle = self._load_remote_bundle(refresh=refresh)
        if not bundle or not bundle.accounts:
            return None

        default_name = bundle.default_account or bundle.accounts[0].name
        for item in bundle.accounts:
            if item.name == default_name:
                return SifAccount(name=item.name, username=item.username, password=item.password)

        raise SifConfigError(f"Sif 集成账号中不存在默认账号：{default_name}")

    def _list_remote_accounts(self) -> list[SifAccount]:
        bundle = self._load_remote_bundle()
        if not bundle:
            return []
        return [SifAccount(name=item.name, username=item.username, password=item.password) for item in bundle.accounts]

    def _load_remote_bundle(self, *, refresh: bool = False) -> IntegrationAccountBundle | None:
        if not refresh and self._remote_bundle is not None:
            return self._remote_bundle
        cached = _REMOTE_BUNDLE_CACHE.get(INTEGRATION_PLATFORM)
        if not refresh and cached and time.time() - cached[0] < self.cache_ttl_seconds:
            self._remote_bundle = cached[1]
            self._remote_error = None
            return self._remote_bundle
        try:
            self._remote_bundle = self.integration_client.get_accounts(INTEGRATION_PLATFORM)
            self._remote_error = None
            _REMOTE_BUNDLE_CACHE[INTEGRATION_PLATFORM] = (time.time(), self._remote_bundle)
        except Exception as exc:
            self._remote_error = exc
            self._remote_bundle = None
        return self._remote_bundle


def _mask_username(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:3]}{'*' * max(len(text) - 5, 3)}{text[-2:]}"
