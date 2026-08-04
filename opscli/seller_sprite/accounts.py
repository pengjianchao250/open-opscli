"""卖家精灵账号来源。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteAccountSourceUnavailableError,
    SellerSpriteConfigError,
    SellerSpriteNoEligibleAccountError,
)
from opscli.shared.integration_accounts import (
    IntegrationAccountBundle,
    IntegrationAccountClient,
    IntegrationAccountError,
)

# 卖家精灵账号是平台公共数据，仅按平台在当前进程内缓存。
INTEGRATION_PLATFORM = "seller_sprite"
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
        *,
        allow_local_fallback: bool = True,
    ) -> None:
        """创建卖家精灵账号 Provider。

        参数：
            settings: 本地账号与缓存配置。
            integration_client: 远程集成账号客户端。
            allow_local_fallback: 远程异常或空结果时是否允许使用本地账号。

        返回：
            无。
        """
        self.settings = settings or load_settings()
        self.integration_client = integration_client or IntegrationAccountClient()
        self.allow_local_fallback = allow_local_fallback
        self._remote_bundle: IntegrationAccountBundle | None = None
        self._remote_error: IntegrationAccountError | None = None

    def get_default(self, *, refresh: bool = False) -> SellerSpriteAccount:
        """读取默认账号。"""
        account = self._get_remote_default(refresh=refresh)
        if account:
            return account

        self._raise_when_remote_required()

        account = self._get_from_pool(self.settings.account_name)
        if account:
            return account

        if self.settings.accounts:
            raise SellerSpriteConfigError(f"账号池中不存在默认账号：{self.settings.account_name}")

        if self._remote_error:
            raise SellerSpriteConfigError(
                f"获取卖家精灵集成账号失败：{self._remote_error}。"
                "请检查 OPS 授权：MCP 模式需携带有效 X-MCP-API-Key，CLI 模式执行 opscli auth login。"
            )
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
        return [account.to_public_dict() for account in self.list_accounts()]

    def list_accounts(self, *, refresh: bool = False) -> list[SellerSpriteAccount]:
        """按账号接口顺序返回全部可用账号凭证。"""
        remote_accounts = self._list_remote_accounts(refresh=refresh)
        if remote_accounts:
            return remote_accounts

        self._raise_when_remote_required()

        if self.settings.accounts:
            return [
                SellerSpriteAccount(
                    name=item["name"],
                    username=item["username"],
                    password=item["password"],
                )
                for item in self.settings.accounts
            ]

        if not self.settings.username or not self.settings.password:
            return []
        return [
            SellerSpriteAccount(
                name=self.settings.account_name,
                username=self.settings.username,
                password=self.settings.password,
            )
        ]

    def _raise_when_remote_required(self) -> None:
        """生产调度禁止把远程异常或空结果解释为本地账号候选。"""
        if self.allow_local_fallback:
            return
        if self._remote_error:
            raise SellerSpriteAccountSourceUnavailableError(
                "卖家精灵远程账号源不可用，已禁止回退本地账号"
            ) from self._remote_error
        raise SellerSpriteNoEligibleAccountError("卖家精灵远程账号源没有可用账号")

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

    def _list_remote_accounts(self, *, refresh: bool = False) -> list[SellerSpriteAccount]:
        """列出远端账号。"""
        bundle = self._load_remote_bundle(refresh=refresh)
        if not bundle:
            return []
        return [SellerSpriteAccount(name=item.name, username=item.username, password=item.password) for item in bundle.accounts]

    def _load_remote_bundle(self, *, refresh: bool = False) -> IntegrationAccountBundle | None:
        """加载远端集成账号。"""
        if not refresh and self._remote_bundle is not None:
            return self._remote_bundle
        now = time.time()
        _cleanup_remote_bundle_cache(now, self.settings.account_cache_ttl_seconds)
        cached = _REMOTE_BUNDLE_CACHE.get(INTEGRATION_PLATFORM)
        if not refresh and cached and time.time() - cached[0] < self.settings.account_cache_ttl_seconds:
            self._remote_bundle = cached[1]
            self._remote_error = None
            return self._remote_bundle
        try:
            self._remote_bundle = self.integration_client.get_accounts(INTEGRATION_PLATFORM)
            self._remote_error = None
            _REMOTE_BUNDLE_CACHE[INTEGRATION_PLATFORM] = (time.time(), self._remote_bundle)
        except IntegrationAccountError as exc:
            self._remote_error = exc
            self._remote_bundle = None
        return self._remote_bundle

def _cleanup_remote_bundle_cache(now: float, ttl_seconds: int) -> None:
    """主动清理过期的解密账号，避免公用 MCP 长期滞留敏感数据。"""
    expired = [
        key
        for key, (created_at, _) in _REMOTE_BUNDLE_CACHE.items()
        if now - created_at >= ttl_seconds
    ]
    for key in expired:
        _REMOTE_BUNDLE_CACHE.pop(key, None)
