"""Shopify 刊登模块。

封装北极星刊登系统的 Shopify 相关 API：
- 查询用户有权限的店铺（getSourceChannels）
- 查询 Shopify 商品列表（/shopify/listing/list）
- 构造工单 payload 并委托 feedtask 模块提交
"""

from opscli.shopify.domain.exceptions import (
    ShopifyAuthError,
    ShopifyError,
    ShopifyNotFoundError,
    ShopifyParamsError,
    ShopifyTaskError,
)
from opscli.shopify.domain.models import Shop, ShopifyProduct, ShopifyVariant
from opscli.shopify.services.manager import ShopifyManager
from opscli.shopify.transport.client import ShopifyClient

__all__ = [
    "ShopifyClient",
    "ShopifyManager",
    "Shop",
    "ShopifyProduct",
    "ShopifyVariant",
    "ShopifyError",
    "ShopifyAuthError",
    "ShopifyNotFoundError",
    "ShopifyParamsError",
    "ShopifyTaskError",
]
