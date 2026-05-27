"""卖家精灵服务端账号来源。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


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
    """从服务端配置读取卖家精灵账号。"""

    def __init__(self, settings: SellerSpriteSettings | None = None) -> None:
        self.settings = settings or load_settings()

    def get_default(self) -> SellerSpriteAccount:
        """读取默认账号。"""
        account = self._get_from_pool(self.settings.account_name)
        if account:
            return account

        if self.settings.accounts:
            raise SellerSpriteConfigError(f"账号池中不存在默认账号：{self.settings.account_name}")

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
