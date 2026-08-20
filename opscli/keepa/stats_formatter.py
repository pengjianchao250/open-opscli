"""Keepa Product stats object formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)


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
    0: PriceTypeConfig("AMAZON", "price", "Amazon"),
    1: PriceTypeConfig("NEW", "price", "New"),
    2: PriceTypeConfig("USED", "price", "Used"),
    3: PriceTypeConfig("SALES", "rank", "SalesRank"),
    4: PriceTypeConfig("LISTPRICE", "price", "ListPrice"),
    5: PriceTypeConfig("COLLECTIBLE", "price", "Collectible"),
    6: PriceTypeConfig("REFURBISHED", "price", "Refurbished"),
    7: PriceTypeConfig("NEW_FBM_SHIPPING", "price", "NewFbmShipping"),
    8: PriceTypeConfig("LIGHTNING_DEAL", "price", "LightningDeal"),
    9: PriceTypeConfig("WAREHOUSE", "price", "Warehouse"),
    10: PriceTypeConfig("NEW_FBA", "price", "NewFba"),
    11: PriceTypeConfig("COUNT_NEW", "count", "NewOfferCount"),
    12: PriceTypeConfig("COUNT_USED", "count", "UsedOfferCount"),
    13: PriceTypeConfig("COUNT_REFURBISHED", "count", "RefurbishedOfferCount"),
    14: PriceTypeConfig("COUNT_COLLECTIBLE", "count", "CollectibleOfferCount"),
    16: PriceTypeConfig("RATING", "rating", "Rating"),
    17: PriceTypeConfig("COUNT_REVIEWS", "count", "ReviewCount"),
    18: PriceTypeConfig("BUY_BOX_SHIPPING", "price", "BuyBox"),
    32: PriceTypeConfig("BUY_BOX_USED_SHIPPING", "price", "BuyBoxUsed"),
    34: PriceTypeConfig("COUNT_NEW_FBA", "count", "NewFbaOfferCount"),
    35: PriceTypeConfig("COUNT_NEW_FBM", "count", "NewFbmOfferCount"),
}

ARRAY_FIELDS = ("current", "avg", "avg30", "avg90", "avg180", "avg365", "atIntervalStart")
EXTREME_FIELDS = ("min", "max", "minInInterval", "maxInInterval")
OUT_OF_STOCK_FIELDS = (
    "outOfStockPercentageInInterval",
    "outOfStockPercentage30",
    "outOfStockPercentage90",
    "outOfStockPercentage180",
    "outOfStockPercentage365",
)

COMMON_ARRAY_COLUMNS: dict[tuple[str, int], str] = {
    ("current", 0): "statsCurrentAmazonPrice",
    ("current", 1): "statsCurrentNewPrice",
    ("current", 2): "statsCurrentUsedPrice",
    ("current", 3): "statsCurrentSalesRank",
    ("current", 10): "statsCurrentNewFbaPrice",
    ("current", 11): "statsCurrentNewOfferCount",
    ("current", 16): "statsCurrentRating",
    ("current", 17): "statsCurrentReviewCount",
    ("current", 18): "statsCurrentBuyBoxPrice",
    ("current", 34): "statsCurrentNewFbaOfferCount",
    ("current", 35): "statsCurrentNewFbmOfferCount",
    ("avg30", 1): "statsAvg30NewPrice",
    ("avg30", 3): "statsAvg30SalesRank",
    ("avg90", 1): "statsAvg90NewPrice",
    ("avg90", 3): "statsAvg90SalesRank",
}

TIME_FIELDS = ("lastOffersUpdate", "lastBuyBoxUpdate")
MONEY_FIELDS = (
    "buyBoxPrice",
    "buyBoxShipping",
    "buyBoxSavingBasis",
    "buyBoxUsedPrice",
    "buyBoxUsedShipping",
)
PERCENT_FIELDS = ("buyBoxSavingPercentage",)
JOIN_FIELDS = ("sellerIdsLowestFBA", "sellerIdsLowestFBM")


@dataclass
class FormattedStatsExport:
    main_fields: dict[str, Any]
    price_type_rows: list[dict[str, Any]]
    extreme_rows: list[dict[str, Any]]
    buy_box_seller_rows: list[dict[str, Any]]
    offer_snapshot_rows: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        sheets: dict[str, list[dict[str, Any]]] = {}
        if self.price_type_rows:
            sheets["stats_price_types"] = self.price_type_rows
        if self.extreme_rows:
            sheets["stats_extremes"] = self.extreme_rows
        if self.buy_box_seller_rows:
            sheets["stats_buy_box_sellers"] = self.buy_box_seller_rows
        if self.offer_snapshot_rows:
            sheets["stats_offer_snapshot"] = self.offer_snapshot_rows
        return sheets

    def to_dict(self) -> dict[str, Any]:
        return {
            "stats_price_types": self.price_type_rows,
            "stats_extremes": self.extreme_rows,
            "stats_buy_box_sellers": self.buy_box_seller_rows,
            "stats_offer_snapshot": self.offer_snapshot_rows,
        }


def format_stats_for_product(product: dict[str, Any], *, site: str = "US", domain_id: Any = None) -> FormattedStatsExport | None:
    """Format Product Object stats into main-row fields and detail tables."""
    stats = product.get("stats")
    if not isinstance(stats, dict):
        return None
    asin = "" if product.get("asin") is None else str(product.get("asin"))
    currency = _currency_for(site=site, domain_id=domain_id or product.get("domainId"))
    main_fields = _main_fields(stats, asin=asin, currency=currency)
    return FormattedStatsExport(
        main_fields=main_fields,
        price_type_rows=_price_type_rows(stats, asin=asin, currency=currency),
        extreme_rows=_extreme_rows(stats, asin=asin, currency=currency),
        buy_box_seller_rows=_buy_box_seller_rows(stats, asin=asin, currency=currency),
        offer_snapshot_rows=_offer_snapshot_rows(stats, asin=asin),
    )


def _main_fields(stats: dict[str, Any], *, asin: str, currency: CurrencyConfig) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for field in TIME_FIELDS:
        _add_keepa_time_fields(fields, f"stats{_pascal(field)}", stats.get(field))
    for field in MONEY_FIELDS:
        if field in stats:
            _add_money_fields(fields, f"stats{_pascal(field)}", stats.get(field), currency)
    for field in PERCENT_FIELDS:
        if field in stats:
            fields[f"stats{_pascal(field)}Display"] = _format_percent(stats.get(field))
    for field in ("salesRankDrops30", "salesRankDrops90", "salesRankDrops180", "salesRankDrops365"):
        if field in stats:
            fields[f"stats{_pascal(field)}"] = stats.get(field)
    for field in ("totalOfferCount", "retrievedOfferCount", "offerCountFBA", "offerCountFBM", "stockAmazon", "stockBuyBox"):
        if field in stats:
            fields[f"stats{_pascal(field)}"] = _available_numeric(stats.get(field))
    for field in JOIN_FIELDS:
        value = stats.get(field)
        if isinstance(value, list):
            fields[f"stats{_pascal(field)}Joined"] = ", ".join(str(item) for item in value)

    _add_array_main_fields(fields, stats, currency)
    _add_out_of_stock_main_fields(fields, stats)
    _add_buy_box_fields(fields, stats, currency)
    _add_lightning_deal_fields(fields, stats)
    fields["statsDataFreshness"] = _data_freshness(stats)
    if asin:
        fields["statsAsin"] = asin
    return fields


def _add_array_main_fields(fields: dict[str, Any], stats: dict[str, Any], currency: CurrencyConfig) -> None:
    for (field, price_type_index), output_name in COMMON_ARRAY_COLUMNS.items():
        values = stats.get(field)
        if not isinstance(values, list) or price_type_index >= len(values):
            continue
        raw_value = values[price_type_index]
        config = _price_type(price_type_index)
        fields[f"{output_name}Raw"] = raw_value
        fields[output_name] = _format_by_kind(raw_value, config.kind, currency)
        if config.kind == "price":
            fields[f"{output_name}Currency"] = currency.code


def _add_out_of_stock_main_fields(fields: dict[str, Any], stats: dict[str, Any]) -> None:
    mappings = {
        ("outOfStockPercentage30", 0): "statsOutOfStockPercentage30Amazon",
        ("outOfStockPercentage30", 1): "statsOutOfStockPercentage30New",
        ("outOfStockPercentage90", 0): "statsOutOfStockPercentage90Amazon",
        ("outOfStockPercentage90", 1): "statsOutOfStockPercentage90New",
    }
    for (field, price_type_index), output_name in mappings.items():
        values = stats.get(field)
        if isinstance(values, list) and price_type_index < len(values):
            raw_value = values[price_type_index]
            fields[output_name] = None if raw_value in {-1, -2} else raw_value
            fields[f"{output_name}Display"] = (
                None if raw_value in {-1, -2} else _format_percent(raw_value)
            )


def _add_buy_box_fields(fields: dict[str, Any], stats: dict[str, Any], currency: CurrencyConfig) -> None:
    seller_id = stats.get("buyBoxSellerId")
    if "buyBoxSellerId" in stats:
        fields["statsBuyBoxSellerStatus"] = _seller_status(seller_id)
        fields["statsHasBuyBox"] = _seller_status(seller_id) == "seller" and _format_money(stats.get("buyBoxPrice"), currency) is not None
    landed = _landed_price(stats.get("buyBoxPrice"), stats.get("buyBoxShipping"), currency)
    if landed is not None:
        fields["statsBuyBoxLandedPrice"] = landed
        fields["statsBuyBoxLandedPriceCurrency"] = currency.code
    used_landed = _landed_price(stats.get("buyBoxUsedPrice"), stats.get("buyBoxUsedShipping"), currency)
    if used_landed is not None:
        fields["statsBuyBoxUsedLandedPrice"] = used_landed
        fields["statsBuyBoxUsedLandedPriceCurrency"] = currency.code
    shipping_time = stats.get("buyBoxShippingTime")
    if isinstance(shipping_time, list) and len(shipping_time) >= 2:
        fields["statsBuyBoxShippingTimeText"] = _shipping_time_text(shipping_time[0], shipping_time[1])


def _add_lightning_deal_fields(fields: dict[str, Any], stats: dict[str, Any]) -> None:
    value = stats.get("lightningDealInfo")
    if value is None:
        fields["statsLightningDealStatus"] = "none"
        fields["statsHasLightningDealHistory"] = False
        return
    if not isinstance(value, list) or len(value) < 2:
        fields["statsLightningDealStatus"] = "unknown"
        fields["statsHasLightningDealHistory"] = True
        return
    start, end = value[0], value[1]
    fields["statsHasLightningDealHistory"] = True
    _add_keepa_time_fields(fields, "statsLightningDealStart", start)
    if end != -1:
        _add_keepa_time_fields(fields, "statsLightningDealEnd", end)
    fields["statsLightningDealStatus"] = _lightning_status(start, end)


def _price_type_rows(stats: dict[str, Any], *, asin: str, currency: CurrencyConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in ARRAY_FIELDS:
        values = stats.get(field)
        if not isinstance(values, list):
            continue
        for index, raw_value in enumerate(values):
            config = _price_type(index)
            row = _price_type_base(asin, field, index, config, raw_value, currency)
            rows.append(row)
    for field in OUT_OF_STOCK_FIELDS:
        values = stats.get(field)
        if not isinstance(values, list):
            continue
        for index, raw_value in enumerate(values):
            config = _price_type(index)
            rows.append(
                {
                    "asin": asin,
                    "statField": field,
                    "priceTypeIndex": index,
                    "priceTypeName": config.name,
                    "valueType": "percentage",
                    "rawValue": raw_value,
                    "formattedValue": None if raw_value in {-1, -2} else raw_value,
                    "displayValue": (
                        None if raw_value in {-1, -2} else _format_percent(raw_value)
                    ),
                }
            )
    return rows


def _price_type_base(
    asin: str,
    field: str,
    index: int,
    config: PriceTypeConfig,
    raw_value: Any,
    currency: CurrencyConfig,
) -> dict[str, Any]:
    row = {
        "asin": asin,
        "statField": field,
        "priceTypeIndex": index,
        "priceTypeName": config.name,
        "valueType": config.kind,
        "rawValue": raw_value,
        "formattedValue": _format_by_kind(raw_value, config.kind, currency),
    }
    if config.kind == "price":
        row["currencyCode"] = currency.code
        row["currencyDecimals"] = currency.decimals
    return row


def _extreme_rows(stats: dict[str, Any], *, asin: str, currency: CurrencyConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in EXTREME_FIELDS:
        values = stats.get(field)
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, list) or len(item) < 2:
                continue
            keepa_time, raw_value = item[0], item[1]
            config = _price_type(index)
            row = {
                "asin": asin,
                "statField": field,
                "priceTypeIndex": index,
                "priceTypeName": config.name,
                "keepaTime": keepa_time,
                "rawValue": raw_value,
                "formattedValue": _format_by_kind(raw_value, config.kind, currency),
                "valueType": config.kind,
            }
            if _is_valid_keepa_time(keepa_time):
                row["unixSeconds"] = keepa_minutes_to_unix_seconds(keepa_time)
                row["unixMilliseconds"] = keepa_minutes_to_unix_milliseconds(keepa_time)
                row["utc"] = keepa_minutes_to_utc_iso(keepa_time)
            if config.kind == "price":
                row["currencyCode"] = currency.code
            rows.append(row)
    return rows


def _buy_box_seller_rows(stats: dict[str, Any], *, asin: str, currency: CurrencyConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, box_type in (("buyBoxStats", "new"), ("buyBoxUsedStats", "used")):
        value = stats.get(field)
        if not isinstance(value, dict):
            continue
        for seller_id, seller_stats in value.items():
            if not isinstance(seller_stats, dict):
                continue
            row = {
                "asin": asin,
                "boxType": box_type,
                "sellerId": str(seller_id),
                "avgPriceRaw": seller_stats.get("avgPrice"),
                "avgPrice": _format_money(seller_stats.get("avgPrice"), currency),
                "avgPriceCurrency": currency.code,
                "avgNewOfferCount": seller_stats.get("avgNewOfferCount"),
                "isFBA": seller_stats.get("isFBA"),
                "lastSeen": seller_stats.get("lastSeen"),
                "percentageWon": seller_stats.get("percentageWon"),
                "percentageWonDisplay": _format_percent(seller_stats.get("percentageWon")),
            }
            _add_keepa_time_fields(row, "lastSeen", seller_stats.get("lastSeen"))
            rows.append(row)
    return rows


def _offer_snapshot_rows(stats: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    fields = (
        "retrievedOfferCount",
        "totalOfferCount",
        "sellerIdsLowestFBA",
        "sellerIdsLowestFBM",
        "offerCountFBA",
        "offerCountFBM",
        "stockAmazon",
        "stockBuyBox",
    )
    if not any(field in stats for field in fields):
        return []
    row: dict[str, Any] = {"asin": asin}
    for field in fields:
        if field not in stats:
            continue
        value = stats.get(field)
        row[field] = value
        if isinstance(value, list):
            row[f"{field}Joined"] = ", ".join(str(item) for item in value)
    return [row]


def _add_keepa_time_fields(row: dict[str, Any], prefix: str, value: Any) -> None:
    row[prefix] = value
    if not _is_valid_keepa_time(value):
        return
    row[f"{prefix}UnixSeconds"] = keepa_minutes_to_unix_seconds(value)
    row[f"{prefix}UnixMilliseconds"] = keepa_minutes_to_unix_milliseconds(value)
    row[f"{prefix}Utc"] = keepa_minutes_to_utc_iso(value)


def _add_money_fields(row: dict[str, Any], prefix: str, value: Any, currency: CurrencyConfig) -> None:
    row[f"{prefix}Raw"] = value
    row[prefix] = _format_money(value, currency)
    row[f"{prefix}Currency"] = currency.code


def _format_by_kind(value: Any, kind: str, currency: CurrencyConfig) -> Any:
    if kind == "price":
        return _format_money(value, currency)
    if kind == "rating":
        number = _parse_number(value)
        return None if number is None or number < 0 else number / 10
    return _available_numeric(value)


def _format_money(value: Any, currency: CurrencyConfig) -> float | int | None:
    number = _parse_number(value)
    if number is None or number in {-1, -2}:
        return None
    amount = number / (10**currency.decimals)
    if currency.decimals == 0:
        return int(amount)
    return round(amount, currency.decimals)


def _landed_price(price: Any, shipping: Any, currency: CurrencyConfig) -> float | int | None:
    price_amount = _format_money(price, currency)
    shipping_amount = _format_money(shipping, currency)
    if price_amount is None or shipping_amount is None:
        return None
    amount = price_amount + shipping_amount
    if currency.decimals == 0:
        return int(amount)
    return round(amount, currency.decimals)


def _available_numeric(value: Any) -> Any:
    return None if value in {-1, -2} else value


def _format_percent(value: Any) -> str | None:
    number = _parse_number(value)
    if number is None or number < 0:
        return None
    return f"{number:g}%"


def _price_type(index: int) -> PriceTypeConfig:
    return PRICE_TYPES.get(index, PriceTypeConfig(f"CSV_{index}", "unknown", f"PriceType{index}"))


def _currency_for(*, site: str, domain_id: Any = None) -> CurrencyConfig:
    domain = _parse_int(domain_id)
    if domain is None:
        domain = SITE_DOMAIN.get(str(site or "US").upper(), 1)
    return DOMAIN_CURRENCY.get(domain, CurrencyConfig("USD", 2))


def _seller_status(value: Any) -> str:
    if value in (None, ""):
        return "missing"
    if str(value) in {"-1", "-2"}:
        return f"special_{value}"
    return "seller"


def _shipping_time_text(min_hours: Any, max_hours: Any) -> str | None:
    min_number = _parse_number(min_hours)
    max_number = _parse_number(max_hours)
    if min_number is None or max_number is None:
        return None
    min_days = min_number / 24
    max_days = max_number / 24
    return f"{min_days:g}-{max_days:g} days"


def _lightning_status(start: Any, end: Any) -> str:
    start_seconds = _keepa_seconds_or_none(start)
    end_seconds = _keepa_seconds_or_none(end)
    now = datetime.now(timezone.utc).timestamp()
    if start_seconds is None:
        return "unknown"
    if end == -1:
        return "upcoming"
    if end_seconds is None:
        return "unknown"
    if start_seconds <= now <= end_seconds:
        return "active"
    if end_seconds < now:
        return "past"
    return "upcoming"


def _keepa_seconds_or_none(value: Any) -> int | None:
    if not _is_valid_keepa_time(value):
        return None
    return keepa_minutes_to_unix_seconds(value)


def _data_freshness(stats: dict[str, Any]) -> str:
    if "buyBoxPrice" in stats or "buyBoxSellerId" in stats or "retrievedOfferCount" in stats:
        return "available"
    return "unverified"


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


def _pascal(value: str) -> str:
    return value[:1].upper() + value[1:]
