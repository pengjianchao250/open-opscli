"""Keepa Deal Object formatting helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)


IMAGE_BASE_URL = "https://images-na.ssl-images-amazon.com/images/I"


@dataclass(frozen=True)
class CurrencyConfig:
    code: str
    decimals: int


@dataclass(frozen=True)
class PriceTypeConfig:
    name: str
    kind: str
    label: str


DOMAIN_CURRENCY: dict[int, CurrencyConfig] = {
    1: CurrencyConfig("USD", 2),
    2: CurrencyConfig("GBP", 2),
    3: CurrencyConfig("EUR", 2),
    4: CurrencyConfig("EUR", 2),
    5: CurrencyConfig("JPY", 0),
    6: CurrencyConfig("CAD", 2),
    8: CurrencyConfig("EUR", 2),
    9: CurrencyConfig("EUR", 2),
    10: CurrencyConfig("INR", 2),
    11: CurrencyConfig("MXN", 2),
    12: CurrencyConfig("BRL", 2),
}

SITE_DOMAIN: dict[str, int] = {
    "US": 1,
    "GB": 2,
    "UK": 2,
    "DE": 3,
    "FR": 4,
    "JP": 5,
    "CA": 6,
    "IT": 8,
    "ES": 9,
    "IN": 10,
    "MX": 11,
    "BR": 12,
}

PRICE_TYPES: dict[int, PriceTypeConfig] = {
    0: PriceTypeConfig("AMAZON", "money", "Amazon"),
    1: PriceTypeConfig("NEW", "money", "New"),
    2: PriceTypeConfig("USED", "money", "Used"),
    3: PriceTypeConfig("SALES", "rank", "SalesRank"),
    4: PriceTypeConfig("LISTPRICE", "money", "ListPrice"),
    5: PriceTypeConfig("COLLECTIBLE", "money", "Collectible"),
    6: PriceTypeConfig("REFURBISHED", "money", "Refurbished"),
    7: PriceTypeConfig("NEW_FBM_SHIPPING", "money", "NewFbmShipping"),
    8: PriceTypeConfig("LIGHTNING_DEAL", "money", "LightningDeal"),
    9: PriceTypeConfig("WAREHOUSE", "money", "Warehouse"),
    10: PriceTypeConfig("NEW_FBA", "money", "NewFba"),
    11: PriceTypeConfig("COUNT_NEW", "count", "NewOfferCount"),
    12: PriceTypeConfig("COUNT_USED", "count", "UsedOfferCount"),
    13: PriceTypeConfig("COUNT_REFURBISHED", "count", "RefurbishedOfferCount"),
    14: PriceTypeConfig("COUNT_COLLECTIBLE", "count", "CollectibleOfferCount"),
    15: PriceTypeConfig("EXTRA_INFO_UPDATES", "event", "ExtraInfoUpdates"),
    16: PriceTypeConfig("RATING", "rating", "Rating"),
    17: PriceTypeConfig("COUNT_REVIEWS", "count", "ReviewCount"),
    18: PriceTypeConfig("BUY_BOX_SHIPPING", "money", "BuyBox"),
    32: PriceTypeConfig("BUY_BOX_USED_SHIPPING", "money", "BuyBoxUsed"),
    33: PriceTypeConfig("PRIME_EXCL", "money", "PrimeExclusive"),
    34: PriceTypeConfig("COUNT_NEW_FBA", "count", "NewFbaOfferCount"),
    35: PriceTypeConfig("COUNT_NEW_FBM", "count", "NewFbmOfferCount"),
}

DATE_RANGES: dict[int, str] = {
    0: "day",
    1: "week",
    2: "month",
    3: "days90",
}

WAREHOUSE_CONDITION_TEXT = {
    0: "unknown_or_none",
    2: "used_like_new",
    3: "used_very_good",
    4: "used_good",
    5: "used_acceptable",
}

DELTA_REFERENCE_PRICE_TYPES = {8, 9, 33}


@dataclass
class FormattedDealExport:
    deals: list[dict[str, Any]]
    metric_rows: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        if not self.metric_rows:
            return {}
        return {"deal_metrics": self.metric_rows}

    def to_dict(self) -> dict[str, Any]:
        return {
            "deals": self.deals,
            "deal_metrics": self.metric_rows,
        }


def format_deal_export(rows: list[Any], *, site: str = "US", domain_id: Any = None) -> FormattedDealExport:
    """Format Keepa deal rows into main rows and metric detail rows."""
    deals: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    currency = _currency_for(site=site, domain_id=domain_id)
    for row in rows:
        if not isinstance(row, dict):
            deals.append({"value": row})
            continue
        deals.append(format_deal_object(row, site=site, domain_id=domain_id))
        metric_rows.extend(format_deal_metric_rows(row, currency=currency))
    return FormattedDealExport(deals=deals, metric_rows=metric_rows)


def format_deal_object(deal: dict[str, Any], *, site: str = "US", domain_id: Any = None) -> dict[str, Any]:
    """Return a Deal Object copy with derived display/export fields."""
    currency = _currency_for(site=site, domain_id=domain_id or deal.get("domainId"))
    row = dict(deal)
    row["rowSource"] = "deals"
    row["dealRaw"] = deal

    if isinstance(deal.get("title"), str):
        row["titleText"] = _strip_html(deal["title"])
    root_cat = deal.get("rootCat")
    if root_cat not in (None, 0, 9223372036854775807):
        row["rootCatText"] = str(root_cat)
    categories = deal.get("categories")
    if isinstance(categories, list):
        row["categoryIds"] = ", ".join(str(item) for item in categories)

    image_name = _image_name(deal.get("image"))
    if image_name:
        row["imageName"] = image_name
        row["imageUrl"] = f"{IMAGE_BASE_URL}/{image_name}"

    _add_keepa_time_fields(row, "lastUpdate", deal.get("lastUpdate"))
    if deal.get("creationDate") not in (None, -1):
        _add_keepa_time_fields(row, "creationDate", deal.get("creationDate"))
    lightning_end = deal.get("lightningEnd")
    row["isLightningDeal"] = _parse_number(lightning_end) is not None and _parse_number(lightning_end) > 0
    if row["isLightningDeal"]:
        _add_keepa_time_fields(row, "lightningEnd", lightning_end)

    if "warehouseCondition" in deal:
        condition = _parse_int(deal.get("warehouseCondition"))
        row["warehouseConditionText"] = WAREHOUSE_CONDITION_TEXT.get(condition, "unknown")

    _add_current_summary_fields(row, deal.get("current"), currency)
    row["currencyCode"] = currency.code
    row["currencyDecimals"] = currency.decimals
    return row


def format_deal_metric_rows(deal: dict[str, Any], *, currency: CurrencyConfig) -> list[dict[str, Any]]:
    asin = "" if deal.get("asin") is None else str(deal.get("asin"))
    rows: list[dict[str, Any]] = []
    for metric in ("current", "currentSince", "deltaLast"):
        values = deal.get(metric)
        if isinstance(values, list):
            rows.extend(_one_dimensional_metric_rows(asin, metric, values, currency))
    for metric in ("delta", "deltaPercent", "avg"):
        values = deal.get(metric)
        if isinstance(values, list):
            rows.extend(_two_dimensional_metric_rows(asin, metric, values, currency))
    return rows


def _one_dimensional_metric_rows(
    asin: str,
    metric: str,
    values: list[Any],
    currency: CurrencyConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for price_type_index, raw_value in enumerate(values):
        config = _price_type(price_type_index)
        rows.append(_metric_row(asin, metric, None, price_type_index, config, raw_value, currency))
    return rows


def _two_dimensional_metric_rows(
    asin: str,
    metric: str,
    values: list[Any],
    currency: CurrencyConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date_range_index, range_values in enumerate(values):
        if not isinstance(range_values, list):
            continue
        for price_type_index, raw_value in enumerate(range_values):
            config = _price_type(price_type_index)
            rows.append(_metric_row(asin, metric, date_range_index, price_type_index, config, raw_value, currency))
    return rows


def _metric_row(
    asin: str,
    metric: str,
    date_range_index: int | None,
    price_type_index: int,
    config: PriceTypeConfig,
    raw_value: Any,
    currency: CurrencyConfig,
) -> dict[str, Any]:
    value_kind = _value_kind(metric, config.kind)
    row: dict[str, Any] = {
        "asin": asin,
        "metric": metric,
        "dateRangeIndex": date_range_index,
        "dateRangeName": DATE_RANGES.get(date_range_index) if date_range_index is not None else None,
        "priceTypeIndex": price_type_index,
        "priceTypeName": config.name,
        "rawValue": raw_value,
        "formattedValue": _format_metric_value(raw_value, value_kind, currency),
        "valueKind": value_kind,
    }
    if value_kind == "money":
        row["currency"] = currency.code
    if value_kind == "time" and _is_valid_keepa_time(raw_value):
        row["unixSeconds"] = keepa_minutes_to_unix_seconds(raw_value)
        row["unixMilliseconds"] = keepa_minutes_to_unix_milliseconds(raw_value)
        row["utc"] = keepa_minutes_to_utc_iso(raw_value)
    if metric in {"delta", "deltaLast", "deltaPercent"} and price_type_index in DELTA_REFERENCE_PRICE_TYPES:
        row["deltaReference"] = "AMAZON_OR_NEW"
    if metric == "avg" and date_range_index == 0:
        row["dateRangeNote"] = "avg day window is 48 hours"
    return row


def _add_current_summary_fields(row: dict[str, Any], current: Any, currency: CurrencyConfig) -> None:
    if not isinstance(current, list):
        return
    mappings = {
        0: "currentAmazonPrice",
        1: "currentNewPrice",
        3: "currentSalesRank",
        10: "currentNewFbaPrice",
        16: "currentRating",
        17: "currentReviewCount",
        18: "currentBuyBoxPrice",
    }
    for index, field in mappings.items():
        if index >= len(current):
            continue
        config = _price_type(index)
        raw_value = current[index]
        row[f"{field}Raw"] = raw_value
        row[field] = _format_metric_value(raw_value, config.kind, currency)
        if config.kind == "money":
            row[f"{field}Currency"] = currency.code


def _value_kind(metric: str, price_type_kind: str) -> str:
    if metric == "currentSince":
        return "time"
    if metric == "deltaPercent":
        return "percent"
    return price_type_kind


def _format_metric_value(value: Any, value_kind: str, currency: CurrencyConfig) -> Any:
    if value_kind == "money":
        return _format_money(value, currency)
    if value_kind == "rating":
        number = _parse_number(value)
        return None if number is None or number < 0 else number / 10
    if value_kind == "time":
        return keepa_minutes_to_utc_iso(value) if _is_valid_keepa_time(value) else None
    if value_kind == "percent":
        return None if value == -1 else value
    return None if value == -1 else value


def _format_money(value: Any, currency: CurrencyConfig) -> float | int | None:
    number = _parse_number(value)
    if number is None or number == -1:
        return None
    amount = number / (10**currency.decimals)
    if currency.decimals == 0:
        return int(amount)
    return round(amount, currency.decimals)


def _add_keepa_time_fields(row: dict[str, Any], field: str, value: Any) -> None:
    row[field] = value
    if not _is_valid_keepa_time(value):
        return
    row[f"{field}UnixSeconds"] = keepa_minutes_to_unix_seconds(value)
    row[f"{field}UnixMilliseconds"] = keepa_minutes_to_unix_milliseconds(value)
    row[f"{field}Utc"] = keepa_minutes_to_utc_iso(value)


def _image_name(value: Any) -> str | None:
    if isinstance(value, list):
        try:
            return "".join(chr(int(item)) for item in value if _parse_int(item) is not None)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _price_type(index: int) -> PriceTypeConfig:
    return PRICE_TYPES.get(index, PriceTypeConfig(f"CSV_{index}", "unknown", f"PriceType{index}"))


def _currency_for(*, site: str, domain_id: Any = None) -> CurrencyConfig:
    domain = _parse_int(domain_id)
    if domain is None:
        domain = SITE_DOMAIN.get(str(site or "US").upper(), 1)
    return DOMAIN_CURRENCY.get(domain, CurrencyConfig("USD", 2))


def _is_valid_keepa_time(value: Any) -> bool:
    number = _parse_number(value)
    return number is not None and number > 0


def _parse_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_int(value: Any) -> int | None:
    number = _parse_number(value)
    if number is None:
        return None
    return int(number)
