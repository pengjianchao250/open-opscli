"""Keepa Product Object formatting helpers.

Raw Keepa payloads are preserved by the caller. This module only adds derived
fields and optional export detail tables for Product Object display/export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)


MISSING_NUMERIC_VALUES = {-1}
IMAGE_BASE_URL = "https://m.media-amazon.com/images/I"

KEEPA_TIME_FIELDS = {
    "trackingSince",
    "listedSince",
    "lastUpdate",
    "lastPriceChange",
    "lastStockUpdate",
    "lastSoldUpdate",
}

MONEY_FIELDS = {
    "competitivePriceThreshold",
    "suggestedLowerPrice",
    "variableClosingFee",
}

DATE_INT_FIELDS = {"publicationDate", "releaseDate"}
DIMENSION_MM_FIELDS = {
    "packageHeight",
    "packageLength",
    "packageWidth",
    "itemHeight",
    "itemLength",
    "itemWidth",
}
WEIGHT_GRAM_FIELDS = {"packageWeight", "itemWeight"}
JOINED_ARRAY_FIELDS = {"eanList", "upcList", "gtinList", "frequentlyBoughtTogether"}


@dataclass(frozen=True)
class CurrencyConfig:
    code: str
    decimals: int


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


@dataclass(frozen=True)
class CsvSeriesConfig:
    name: str
    kind: str
    tuple_size: int = 2


CSV_SERIES: dict[int, CsvSeriesConfig] = {
    0: CsvSeriesConfig("AMAZON", "price"),
    1: CsvSeriesConfig("NEW", "price"),
    2: CsvSeriesConfig("USED", "price"),
    3: CsvSeriesConfig("SALES", "rank"),
    4: CsvSeriesConfig("LISTPRICE", "price"),
    5: CsvSeriesConfig("COLLECTIBLE", "price"),
    6: CsvSeriesConfig("REFURBISHED", "price"),
    7: CsvSeriesConfig("NEW_FBM_SHIPPING", "shipping_price", 3),
    8: CsvSeriesConfig("LIGHTNING_DEAL", "price"),
    9: CsvSeriesConfig("WAREHOUSE", "price"),
    10: CsvSeriesConfig("NEW_FBA", "price"),
    11: CsvSeriesConfig("COUNT_NEW", "count"),
    12: CsvSeriesConfig("COUNT_USED", "count"),
    13: CsvSeriesConfig("COUNT_REFURBISHED", "count"),
    14: CsvSeriesConfig("COUNT_COLLECTIBLE", "count"),
    15: CsvSeriesConfig("EXTRA_INFO_UPDATES", "event"),
    16: CsvSeriesConfig("RATING", "rating"),
    17: CsvSeriesConfig("COUNT_REVIEWS", "count"),
    18: CsvSeriesConfig("BUY_BOX_SHIPPING", "shipping_price", 3),
    19: CsvSeriesConfig("USED_NEW_SHIPPING", "shipping_price", 3),
    20: CsvSeriesConfig("USED_VERY_GOOD_SHIPPING", "shipping_price", 3),
    21: CsvSeriesConfig("USED_GOOD_SHIPPING", "shipping_price", 3),
    22: CsvSeriesConfig("USED_ACCEPTABLE_SHIPPING", "shipping_price", 3),
    23: CsvSeriesConfig("COLLECTIBLE_NEW_SHIPPING", "shipping_price", 3),
    24: CsvSeriesConfig("COLLECTIBLE_VERY_GOOD_SHIPPING", "shipping_price", 3),
    25: CsvSeriesConfig("COLLECTIBLE_GOOD_SHIPPING", "shipping_price", 3),
    26: CsvSeriesConfig("COLLECTIBLE_ACCEPTABLE_SHIPPING", "shipping_price", 3),
    27: CsvSeriesConfig("REFURBISHED_SHIPPING", "shipping_price", 3),
    28: CsvSeriesConfig("EBAY_NEW_SHIPPING", "shipping_price", 3),
    29: CsvSeriesConfig("EBAY_USED_SHIPPING", "shipping_price", 3),
    30: CsvSeriesConfig("TRADE_IN", "price"),
    31: CsvSeriesConfig("RENTAL", "price"),
    32: CsvSeriesConfig("BUY_BOX_USED_SHIPPING", "shipping_price", 3),
    33: CsvSeriesConfig("PRIME_EXCL", "price"),
    34: CsvSeriesConfig("COUNT_NEW_FBA", "count"),
    35: CsvSeriesConfig("COUNT_NEW_FBM", "count"),
}

CURRENT_FIELD_BY_INDEX = {
    0: "currentAmazonPrice",
    1: "currentNewPrice",
    2: "currentUsedPrice",
    3: "currentSalesRank",
    4: "currentListPrice",
    10: "currentNewFbaPrice",
    16: "currentRating",
    17: "currentReviewCount",
    18: "currentBuyBoxPrice",
    34: "currentNewFbaOfferCount",
    35: "currentNewFbmOfferCount",
}


@dataclass
class FormattedProductExport:
    products: list[dict[str, Any]]
    csv_history: list[dict[str, Any]]
    offers: list[dict[str, Any]]
    variations: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        sheets: dict[str, list[dict[str, Any]]] = {}
        if self.csv_history:
            sheets["csv_history"] = self.csv_history
        if self.offers:
            sheets["offers"] = self.offers
        if self.variations:
            sheets["variations"] = self.variations
        return sheets

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": self.products,
            "csv_history": self.csv_history,
            "offers": self.offers,
            "variations": self.variations,
        }


def format_product_export(rows: list[Any], *, site: str = "US", domain_id: Any = None) -> FormattedProductExport:
    """Format Keepa product rows into a main table plus optional detail tables."""
    products: list[dict[str, Any]] = []
    csv_history: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    variations: list[dict[str, Any]] = []
    currency = _currency_for(site=site, domain_id=domain_id)

    for row in rows:
        if not isinstance(row, dict):
            products.append({"value": row})
            continue
        formatted = format_product_object(row, site=site, domain_id=domain_id)
        products.append(formatted)
        asin = _string_or_empty(row.get("asin"))
        csv_history.extend(format_csv_history_rows(row, asin=asin, currency=currency))
        offers.extend(format_offer_rows(row, asin=asin))
        variations.extend(format_variation_rows(row, asin=asin))

    return FormattedProductExport(products=products, csv_history=csv_history, offers=offers, variations=variations)


def format_product_object(product: dict[str, Any], *, site: str = "US", domain_id: Any = None) -> dict[str, Any]:
    """Return a Product Object copy with compact derived fields appended."""
    currency = _currency_for(site=site, domain_id=domain_id or product.get("domainId"))
    row = dict(product)

    for field in KEEPA_TIME_FIELDS:
        _add_keepa_time_fields(row, field)
    for field in MONEY_FIELDS:
        _add_money_field(row, field, currency)
    for field in DATE_INT_FIELDS:
        _add_date_int_field(row, field)
    for field in DIMENSION_MM_FIELDS:
        _add_dimension_field(row, field)
    for field in WEIGHT_GRAM_FIELDS:
        _add_weight_field(row, field)
    for field in JOINED_ARRAY_FIELDS:
        _add_joined_array_field(row, field)

    _add_fba_fee_fields(row, currency)
    _add_images_fields(row)
    _add_category_fields(row)
    _add_variation_summary(row)
    _add_content_summary(row)
    _add_coupon_fields(row, currency)
    _add_stats_current_fields(row, product, currency)

    row["currencyCode"] = currency.code
    row["currencyDecimals"] = currency.decimals
    return row


def format_csv_history_rows(
    product: dict[str, Any],
    *,
    asin: str,
    currency: CurrencyConfig,
) -> list[dict[str, Any]]:
    csv = product.get("csv")
    if not isinstance(csv, list):
        return []

    rows: list[dict[str, Any]] = []
    for csv_index, series in enumerate(csv):
        if not isinstance(series, list) or not series:
            continue
        config = CSV_SERIES.get(csv_index, CsvSeriesConfig(f"CSV_{csv_index}", "value"))
        for values in _iter_series_values(series, config.tuple_size):
            history_row = _base_history_row(asin=asin, csv_index=csv_index, config=config, keepa_time=values[0])
            if len(values) > 1:
                _apply_csv_value(history_row, value=values[1], config=config, currency=currency)
            if config.tuple_size == 3 and len(values) > 2:
                shipping = values[2]
                history_row["shipping"] = shipping
                history_row["shippingAmount"] = _format_money(shipping, currency)
            if csv_index in {28, 29}:
                history_row["sourceReliability"] = "low"
            rows.append(history_row)
    return rows


def format_offer_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    offers = product.get("offers")
    if not isinstance(offers, list):
        return []
    live_order = product.get("liveOffersOrder")
    live_rank_by_index = {
        offer_index: rank for rank, offer_index in enumerate(live_order, start=1)
    } if isinstance(live_order, list) else {}

    rows: list[dict[str, Any]] = []
    for index, offer in enumerate(offers):
        if not isinstance(offer, dict):
            rows.append({"asin": asin, "offerIndex": index, "rawOffer": offer})
            continue
        row = {
            "asin": asin,
            "offerIndex": index,
            "liveOfferRank": live_rank_by_index.get(index),
            "sellerId": offer.get("sellerId"),
            "condition": offer.get("condition"),
            "isFBA": offer.get("isFBA"),
            "isPrime": offer.get("isPrime"),
            "isAmazon": offer.get("isAmazon"),
            "isMAP": offer.get("isMAP"),
            "shipsFromChina": offer.get("shipsFromChina"),
            "offer": offer,
        }
        rows.append(row)
    return rows


def format_variation_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    variations = product.get("variations")
    if not isinstance(variations, list):
        return []

    rows: list[dict[str, Any]] = []
    for index, variation in enumerate(variations):
        if not isinstance(variation, dict):
            rows.append({"parentAsin": asin, "variationIndex": index, "variation": variation})
            continue
        attributes = variation.get("attributes")
        row = {
            "parentAsin": asin,
            "variationIndex": index,
            "asin": variation.get("asin"),
            "image": variation.get("image"),
            "attributesText": _attributes_text(attributes),
            "attributes": attributes,
            "variation": variation,
        }
        rows.append(row)
    return rows


def _currency_for(*, site: str, domain_id: Any = None) -> CurrencyConfig:
    domain = _parse_int(domain_id)
    if domain is None:
        domain = SITE_DOMAIN.get(str(site or "US").upper(), 1)
    return DOMAIN_CURRENCY.get(domain, CurrencyConfig("USD", 2))


def _add_keepa_time_fields(row: dict[str, Any], field: str) -> None:
    value = row.get(field)
    if not _is_valid_keepa_time(value):
        return
    row[f"{field}UnixSeconds"] = keepa_minutes_to_unix_seconds(value)
    row[f"{field}UnixMilliseconds"] = keepa_minutes_to_unix_milliseconds(value)
    row[f"{field}Utc"] = keepa_minutes_to_utc_iso(value)


def _add_money_field(row: dict[str, Any], field: str, currency: CurrencyConfig) -> None:
    if field not in row:
        return
    row[f"{field}Amount"] = _format_money(row.get(field), currency)
    row[f"{field}Currency"] = currency.code


def _add_date_int_field(row: dict[str, Any], field: str) -> None:
    formatted = _format_date_int(row.get(field))
    if formatted is not None:
        row[f"{field}Formatted"] = formatted


def _add_dimension_field(row: dict[str, Any], field: str) -> None:
    value = _parse_number(row.get(field))
    if value is None or value <= 0:
        return
    row[f"{field}Cm"] = round(value / 10, 2)


def _add_weight_field(row: dict[str, Any], field: str) -> None:
    value = _parse_number(row.get(field))
    if value is None or value <= 0:
        return
    row[f"{field}Kg"] = round(value / 1000, 4)


def _add_joined_array_field(row: dict[str, Any], field: str) -> None:
    value = row.get(field)
    if isinstance(value, list):
        row[f"{field}Joined"] = ", ".join(str(item) for item in value)


def _add_fba_fee_fields(row: dict[str, Any], currency: CurrencyConfig) -> None:
    fba_fees = row.get("fbaFees")
    if not isinstance(fba_fees, dict):
        return
    if "pickAndPackFee" in fba_fees:
        row["fbaPickAndPackFeeAmount"] = _format_money(fba_fees.get("pickAndPackFee"), currency)
        row["fbaPickAndPackFeeCurrency"] = currency.code
    last_update = fba_fees.get("lastUpdate")
    if _is_valid_keepa_time(last_update):
        row["fbaFeesLastUpdateUtc"] = keepa_minutes_to_utc_iso(last_update)


def _add_images_fields(row: dict[str, Any]) -> None:
    urls = _image_urls(row)
    if not urls:
        return
    row["imagesCount"] = len(urls)
    row["mainImageUrl"] = urls[0]
    row["imageUrls"] = urls
    row["imageUrlsJoined"] = "\n".join(urls)


def _image_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    images = row.get("images")
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            for key in ("l", "m"):
                image_name = image.get(key)
                if isinstance(image_name, str) and image_name.strip():
                    urls.append(_image_url(image_name))
                    break
    images_csv = row.get("imagesCSV")
    if isinstance(images_csv, str):
        for image_name in images_csv.split(","):
            if image_name.strip():
                urls.append(_image_url(image_name.strip()))
    return _unique(urls)


def _image_url(image_name: str) -> str:
    if image_name.startswith("http://") or image_name.startswith("https://"):
        return image_name
    return f"{IMAGE_BASE_URL}/{image_name.lstrip('/')}"


def _add_category_fields(row: dict[str, Any]) -> None:
    category_tree = row.get("categoryTree")
    if not isinstance(category_tree, list):
        return
    names: list[str] = []
    ids: list[str] = []
    for category in category_tree:
        if not isinstance(category, dict):
            continue
        name = category.get("name")
        cat_id = category.get("catId")
        if name is not None:
            names.append(str(name))
        if cat_id is not None:
            ids.append(str(cat_id))
    if names:
        row["categoryPathName"] = " > ".join(names)
    if ids:
        row["categoryPathId"] = " > ".join(ids)


def _add_variation_summary(row: dict[str, Any]) -> None:
    variations = row.get("variations")
    if not isinstance(variations, list):
        return
    asins = [
        str(variation.get("asin"))
        for variation in variations
        if isinstance(variation, dict) and variation.get("asin")
    ]
    row["variationCount"] = len(variations)
    row["variationAsins"] = asins
    row["variationAsinsJoined"] = ", ".join(asins)


def _add_content_summary(row: dict[str, Any]) -> None:
    a_plus = row.get("aPlus")
    if a_plus is not None:
        row["hasAPlus"] = bool(a_plus)
        row["aPlusImageCount"] = _count_nested_image_refs(a_plus)
    videos = row.get("videos")
    if isinstance(videos, list):
        row["videoCount"] = len(videos)
    hazardous_materials = row.get("hazardousMaterials")
    if isinstance(hazardous_materials, list):
        row["hazardousMaterialCount"] = len(hazardous_materials)
    deals = row.get("deals")
    if isinstance(deals, list):
        row["dealCount"] = len(deals)


def _add_coupon_fields(row: dict[str, Any], currency: CurrencyConfig) -> None:
    coupon = row.get("coupon")
    if not isinstance(coupon, list):
        return
    labels = ("couponOneTime", "couponSNS")
    for index, label in enumerate(labels):
        if index >= len(coupon):
            continue
        value = _parse_number(coupon[index])
        if value is None or value == 0:
            continue
        if value > 0:
            row[f"{label}Amount"] = _format_money(value, currency)
            row[f"{label}Currency"] = currency.code
        else:
            row[f"{label}Percent"] = abs(value)


def _add_stats_current_fields(row: dict[str, Any], product: dict[str, Any], currency: CurrencyConfig) -> None:
    current = None
    stats = product.get("stats")
    if isinstance(stats, dict) and isinstance(stats.get("current"), list):
        current = stats.get("current")
    for csv_index, field in CURRENT_FIELD_BY_INDEX.items():
        value = _stats_value(current, csv_index)
        if value is None:
            value = _latest_csv_value(product.get("csv"), csv_index)
        if value is None:
            continue
        config = CSV_SERIES.get(csv_index, CsvSeriesConfig(f"CSV_{csv_index}", "value"))
        if config.kind in {"price", "shipping_price"}:
            row[field] = _format_money(value, currency)
            row[f"{field}Currency"] = currency.code
        elif config.kind == "rating":
            rating = _parse_number(value)
            row[field] = None if rating is None or rating < 0 else rating / 10
        else:
            row[field] = None if value == -1 else value


def _iter_series_values(series: list[Any], tuple_size: int) -> list[list[Any]]:
    values: list[list[Any]] = []
    index = 0
    while index < len(series):
        chunk = series[index : index + tuple_size]
        if len(chunk) < tuple_size:
            chunk = series[index:]
        values.append(chunk)
        index += tuple_size
    return values


def _base_history_row(*, asin: str, csv_index: int, config: CsvSeriesConfig, keepa_time: Any) -> dict[str, Any]:
    row = {
        "asin": asin,
        "csvIndex": csv_index,
        "csvName": config.name,
        "valueKind": config.kind,
        "keepaTime": keepa_time,
    }
    if _is_valid_keepa_time(keepa_time):
        row["unixSeconds"] = keepa_minutes_to_unix_seconds(keepa_time)
        row["unixMilliseconds"] = keepa_minutes_to_unix_milliseconds(keepa_time)
        row["utc"] = keepa_minutes_to_utc_iso(keepa_time)
    return row


def _apply_csv_value(row: dict[str, Any], *, value: Any, config: CsvSeriesConfig, currency: CurrencyConfig) -> None:
    row["value"] = value
    if config.kind in {"price", "shipping_price"}:
        row["price"] = value
        row["priceAmount"] = _format_money(value, currency)
        row["currencyCode"] = currency.code
        row["currencyDecimals"] = currency.decimals
    elif config.kind == "rating":
        row["ratingX10"] = value
        number = _parse_number(value)
        row["rating"] = None if number is None or number < 0 else number / 10
    elif config.kind == "rank":
        row["rank"] = None if value == -1 else value
    elif config.kind == "count":
        row["count"] = None if value == -1 else value
    elif config.kind == "event":
        number = _parse_number(value)
        if number is None:
            return
        row["fetchedOfferCount"] = abs(number)
        row["hasMoreOffers"] = number < 0


def _format_money(value: Any, currency: CurrencyConfig) -> float | int | None:
    number = _parse_number(value)
    if number is None or number in MISSING_NUMERIC_VALUES:
        return None
    amount = number / (10**currency.decimals)
    if currency.decimals == 0:
        return int(amount)
    return round(amount, currency.decimals)


def _format_date_int(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text or text == "-1" or text == "0":
        return None
    if not re.fullmatch(r"\d{4}(\d{2}){0,2}", text):
        return None
    if len(text) == 4:
        return text
    if len(text) == 6:
        return f"{text[:4]}-{text[4:]}"
    if len(text) == 8:
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    return None


def _latest_csv_value(csv: Any, csv_index: int) -> Any:
    if not isinstance(csv, list) or csv_index >= len(csv):
        return None
    series = csv[csv_index]
    if not isinstance(series, list) or len(series) < 2:
        return None
    config = CSV_SERIES.get(csv_index, CsvSeriesConfig(f"CSV_{csv_index}", "value"))
    tuple_size = config.tuple_size
    if len(series) < tuple_size:
        return None
    return series[-tuple_size + 1]


def _stats_value(current: Any, csv_index: int) -> Any:
    if not isinstance(current, list) or csv_index >= len(current):
        return None
    return current[csv_index]


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


def _attributes_text(attributes: Any) -> str:
    if not isinstance(attributes, list):
        return ""
    parts: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        dimension = attribute.get("dimension") or attribute.get("name")
        value = attribute.get("value")
        if dimension is not None and value is not None:
            parts.append(f"{dimension}={value}")
    return "; ".join(parts)


def _count_nested_image_refs(value: Any) -> int:
    if isinstance(value, dict):
        count = 0
        for key, child in value.items():
            if isinstance(key, str) and "image" in key.lower() and child:
                count += 1
            count += _count_nested_image_refs(child)
        return count
    if isinstance(value, list):
        return sum(_count_nested_image_refs(item) for item in value)
    if isinstance(value, str) and (".jpg" in value.lower() or ".png" in value.lower()):
        return 1
    return 0


def _string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
