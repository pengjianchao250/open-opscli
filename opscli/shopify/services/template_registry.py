"""Polaris workorder operation registry for Shopify."""

from __future__ import annotations

from dataclasses import dataclass

from opscli.config import get_shopify_template_id
from opscli.shopify.domain.exceptions import ShopifyParamsError


@dataclass(frozen=True)
class ShopifyOperationConfig:
    """Polaris template metadata for a Shopify operation."""

    name: str
    operate_method: str
    image: str
    label: str
    form_ref: str

    @property
    def template_id(self) -> int:
        return get_shopify_template_id(self.name)

    def to_legacy_dict(self) -> dict:
        return {
            "operate_method": self.operate_method,
            "image": self.image,
            "label": self.label,
            "form_ref": self.form_ref,
        }


OPERATION_REGISTRY: dict[str, ShopifyOperationConfig] = {
    "price_update": ShopifyOperationConfig(
        name="price_update",
        operate_method="shopifyModifyPrice",
        image="shopifyModifyPrice.png",
        label="修改价格",
        form_ref="Shopify-修改价格1",
    ),
    "inventory_set": ShopifyOperationConfig(
        name="inventory_set",
        operate_method="shopifyModifyInventory",
        image="shopifyModifyInventory.png",
        label="修改库存",
        form_ref="Shopify-修改库存",
    ),
    "set_active": ShopifyOperationConfig(
        name="set_active",
        operate_method="shopifySetActive",
        image="shopifySetActive.png",
        label="设置活跃",
        form_ref='shopify-设置"活跃"',
    ),
    "set_draft": ShopifyOperationConfig(
        name="set_draft",
        operate_method="shopifySetDraft",
        image="shopifySetDraft.png",
        label="设置草稿",
        form_ref='shopify-设置"草稿"',
    ),
    "delete": ShopifyOperationConfig(
        name="delete",
        operate_method="shopifyDelete",
        image="shopifyDelete.png",
        label="删除",
        form_ref="shopify-删除",
    ),
}


def get_operation_config(operation: str) -> ShopifyOperationConfig:
    """Return operation metadata, failing before a workorder is submitted."""

    config = OPERATION_REGISTRY.get(operation)
    if config is None:
        raise ShopifyParamsError(f"未知 Shopify 工单操作类型: {operation}")
    if config.template_id <= 0:
        raise ShopifyParamsError(f"Shopify 工单操作 {operation} 缺少有效模板 ID")
    return config
