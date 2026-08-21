"""Keepa Product Object formatting helpers.

Raw Keepa payloads are preserved by the caller. This module only adds derived
fields and optional export detail tables for Product Object display/export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from opscli.keepa.object_formatting import (
    DOMAIN_CURRENCY_INFO,
    IMAGE_BASE_URL,
    SITE_DOMAIN,
)
from opscli.keepa.stats_formatter import FormattedStatsExport, format_stats_for_product
from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)

# Keepa 数值字段通用的缺失哨兵值。
MISSING_NUMERIC_VALUES = {-1, -2}

# Marketplace Offer 的 condition 数字映射；未知值保留原始数字并标记 unknown。
OFFER_CONDITION_TEXT = {
    1: "new",
    2: "used_like_new",
    3: "used_very_good",
    4: "used_good",
    5: "used_acceptable",
    6: "refurbished",
}

# Product 顶层使用 Keepa Time minutes 的字段白名单。
KEEPA_TIME_FIELDS = {
    "trackingSince",
    "listedSince",
    "lastUpdate",
    "lastPriceChange",
    "lastStockUpdate",
    "lastSoldUpdate",
}

# Product 顶层使用站点最小货币单位的字段白名单。
MONEY_FIELDS = {
    "competitivePriceThreshold",
    "suggestedLowerPrice",
    "variableClosingFee",
}

# Amazon 紧凑日期整数及尺寸/重量字段白名单。
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
# 常用短列表先派生 joined 摘要，再从主表拆到明细表。
JOINED_ARRAY_FIELDS = {"eanList", "upcList", "gtinList", "frequentlyBoughtTogether"}
# Product 主表需要拆到通用列表明细的官方数组字段。
LIST_DETAIL_FIELDS = {
    "buyBoxEligibleOfferCounts",
    "categories",
    "eanList",
    "features",
    "frequentlyBoughtTogether",
    "gtinList",
    "hazardousMaterials",
    "materials",
    "specialFeatures",
    "upcList",
}
# Product 顶层按 Keepa Time/value 二元组返回的历史字段。
PRODUCT_HISTORY_FIELDS = {
    "monthlySoldHistory",
    "parentAsinHistory",
    "salesRankReferenceHistory",
    "rootCategoryHistory",
    "buyBoxSellerIdHistory",
    "buyBoxUsedHistory",
}


@dataclass(frozen=True)
class CurrencyConfig:
    code: str
    decimals: int


# Product formatter 使用不可变币种配置对象，数据来源统一由共用映射维护。
DOMAIN_CURRENCY: dict[int, CurrencyConfig] = {
    domain: CurrencyConfig(*currency)
    for domain, currency in DOMAIN_CURRENCY_INFO.items()
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
    images: list[dict[str, Any]]
    videos: list[dict[str, Any]]
    category_tree: list[dict[str, Any]]
    sales_ranks: list[dict[str, Any]]
    offers: list[dict[str, Any]]
    offer_history: list[dict[str, Any]]
    offer_duplicates: list[dict[str, Any]]
    variations: list[dict[str, Any]]
    variation_attributes: list[dict[str, Any]]
    list_values: list[dict[str, Any]]
    product_history: list[dict[str, Any]]
    nested_values: list[dict[str, Any]]
    stats_price_types: list[dict[str, Any]]
    stats_extremes: list[dict[str, Any]]
    stats_buy_box_sellers: list[dict[str, Any]]
    stats_offer_snapshot: list[dict[str, Any]]
    stats_stock_by_condition: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        sheets: dict[str, list[dict[str, Any]]] = {}
        if self.csv_history:
            sheets["csv_history"] = self.csv_history
        if self.images:
            sheets["images"] = self.images
        if self.videos:
            sheets["product_videos"] = self.videos
        if self.category_tree:
            sheets["category_tree"] = self.category_tree
        if self.sales_ranks:
            sheets["sales_ranks"] = self.sales_ranks
        if self.offers:
            sheets["offers"] = self.offers
        if self.offer_history:
            sheets["offer_history"] = self.offer_history
        if self.offer_duplicates:
            sheets["offer_duplicates"] = self.offer_duplicates
        if self.variations:
            sheets["variations"] = self.variations
        if self.variation_attributes:
            sheets["variation_attributes"] = self.variation_attributes
        if self.list_values:
            sheets["product_list_values"] = self.list_values
        if self.product_history:
            sheets["product_history"] = self.product_history
        if self.nested_values:
            sheets["product_nested_values"] = self.nested_values
        if self.stats_price_types:
            sheets["stats_price_types"] = self.stats_price_types
        if self.stats_extremes:
            sheets["stats_extremes"] = self.stats_extremes
        if self.stats_buy_box_sellers:
            sheets["stats_buy_box_sellers"] = self.stats_buy_box_sellers
        if self.stats_offer_snapshot:
            sheets["stats_offer_snapshot"] = self.stats_offer_snapshot
        if self.stats_stock_by_condition:
            sheets["stats_stock_by_condition"] = self.stats_stock_by_condition
        return sheets

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": self.products,
            "csv_history": self.csv_history,
            "images": self.images,
            "videos": self.videos,
            "category_tree": self.category_tree,
            "sales_ranks": self.sales_ranks,
            "offers": self.offers,
            "offer_history": self.offer_history,
            "offer_duplicates": self.offer_duplicates,
            "variations": self.variations,
            "variation_attributes": self.variation_attributes,
            "list_values": self.list_values,
            "product_history": self.product_history,
            "nested_values": self.nested_values,
            "stats_price_types": self.stats_price_types,
            "stats_extremes": self.stats_extremes,
            "stats_buy_box_sellers": self.stats_buy_box_sellers,
            "stats_offer_snapshot": self.stats_offer_snapshot,
            "stats_stock_by_condition": self.stats_stock_by_condition,
        }


def format_product_export(rows: list[Any], *, site: str = "US", domain_id: Any = None) -> FormattedProductExport:
    """Format Keepa product rows into a main table plus optional detail tables."""
    products: list[dict[str, Any]] = []
    csv_history: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    category_tree: list[dict[str, Any]] = []
    sales_ranks: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    offer_history: list[dict[str, Any]] = []
    offer_duplicates: list[dict[str, Any]] = []
    variations: list[dict[str, Any]] = []
    variation_attributes: list[dict[str, Any]] = []
    list_values: list[dict[str, Any]] = []
    product_history: list[dict[str, Any]] = []
    nested_values: list[dict[str, Any]] = []
    stats_price_types: list[dict[str, Any]] = []
    stats_extremes: list[dict[str, Any]] = []
    stats_buy_box_sellers: list[dict[str, Any]] = []
    stats_offer_snapshot: list[dict[str, Any]] = []
    stats_stock_by_condition: list[dict[str, Any]] = []
    currency = _currency_for(site=site, domain_id=domain_id)

    for row in rows:
        if not isinstance(row, dict):
            products.append({"value": row})
            continue
        stats_export = format_stats_for_product(row, site=site, domain_id=domain_id)
        formatted = format_product_object(row, site=site, domain_id=domain_id, stats_export=stats_export)
        products.append(formatted)
        asin = _string_or_empty(row.get("asin"))
        csv_history.extend(format_csv_history_rows(row, asin=asin, currency=currency))
        images.extend(format_image_rows(row, asin=asin))
        videos.extend(format_video_rows(row, asin=asin))
        category_tree.extend(format_category_tree_rows(row, asin=asin))
        sales_ranks.extend(format_sales_rank_rows(row, asin=asin))
        offers.extend(format_offer_rows(row, asin=asin, currency=currency))
        offer_history.extend(format_offer_history_rows(row, asin=asin, currency=currency))
        offer_duplicates.extend(format_offer_duplicate_rows(row, asin=asin, currency=currency))
        variations.extend(format_variation_rows(row, asin=asin))
        variation_attributes.extend(format_variation_attribute_rows(row, asin=asin))
        list_values.extend(format_list_value_rows(row, asin=asin))
        product_history.extend(
            format_product_history_rows(row, asin=asin, currency=currency)
        )
        nested_values.extend(format_unhandled_nested_rows(row, asin=asin))
        if stats_export:
            stats_price_types.extend(stats_export.price_type_rows)
            stats_extremes.extend(stats_export.extreme_rows)
            stats_buy_box_sellers.extend(stats_export.buy_box_seller_rows)
            stats_offer_snapshot.extend(stats_export.offer_snapshot_rows)
            stats_stock_by_condition.extend(stats_export.stock_by_condition_rows)

    return FormattedProductExport(
        products=products,
        csv_history=csv_history,
        images=images,
        videos=videos,
        category_tree=category_tree,
        sales_ranks=sales_ranks,
        offers=offers,
        offer_history=offer_history,
        offer_duplicates=offer_duplicates,
        variations=variations,
        variation_attributes=variation_attributes,
        list_values=list_values,
        product_history=product_history,
        nested_values=nested_values,
        stats_price_types=stats_price_types,
        stats_extremes=stats_extremes,
        stats_buy_box_sellers=stats_buy_box_sellers,
        stats_offer_snapshot=stats_offer_snapshot,
        stats_stock_by_condition=stats_stock_by_condition,
    )


def format_product_object(
    product: dict[str, Any],
    *,
    site: str = "US",
    domain_id: Any = None,
    stats_export: FormattedStatsExport | None = None,
) -> dict[str, Any]:
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
    _add_unit_count_fields(row)
    _add_images_fields(row)
    _add_category_fields(row)
    _add_variation_summary(row)
    _add_content_summary(row)
    _add_coupon_fields(row, currency)
    _add_stats_current_fields(row, product, currency)
    if stats_export:
        row.update(stats_export.main_fields)

    row["currencyCode"] = currency.code
    row["currencyDecimals"] = currency.decimals
    for field in {
        "images",
        "imagesCSV",
        "csv",
        "offers",
        "liveOffersOrder",
        "variations",
        "stats",
        "categoryTree",
        "salesRanks",
        "monthlySoldHistory",
        "buyBoxSellerIdHistory",
        "buyBoxUsedHistory",
        "rootCategoryHistory",
        "fbaFees",
        "unitCount",
        "coupon",
    } | LIST_DETAIL_FIELDS | PRODUCT_HISTORY_FIELDS:
        row.pop(field, None)
    row.pop("imageUrls", None)
    row.pop("variationAsins", None)
    # Keepa 会持续新增对象字段；未识别的嵌套值已进入 product_nested_values，主表只保留标量。
    for field, value in list(row.items()):
        if isinstance(value, (dict, list)):
            row.pop(field)
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


def format_offer_rows(
    product: dict[str, Any], *, asin: str, currency: CurrencyConfig | None = None
) -> list[dict[str, Any]]:
    offers = product.get("offers")
    if not isinstance(offers, list):
        return []
    currency = currency or _currency_for(site="US", domain_id=product.get("domainId"))
    live_order = product.get("liveOffersOrder")
    live_rank_by_index = {
        offer_index: rank for rank, offer_index in enumerate(live_order, start=1)
    } if isinstance(live_order, list) else {}

    rows: list[dict[str, Any]] = []
    for index, offer in enumerate(offers):
        if not isinstance(offer, dict):
            rows.append({"asin": asin, "offerIndex": index, "rawOffer": offer})
            continue
        row: dict[str, Any] = {
            "asin": asin,
            "offerIndex": index,
            "liveOfferRank": live_rank_by_index.get(index),
        }
        row.update(
            {
                key: value
                for key, value in offer.items()
                if not isinstance(value, (dict, list))
            }
        )
        if "condition" in offer:
            condition = _parse_number(offer.get("condition"))
            row["conditionText"] = OFFER_CONDITION_TEXT.get(condition, "unknown")
        for field in ("price", "shipping", "primeExcl"):
            if field in offer:
                row[f"{field}Amount"] = _format_money(offer.get(field), currency)
                row[f"{field}Currency"] = currency.code
        if "coupon" in offer:
            _apply_coupon_history_value(
                row, label="coupon", value=offer.get("coupon"), currency=currency
            )
        for field in ("lastSeen", "lastStockUpdate"):
            _add_keepa_time_fields(row, field)
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
        row: dict[str, Any] = {
            "parentAsin": asin,
            "variationIndex": index,
            "attributesText": _attributes_text(attributes),
        }
        row.update(
            {
                key: value
                for key, value in variation.items()
                if key != "attributes" and not isinstance(value, (dict, list))
            }
        )
        rows.append(row)
    return rows


def format_image_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """把 Product 图片对象或旧版 imagesCSV 拆成图片明细。"""
    rows: list[dict[str, Any]] = []
    images = product.get("images")
    if isinstance(images, list):
        for index, image in enumerate(images):
            row: dict[str, Any] = {"asin": asin, "imageIndex": index}
            if isinstance(image, dict):
                row.update({key: value for key, value in image.items() if not isinstance(value, (dict, list))})
                filename = image.get("l") or image.get("m") or image.get("s")
                row["imageFilename"] = filename
                row["imageUrl"] = _image_url(filename) if filename else None
                row["width"] = image.get("w") or image.get("width")
                row["height"] = image.get("h") or image.get("height")
            else:
                row["imageFilename"] = image
                row["imageUrl"] = _image_url(str(image)) if image else None
            rows.append(row)
        return rows

    for index, filename in enumerate(_image_names_from_csv(product.get("imagesCSV"))):
        rows.append(
            {
                "asin": asin,
                "imageIndex": index,
                "variant": "MAIN" if index == 0 else f"PT{index:02d}",
                "imageFilename": filename,
                "imageUrl": _image_url(filename),
            }
        )
    return rows


def format_video_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """把 Product 视频对象拆成视频明细，避免通用 path 表难以直接分析。"""
    values = product.get("videos")
    if not isinstance(values, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        row: dict[str, Any] = {"asin": asin, "videoIndex": index}
        if isinstance(value, dict):
            row.update(
                {
                    key: item
                    for key, item in value.items()
                    if not isinstance(item, (dict, list))
                }
            )
            if value.get("image"):
                row["imageUrl"] = _image_url(str(value["image"]))
        else:
            row["value"] = value
        rows.append(row)
    return rows


def format_category_tree_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """把 Product categoryTree 拆成有序路径明细。"""
    tree = product.get("categoryTree")
    if not isinstance(tree, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(tree):
        row = {"asin": asin, "categoryLevel": index}
        if isinstance(value, dict):
            row.update({key: item for key, item in value.items() if not isinstance(item, (dict, list))})
            if "catId" in row:
                row["catId"] = _string_or_empty(row["catId"])
        else:
            row["value"] = value
        rows.append(row)
    return rows


def format_sales_rank_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """把 salesRanks 中的类目历史序列拆成长表。"""
    values = product.get("salesRanks")
    if not isinstance(values, dict):
        return []
    rows: list[dict[str, Any]] = []
    for category_id, series in values.items():
        if not isinstance(series, list):
            continue
        for pair in _iter_series_values(series, 2):
            row = {
                "asin": asin,
                "categoryId": str(category_id),
                "keepaTime": pair[0],
                "salesRank": pair[1] if len(pair) > 1 else None,
            }
            _add_keepa_time_fields(row, "keepaTime")
            rows.append(row)
    return rows


def format_offer_history_rows(
    product: dict[str, Any], *, asin: str, currency: CurrencyConfig
) -> list[dict[str, Any]]:
    """把 Offer 的价格、库存、Prime 专享价与优惠券历史拆成长表。"""
    rows: list[dict[str, Any]] = []
    offers = product.get("offers")
    if not isinstance(offers, list):
        return rows
    configs = (
        ("offerCSV", "offer_price", 3),
        ("stockCSV", "stock", 2),
        ("primeExclCSV", "prime_exclusive_price", 2),
        ("couponHistory", "coupon", 2),
    )
    for offer_index, offer in enumerate(offers):
        if not isinstance(offer, dict):
            continue
        for field, history_type, tuple_size in configs:
            series = offer.get(field)
            if not isinstance(series, list):
                continue
            for values in _iter_series_values(series, tuple_size):
                row = {
                    "asin": asin,
                    "offerIndex": offer_index,
                    "offerId": offer.get("offerId"),
                    "sellerId": offer.get("sellerId"),
                    "historyType": history_type,
                    "keepaTime": values[0],
                }
                _add_keepa_time_fields(row, "keepaTime")
                if len(values) > 1:
                    if history_type == "coupon":
                        row["coupon"] = values[1]
                        _apply_coupon_history_value(
                            row, label="coupon", value=values[1], currency=currency
                        )
                    elif history_type in {"offer_price", "prime_exclusive_price"}:
                        row["price"] = values[1]
                        row["priceAmount"] = _format_money(values[1], currency)
                    else:
                        row["stock"] = values[1]
                if history_type == "offer_price" and len(values) > 2:
                    row["shipping"] = values[2]
                    row["shippingAmount"] = _format_money(values[2], currency)
                rows.append(row)
    return rows


def format_offer_duplicate_rows(
    product: dict[str, Any], *, asin: str, currency: CurrencyConfig
) -> list[dict[str, Any]]:
    """把每个 Offer 的重复报价对象拆成独立明细。"""
    rows: list[dict[str, Any]] = []
    offers = product.get("offers")
    if not isinstance(offers, list):
        return rows
    for offer_index, offer in enumerate(offers):
        if not isinstance(offer, dict) or not isinstance(offer.get("offerDuplicates"), list):
            continue
        for index, value in enumerate(offer["offerDuplicates"]):
            row = {"asin": asin, "offerIndex": offer_index, "duplicateIndex": index}
            if isinstance(value, dict):
                row.update({key: item for key, item in value.items() if not isinstance(item, (dict, list))})
                for field in ("price", "shipping"):
                    if field in value:
                        row[f"{field}Amount"] = _format_money(value[field], currency)
            else:
                row["value"] = value
            rows.append(row)
    return rows


def format_variation_attribute_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """把每个变体的 dimension/value 属性拆成长表。"""
    rows: list[dict[str, Any]] = []
    variations = product.get("variations")
    if not isinstance(variations, list):
        return rows
    for variation_index, variation in enumerate(variations):
        if not isinstance(variation, dict) or not isinstance(variation.get("attributes"), list):
            continue
        for attribute_index, value in enumerate(variation["attributes"]):
            row = {
                "parentAsin": asin,
                "asin": variation.get("asin"),
                "variationIndex": variation_index,
                "attributeIndex": attribute_index,
            }
            if isinstance(value, dict):
                row.update(value)
            else:
                row["value"] = value
            rows.append(row)
    return rows


def format_list_value_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """把 Product 简单数组拆成长表，避免主表出现超长多行单元格。"""
    rows: list[dict[str, Any]] = []
    for field in sorted(LIST_DETAIL_FIELDS):
        values = product.get(field)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            row = {"asin": asin, "field": field, "index": index}
            if isinstance(value, dict):
                row.update({key: item for key, item in value.items() if not isinstance(item, (dict, list))})
            else:
                row["value"] = value
            rows.append(row)
    return rows


def format_product_history_rows(
    product: dict[str, Any], *, asin: str, currency: CurrencyConfig
) -> list[dict[str, Any]]:
    """把 Product 顶层 Keepa Time/value 历史数组拆成长表。"""
    rows: list[dict[str, Any]] = []
    for field in sorted(PRODUCT_HISTORY_FIELDS):
        series = product.get(field)
        if not isinstance(series, list):
            continue
        for values in _iter_series_values(series, 2):
            row = {
                "asin": asin,
                "field": field,
                "keepaTime": values[0],
                "value": values[1] if len(values) > 1 else None,
            }
            _add_keepa_time_fields(row, "keepaTime")
            rows.append(row)
    coupon_history = product.get("couponHistory")
    if isinstance(coupon_history, list):
        for values in _iter_series_values(coupon_history, 3):
            row = {
                "asin": asin,
                "field": "couponHistory",
                "keepaTime": values[0],
            }
            _add_keepa_time_fields(row, "keepaTime")
            if len(values) > 1:
                _apply_coupon_history_value(
                    row, label="oneTimeCoupon", value=values[1], currency=currency
                )
            if len(values) > 2:
                _apply_coupon_history_value(
                    row, label="snsCoupon", value=values[2], currency=currency
                )
            rows.append(row)
    return rows


def _apply_coupon_history_value(
    row: dict[str, Any], *, label: str, value: Any, currency: CurrencyConfig
) -> None:
    """按 Keepa 正数金额、负数百分比规则展开 Coupon 历史值。"""
    number = _parse_number(value)
    row[label] = value
    if number is None or number in MISSING_NUMERIC_VALUES or number == 0:
        return
    if number > 0:
        row[f"{label}Amount"] = _format_money(number, currency)
        row[f"{label}Currency"] = currency.code
    else:
        row[f"{label}Percent"] = abs(number)


def format_unhandled_nested_rows(product: dict[str, Any], *, asin: str) -> list[dict[str, Any]]:
    """递归拆分尚无专用 Sheet 的嵌套字段，确保新版字段不落入主表大单元格。"""
    handled = {
        "images",
        "imagesCSV",
        "categoryTree",
        "salesRanks",
        "offers",
        "liveOffersOrder",
        "variations",
        "csv",
        "stats",
        "fbaFees",
        "unitCount",
        "coupon",
        "couponHistory",
        "videos",
    } | LIST_DETAIL_FIELDS | PRODUCT_HISTORY_FIELDS
    rows: list[dict[str, Any]] = []
    for field, value in product.items():
        if field in handled or not isinstance(value, (dict, list)):
            continue
        _append_nested_leaves(rows, asin=asin, field=field, path=field, value=value)
    return rows


def _append_nested_leaves(
    rows: list[dict[str, Any]],
    *,
    asin: str,
    field: str,
    path: str,
    value: Any,
) -> None:
    """深度优先输出嵌套对象的标量叶子，并以 path 保留原始位置。"""
    if isinstance(value, dict):
        if not value:
            rows.append({"asin": asin, "field": field, "path": path, "value": None, "containerType": "object"})
        for key, child in value.items():
            _append_nested_leaves(
                rows, asin=asin, field=field, path=f"{path}.{key}", value=child
            )
        return
    if isinstance(value, list):
        if not value:
            rows.append({"asin": asin, "field": field, "path": path, "value": None, "containerType": "array"})
        for index, child in enumerate(value):
            _append_nested_leaves(
                rows, asin=asin, field=field, path=f"{path}[{index}]", value=child
            )
        return
    rows.append({"asin": asin, "field": field, "path": path, "value": value})


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


def _add_unit_count_fields(row: dict[str, Any]) -> None:
    """把 unitCount 小对象展开到 Product 主表。"""
    unit_count = row.get("unitCount")
    if not isinstance(unit_count, dict):
        return
    for key, value in unit_count.items():
        suffix = key[:1].upper() + key[1:]
        row[f"unitCount{suffix}"] = value


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


def _image_names_from_csv(value: Any) -> list[str]:
    """解析旧版 imagesCSV 中的图片文件名。"""
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _image_url(image_name: str) -> str:
    if image_name.startswith(("http://", "https://")):
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
            row[field] = None if value in MISSING_NUMERIC_VALUES else value


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
        row["rank"] = None if value in MISSING_NUMERIC_VALUES else value
    elif config.kind == "count":
        row["count"] = None if value in MISSING_NUMERIC_VALUES else value
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
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc).date().isoformat()
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
