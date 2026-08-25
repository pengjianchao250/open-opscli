"""Keepa 任务结果的小型公开摘要。"""

from __future__ import annotations

from typing import Any

# MCP 和 result.json 最多保留 5 行摘要，完整记录统一从导出文件读取。
KEEPA_SUMMARY_ROW_LIMIT = 5
# 白名单只包含识别结果所需的标量字段，避免历史、Offer 等嵌套值进入上下文。
KEEPA_SUMMARY_FIELDS = (
    "asin",
    "title",
    "brand",
    "sellerId",
    "sellerName",
    "categoryId",
    "catId",
    "name",
    "dealId",
    "dealState",
    "totalResults",
    "bestSellerRank",
)

SCENARIO_SUMMARY_FIELDS: dict[str, tuple[str, ...]] = {
    "product": KEEPA_SUMMARY_FIELDS
    + (
        "dealMetadataStatus",
        "hasActiveDealMetadata",
        "dealCount",
        "dealTypesJoined",
        "dealBadgesJoined",
        "dealAccessTypesJoined",
        "hasLimitedTimeDealBadge",
        "hasPriceDealBadge",
        "statsCurrentLightningDealPrice",
        "statsCurrentLightningDealPriceSource",
        "statsCurrentPrimeExclusivePrice",
        "statsCurrentPrimeExclusivePriceSource",
        "statsBuyBoxPrice",
        "statsBuyBoxShipping",
        "statsBuyBoxLandedPrice",
        "statsBuyBoxSavingBasis",
        "statsBuyBoxSavingBasisType",
        "statsBuyBoxSavingPercentage",
        "dealAssociatedBuyBoxLandedPrice",
        "dealAssociatedPriceStatus",
        "dealAssociatedPriceCurrency",
        "dealAssociatedPriceSource",
        "dealAssociatedPriceIsNativeDealPrice",
        "offersRequested",
        "offersSuccessful",
        "priceFreshnessStatus",
        "currencyCode",
    ),
    "deals": KEEPA_SUMMARY_FIELDS
    + (
        "titleText",
        "currentAmazonPrice",
        "currentNewPrice",
        "currentLightningDealPrice",
        "currentBuyBoxPrice",
        "currentPrimeExclusivePrice",
        "isLightningDeal",
        "lightningEndUtc",
    ),
    "lightning-deals": KEEPA_SUMMARY_FIELDS
    + (
        "dealPriceAmount",
        "currentPriceAmount",
        "currencyCode",
        "startTimeUtc",
        "endTimeUtc",
        "percentClaimed",
        "percentOff",
        "calculatedDiscountPercent",
    ),
}


def summarize_rows(
    rows: list[Any],
    *,
    limit: int = KEEPA_SUMMARY_ROW_LIMIT,
    scenario: str | None = None,
) -> list[Any]:
    """压缩 Keepa 结果行。

    Args:
        rows: Keepa 主结果行；对象行可能包含大型嵌套字段。
        limit: 最多保留的摘要行数。

    Returns:
        最多 ``limit`` 行的标量白名单摘要；标量结果行保持原值。
    """
    fields = SCENARIO_SUMMARY_FIELDS.get(scenario or "", KEEPA_SUMMARY_FIELDS)
    return [_summarize_row(row, fields=fields) for row in rows[:limit]]


def _summarize_row(row: Any, *, fields: tuple[str, ...]) -> Any:
    """为单行保留稳定标识字段，标量列表则保持原值。"""
    if not isinstance(row, dict):
        return row
    return {
        field: row[field]
        for field in fields
        if field in row and not isinstance(row[field], (dict, list))
    }
