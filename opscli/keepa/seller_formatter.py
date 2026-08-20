"""Keepa Seller Object 主表与高基数明细表格式化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.keepa.object_formatting import add_time_fields, string_id

# Seller 主表需要移除并拆到明细表的官方数组/对象字段。
DETAIL_FIELDS = {
    "address",
    "ratingCount",
    "positiveRating",
    "neutralRating",
    "negativeRating",
    "recentFeedback",
    "csv",
    "asinList",
    "asinListLastSeen",
    "sellerCategoryStatistics",
    "sellerBrandStatistics",
    "competitors",
    "customerServicesAddress",
    "totalStorefrontAsins",
}
# 四个评分数组的固定索引顺序来自 Keepa Seller Object 官方定义。
RATING_WINDOWS = (
    ("30_days", "30Days"),
    ("90_days", "90Days"),
    ("365_days", "365Days"),
    ("lifetime", "Lifetime"),
)


@dataclass
class FormattedSellerExport:
    """Seller Object 的主表和明细表集合。"""

    sellers: list[dict[str, Any]]
    ratings: list[dict[str, Any]]
    rating_history: list[dict[str, Any]]
    feedback: list[dict[str, Any]]
    storefront: list[dict[str, Any]]
    categories: list[dict[str, Any]]
    brands: list[dict[str, Any]]
    competitors: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        """返回非空附加工作表，供 XLSX 与格式化 JSON 共用。"""
        return {
            name: rows
            for name, rows in {
                "seller_ratings": self.ratings,
                "seller_rating_history": self.rating_history,
                "seller_feedback": self.feedback,
                "seller_storefront": self.storefront,
                "seller_categories": self.categories,
                "seller_brands": self.brands,
                "seller_competitors": self.competitors,
            }.items()
            if rows
        }


def format_seller_export(
    rows: list[Any], *, site: str = "US", domain_id: Any = None
) -> FormattedSellerExport:
    """把 Seller Object 格式化为可筛选主表和各类明细表。

    参数：rows 为原始对象列表；site/domain_id 保留统一 formatter 调用合同。
    返回：包含卖家主表及评分、反馈、storefront、类目、品牌、竞对明细。
    """
    sellers: list[dict[str, Any]] = []
    ratings: list[dict[str, Any]] = []
    rating_history: list[dict[str, Any]] = []
    feedback: list[dict[str, Any]] = []
    storefront: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    brands: list[dict[str, Any]] = []
    competitors: list[dict[str, Any]] = []

    for value in rows:
        if not isinstance(value, dict):
            sellers.append({"value": value})
            continue
        seller_id = value.get("sellerId")
        row = {key: item for key, item in value.items() if key not in DETAIL_FIELDS}
        for field in ("trackedSince", "trackingSince", "lastUpdate", "lastRatingUpdate"):
            add_time_fields(row, field)
        row["addressText"] = _join_address(value.get("address"))
        row["customerServicesAddressText"] = _join_address(value.get("customerServicesAddress"))
        _add_rating_summary(row, value)
        _add_storefront_summary(row, value)
        row["recentFeedbackCount"] = len(_list(value.get("recentFeedback")))
        row["storefrontAsinRowCount"] = len(_list(value.get("asinList")))
        row["categoryStatisticCount"] = len(_list(value.get("sellerCategoryStatistics")))
        row["brandStatisticCount"] = len(_list(value.get("sellerBrandStatistics")))
        row["competitorCount"] = len(_list(value.get("competitors")))
        sellers.append(row)

        ratings.extend(_rating_rows(value, seller_id=seller_id))
        rating_history.extend(_rating_history_rows(value, seller_id=seller_id))
        feedback.extend(_feedback_rows(value, seller_id=seller_id))
        storefront.extend(_storefront_rows(value, seller_id=seller_id))
        categories.extend(
            _object_rows(
                value.get("sellerCategoryStatistics"),
                seller_id=seller_id,
                id_fields=("catId",),
            )
        )
        brands.extend(
            _object_rows(value.get("sellerBrandStatistics"), seller_id=seller_id)
        )
        competitors.extend(_competitor_rows(value, seller_id=seller_id))

    return FormattedSellerExport(
        sellers,
        ratings,
        rating_history,
        feedback,
        storefront,
        categories,
        brands,
        competitors,
    )


def _add_rating_summary(row: dict[str, Any], seller: dict[str, Any]) -> None:
    for index, (_, suffix) in enumerate(RATING_WINDOWS):
        rating_counts = _list(seller.get("ratingCount"))
        if index < len(rating_counts):
            row[f"rating{suffix}Count"] = rating_counts[index]
        for field in ("positiveRating", "neutralRating", "negativeRating"):
            values = _list(seller.get(field))
            if index < len(values):
                row[f"{field}{suffix}"] = values[index]


def _add_storefront_summary(row: dict[str, Any], seller: dict[str, Any]) -> None:
    values = _list(seller.get("totalStorefrontAsins"))
    if len(values) < 2:
        return
    row["totalStorefrontAsinsLastUpdate"] = values[0]
    row["totalStorefrontAsinCount"] = values[1]
    add_time_fields(row, "totalStorefrontAsinsLastUpdate")


def _rating_rows(seller: dict[str, Any], *, seller_id: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (window, _) in enumerate(RATING_WINDOWS):
        row = {"sellerId": seller_id, "window": window}
        for field in ("ratingCount", "positiveRating", "neutralRating", "negativeRating"):
            values = _list(seller.get(field))
            row[field] = values[index] if index < len(values) else None
        if any(value is not None for key, value in row.items() if key not in {"sellerId", "window"}):
            rows.append(row)
    return rows


def _rating_history_rows(seller: dict[str, Any], *, seller_id: Any) -> list[dict[str, Any]]:
    # Keepa 固定 csv[0] 为评分百分比历史，csv[1] 为评分数量历史；两者均为二元序列。
    csv = _list(seller.get("csv"))
    rows: list[dict[str, Any]] = []
    configs = ((0, "rating", "ratingPercent"), (1, "rating_count", "ratingCount"))
    for series_index, metric, value_field in configs:
        if series_index >= len(csv) or not isinstance(csv[series_index], list):
            continue
        series = csv[series_index]
        for index in range(0, len(series) - 1, 2):
            row = {
                "sellerId": seller_id,
                "metric": metric,
                "keepaTime": series[index],
                value_field: series[index + 1],
            }
            add_time_fields(row, "keepaTime")
            rows.append(row)
    return rows


def _feedback_rows(seller: dict[str, Any], *, seller_id: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(_list(seller.get("recentFeedback"))):
        row = {"sellerId": seller_id, "feedbackIndex": index}
        if isinstance(value, dict):
            row.update(value)
            add_time_fields(row, "date")
            if isinstance(value.get("rating"), (int, float)) and value["rating"] >= 0:
                row["ratingStars"] = value["rating"] / 10
        else:
            row["value"] = value
        rows.append(row)
    return rows


def _storefront_rows(seller: dict[str, Any], *, seller_id: Any) -> list[dict[str, Any]]:
    # 两个数组按相同索引配对；last-seen 缺项时保留 ASIN 并将时间留空，避免丢商品。
    asins = _list(seller.get("asinList"))
    last_seen = _list(seller.get("asinListLastSeen"))
    rows: list[dict[str, Any]] = []
    for index, asin in enumerate(asins):
        row = {
            "sellerId": seller_id,
            "storefrontIndex": index,
            "asin": asin,
            "lastSeen": last_seen[index] if index < len(last_seen) else None,
        }
        add_time_fields(row, "lastSeen")
        rows.append(row)
    return rows


def _object_rows(
    values: Any,
    *,
    seller_id: Any,
    id_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(_list(values)):
        row = {"sellerId": seller_id, "index": index}
        if isinstance(value, dict):
            row.update(value)
            for field in id_fields:
                if field in row:
                    row[field] = string_id(row[field])
        else:
            row["value"] = value
        rows.append(row)
    return rows


def _competitor_rows(seller: dict[str, Any], *, seller_id: Any) -> list[dict[str, Any]]:
    rows = _object_rows(seller.get("competitors"), seller_id=seller_id)
    for row in rows:
        if "sellerId" in row and row["sellerId"] != seller_id:
            row["competitorSellerId"] = row["sellerId"]
            row["sellerId"] = seller_id
    return rows


def _join_address(value: Any) -> str | None:
    if not isinstance(value, list):
        return str(value) if value not in (None, "") else None
    parts = [str(item).strip() for item in value if str(item).strip()]
    return " | ".join(parts) or None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
