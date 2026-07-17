"""卖家精灵接口直连领域对象。"""

from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteApiError,
    SellerSpriteAuthenticationError,
    SellerSpriteConfigError,
    SellerSpriteError,
)
from opscli.seller_sprite.domain.models import (
    SellerSpriteExportResult,
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)

__all__ = [
    "SellerSpriteApiError",
    "SellerSpriteAuthenticationError",
    "SellerSpriteConfigError",
    "SellerSpriteError",
    "SellerSpriteExportResult",
    "SellerSpriteScenarioRequest",
    "SellerSpriteScenarioResult",
]
