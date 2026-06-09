"""Shopify 刊登数据模型。"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass
class Shop:
    """店铺/渠道信息。"""

    channel_id: int
    channel_name: str
    platform: str
    site_id: int
    status: str
    currency: str
    url: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class ShopifyVariant:
    """商品变体。"""

    listing_id: int
    sku: str | None = None
    seller_sku: str | None = None
    price: str = ""
    sale_price: str | None = None
    inventory_quantity: int = 0
    shopify_product_id: str | None = None
    product_gid: str | None = None
    product_id: str | None = None
    variant_gid: str | None = None
    main_image_url: str | None = None
    url: str | None = None
    currency_symbol: str | None = None
    overseas_inventory: list[dict] | None = None
    platform_inventory: list[dict] | None = None
    channel_id: int | None = None
    channel_name: str | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class ShopifyProduct:
    """刊登商品（聚合变体）。"""

    listing_id: int
    channel_id: int
    channel_name: str
    name: str
    sku: str | None = None
    variants: list[ShopifyVariant] | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
