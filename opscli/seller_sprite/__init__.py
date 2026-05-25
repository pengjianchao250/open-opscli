"""卖家精灵接口直连模块。

本包只承载新接口直连方案；旧 Playwright 方案保留在
``opscli.seller_sprite_legacy``，不在这里混用。
"""

from opscli.seller_sprite.domain.models import (
    SellerSpriteExportResult,
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)

__all__ = [
    "SellerSpriteExportResult",
    "SellerSpriteScenarioRequest",
    "SellerSpriteScenarioResult",
]
