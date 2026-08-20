"""Keepa Lightning Deal Object 格式化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.keepa.object_formatting import (
    add_time_fields,
    currency_info,
    image_url,
    money_amount,
)


@dataclass
class FormattedLightningDealExport:
    """Lightning Deal 主表与变体维度明细。"""

    deals: list[dict[str, Any]]
    variations: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        """返回非空变体工作表，供 XLSX 与格式化 JSON 共用。"""
        return {"lightning_variations": self.variations} if self.variations else {}


def format_lightning_deal_export(
    rows: list[Any], *, site: str = "US", domain_id: Any = None
) -> FormattedLightningDealExport:
    """格式化 Lightning Deal Object 并拆分 variation 数组。

    参数：rows 为原始对象列表，site/domain_id 用于站点币种解析。
    返回：包含秒杀主表和 variation dimension/value 明细的导出对象。
    """
    deals: list[dict[str, Any]] = []
    variations: list[dict[str, Any]] = []

    for value in rows:
        if not isinstance(value, dict):
            deals.append({"value": value})
            continue
        currency_code, decimals = currency_info(
            site=site,
            domain_id=value.get("domainId", domain_id),
        )
        row = {key: item for key, item in value.items() if key != "variation"}
        for field in ("lastUpdate", "startTime", "endTime"):
            add_time_fields(row, field)
        for field in ("dealPrice", "currentPrice"):
            if field in value:
                row[f"{field}Amount"] = money_amount(value.get(field), decimals=decimals)
        row["currencyCode"] = currency_code
        row["imageUrl"] = image_url(value.get("image"))
        if isinstance(value.get("rating"), (int, float)) and value["rating"] >= 0:
            row["ratingStars"] = value["rating"] / 10
        variation_values = value.get("variation") if isinstance(value.get("variation"), list) else []
        row["variationCount"] = len(variation_values)
        deals.append(row)

        for index, variation in enumerate(variation_values):
            detail = {
                "dealId": value.get("dealId"),
                "asin": value.get("asin"),
                "variationIndex": index,
            }
            if isinstance(variation, dict):
                detail.update(variation)
            else:
                detail["value"] = variation
            variations.append(detail)

    return FormattedLightningDealExport(deals, variations)
