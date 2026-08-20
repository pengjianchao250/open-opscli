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
        _add_discount_fields(row, value)
        _add_duration_fields(row, value)
        for field in ("percentClaimed", "percentOff"):
            if field in value:
                row[f"{field}Display"] = _percent_display(value.get(field))
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


def _add_discount_fields(row: dict[str, Any], deal: dict[str, Any]) -> None:
    """根据当前价和秒杀价补充折扣百分比，保留 API 原始字段。"""
    current = _number(deal.get("currentPrice"))
    price = _number(deal.get("dealPrice"))
    if current is None or price is None or current <= 0 or price < 0:
        return
    discount = round((current - price) / current * 100, 2)
    row["calculatedDiscountPercent"] = discount
    row["calculatedDiscountPercentDisplay"] = f"{discount:g}%"


def _add_duration_fields(row: dict[str, Any], deal: dict[str, Any]) -> None:
    start = _number(deal.get("startTime"))
    end = _number(deal.get("endTime"))
    if start is None or end is None or start <= 0 or end < start:
        return
    row["durationMinutes"] = end - start
    row["durationHours"] = round((end - start) / 60, 2)


def _percent_display(value: Any) -> str | None:
    number = _number(value)
    if number is None or number in {-1, -2} or number < 0:
        return None
    return f"{number:g}%"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
