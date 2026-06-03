"""卖家精灵账号来源。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from opscli.seller_sprite.config import DEFAULT_ACCOUNT_CACHE_TTL_SECONDS, SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError
from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountClient, IntegrationAccountError


_REMOTE_BUNDLE_CACHE: dict[str, tuple[float, IntegrationAccountBundle]] = {}


@dataclass(frozen=True)
class SellerSpriteAccount:
    """服务端本地卖家精灵账号。"""

    name: str
    username: str
    password: str

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含密码的账号摘要。"""
        return {
            "name": self.name,
            "username": self.username,
            "has_password": bool(self.password),
        }


class SellerSpriteAccountProvider:
    """读取卖家精灵账号。"""

    def __init__(
        self,
        settings: SellerSpriteSettings | None = None,
        integration_client: IntegrationAccountClient | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.integration_client = integration_client or IntegrationAccountClient()
        self._remote_bundle: IntegrationAccountBundle | None = None
        self._remote_error: IntegrationAccountError | None = None

    def get_default(self, *, refresh: bool = False) -> SellerSpriteAccount:
        """读取默认账号。"""
        account = self._get_remote_default(refresh=refresh)
        if account:
            return account

        account = self._get_from_pool(self.settings.account_name)
        if account:
            return account

        if self.settings.accounts:
            raise SellerSpriteConfigError(f"账号池中不存在默认账号：{self.settings.account_name}")

        if self._remote_error:
            raise SellerSpriteConfigError(f"获取卖家精灵集成账号失败：{self._remote_error}")
        if not self.settings.username:
            raise SellerSpriteConfigError("缺少 OPSCLI_SELLER_SPRITE_USERNAME")
        if not self.settings.password:
            raise SellerSpriteConfigError("缺少 OPSCLI_SELLER_SPRITE_PASSWORD")
        return SellerSpriteAccount(
            name=self.settings.account_name,
            username=self.settings.username,
            password=self.settings.password,
        )

    def list_public(self) -> list[dict[str, Any]]:
        """列出可用账号摘要，不返回密码。"""
        remote_accounts = self._list_remote_accounts()
        if remote_accounts:
            return [account.to_public_dict() for account in remote_accounts]

        if self.settings.accounts:
            return [
                SellerSpriteAccount(
                    name=item["name"],
                    username=item["username"],
                    password=item["password"],
                ).to_public_dict()
                for item in self.settings.accounts
            ]

        if not self.settings.username:
            return []
        return [
            {
                "name": self.settings.account_name,
                "username": self.settings.username,
                "has_password": bool(self.settings.password),
            }
        ]

    def _get_from_pool(self, name: str) -> SellerSpriteAccount | None:
        """从账号池按名称读取账号。"""
        for item in self.settings.accounts:
            if item["name"] == name:
                return SellerSpriteAccount(
                    name=item["name"],
                    username=item["username"],
                    password=item["password"],
                )
        return None

    def _get_remote_default(self, *, refresh: bool = False) -> SellerSpriteAccount | None:
        """优先读取集成账号接口默认账号。"""
        bundle = self._load_remote_bundle(refresh=refresh)
        if not bundle or not bundle.accounts:
            return None

        default_name = bundle.default_account or self.settings.account_name
        for item in bundle.accounts:
            if item.name == default_name:
                return SellerSpriteAccount(name=item.name, username=item.username, password=item.password)

        raise SellerSpriteConfigError(f"集成账号中不存在默认账号：{default_name}")

    def _list_remote_accounts(self) -> list[SellerSpriteAccount]:
        """列出远端账号。"""
        bundle = self._load_remote_bundle()
        if not bundle:
            return []
        return [SellerSpriteAccount(name=item.name, username=item.username, password=item.password) for item in bundle.accounts]

    def _load_remote_bundle(self, *, refresh: bool = False) -> IntegrationAccountBundle | None:
        """加载远端集成账号。"""
        if not refresh and self._remote_bundle is not None:
            return self._remote_bundle
        cache_key = "seller_sprite"
        cached = _REMOTE_BUNDLE_CACHE.get(cache_key)
        if not refresh and cached and time.time() - cached[0] < self.settings.account_cache_ttl_seconds:
            self._remote_bundle = cached[1]
            self._remote_error = None
            return self._remote_bundle
        try:
            self._remote_bundle = self.integration_client.get_accounts("seller_sprite")
            self._remote_error = None
            _REMOTE_BUNDLE_CACHE[cache_key] = (time.time(), self._remote_bundle)
        except IntegrationAccountError as exc:
            self._remote_error = exc
            self._remote_bundle = None
        return self._remote_bundle
