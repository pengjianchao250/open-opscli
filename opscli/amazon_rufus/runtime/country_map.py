"""Amazon 国家站点固定映射。"""

from __future__ import annotations

from opscli.amazon_rufus.domain.exceptions import UnsupportedMarketplaceError
from opscli.amazon_rufus.domain.models import Marketplace

_MARKETPLACES: dict[str, Marketplace] = {
    "US": Marketplace(country="US", base_url="https://www.amazon.com"),
    "UK": Marketplace(country="UK", base_url="https://www.amazon.co.uk"),
    "DE": Marketplace(country="DE", base_url="https://www.amazon.de"),
    "JP": Marketplace(country="JP", base_url="https://www.amazon.co.jp"),
}


def resolve_marketplace(country: str) -> Marketplace:
    """按国家名解析 Amazon 站点。"""
    normalized = country.strip().upper()
    try:
        return _MARKETPLACES[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(_MARKETPLACES))
        raise UnsupportedMarketplaceError(f"不支持的国家: {country}，支持: {supported}") from exc


def build_product_url(asin: str, country: str) -> str:
    """构造商品详情页 URL。"""
    marketplace = resolve_marketplace(country)
    return f"{marketplace.base_url}/dp/{asin.strip().upper()}"
