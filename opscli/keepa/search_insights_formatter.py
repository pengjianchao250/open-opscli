"""Keepa Search Insights Object formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MONEY_FIELDS = {
    "avgBuyBox",
    "avgBuyBox90",
    "avgBuyBox365",
    "avgBuyBoxDeviation",
}

PERCENT_FIELDS = {
    "avgDeltaPercent30BuyBox",
    "avgDeltaPercent90BuyBox",
    "avgDeltaPercent30Amazon",
    "avgDeltaPercent90Amazon",
    "isFBAPercent",
    "soldByAmazonPercent",
    "hasCouponPercent",
}


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


@dataclass
class FormattedSearchInsightsExport:
    main_rows: list[dict[str, Any]]
    brand_rows: list[dict[str, Any]]
    seller_rows: list[dict[str, Any]]
    category_rows: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        sheets: dict[str, list[dict[str, Any]]] = {}
        if self.main_rows:
            sheets["search_insights"] = self.main_rows
        if self.brand_rows:
            sheets["search_insight_brands"] = self.brand_rows
        if self.seller_rows:
            sheets["search_insight_sellers"] = self.seller_rows
        if self.category_rows:
            sheets["search_insight_categories"] = self.category_rows
        return sheets

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_insights": self.main_rows,
            "search_insight_brands": self.brand_rows,
            "search_insight_sellers": self.seller_rows,
            "search_insight_categories": self.category_rows,
        }


def format_search_insights_export(
    search_insights: Any,
    *,
    site: str = "US",
    domain_id: Any = None,
    query_name: str | None = None,
) -> FormattedSearchInsightsExport | None:
    """Format a Keepa Search Insights Object into export tables."""
    if not isinstance(search_insights, dict):
        return None
    main_row = format_search_insights_object(
        search_insights,
        site=site,
        domain_id=domain_id,
        query_name=query_name,
    )
    return FormattedSearchInsightsExport(
        main_rows=[main_row],
        brand_rows=_map_count_rows(
            search_insights.get("topBrandsWithCounts"),
            key_field="brand",
            count_field="productCount",
            query_name=query_name,
        ),
        seller_rows=_map_count_rows(
            search_insights.get("topSellersWithCounts"),
            key_field="sellerId",
            count_field="buyBoxOccurrenceCount",
            query_name=query_name,
        ),
        category_rows=_category_rows(search_insights.get("relatedCategories"), query_name=query_name),
    )


def format_search_insights_object(
    search_insights: dict[str, Any],
    *,
    site: str = "US",
    domain_id: Any = None,
    query_name: str | None = None,
) -> dict[str, Any]:
    """Return a Search Insights Object copy with compact derived fields."""
    currency = _currency_for(site=site, domain_id=domain_id)
    row = dict(search_insights)
    row["rowSource"] = "searchInsights"
    if query_name:
        row["queryName"] = query_name
    if domain_id is not None:
        row["domainId"] = _parse_int(domain_id) or domain_id

    for field in MONEY_FIELDS:
        if field in search_insights:
            row[f"{field}Raw"] = search_insights.get(field)
            row[f"{field}Amount"] = _format_money(search_insights.get(field), currency)
            row[f"{field}Currency"] = currency.code
    for field in PERCENT_FIELDS:
        if field in search_insights:
            row[f"{field}Display"] = _format_percent(search_insights.get(field))

    if "avgRating" in search_insights:
        row["avgRatingRaw"] = search_insights.get("avgRating")
        row["avgRatingStars"] = _format_rating(search_insights.get("avgRating"))

    related_categories = search_insights.get("relatedCategories")
    if isinstance(related_categories, list):
        row["relatedCategoryCount"] = len(related_categories)
        row["relatedCategoriesJoined"] = ", ".join(str(item) for item in related_categories)

    top_brands = search_insights.get("topBrandsWithCounts")
    if isinstance(top_brands, dict):
        row["topBrandCount"] = len(top_brands)
        row["topBrandsJoined"] = _join_map_counts(top_brands)

    top_sellers = search_insights.get("topSellersWithCounts")
    if isinstance(top_sellers, dict):
        row["topSellerCount"] = len(top_sellers)
        row["topSellersJoined"] = _join_map_counts(top_sellers)

    row["currencyCode"] = currency.code
    row["currencyDecimals"] = currency.decimals
    row["searchInsightsRaw"] = search_insights
    return row


def _map_count_rows(
    value: Any,
    *,
    key_field: str,
    count_field: str,
    query_name: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    items = sorted(value.items(), key=lambda item: (-_sortable_count(item[1]), str(item[0])))
    rows: list[dict[str, Any]] = []
    for rank, (key, count) in enumerate(items, start=1):
        row = {"rank": rank, key_field: str(key), count_field: count}
        if query_name:
            row["queryName"] = query_name
        rows.append(row)
    return rows


def _category_rows(value: Any, *, query_name: str | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, category_id in enumerate(value, start=1):
        row = {"index": index, "categoryId": str(category_id)}
        if query_name:
            row["queryName"] = query_name
        rows.append(row)
    return rows


def _currency_for(*, site: str, domain_id: Any = None) -> CurrencyConfig:
    domain = _parse_int(domain_id)
    if domain is None:
        domain = SITE_DOMAIN.get(str(site or "US").upper(), 1)
    return DOMAIN_CURRENCY.get(domain, CurrencyConfig("USD", 2))


def _format_money(value: Any, currency: CurrencyConfig) -> float | int | None:
    number = _parse_number(value)
    if number is None or number in {-1, -2}:
        return None
    amount = number / (10**currency.decimals)
    if currency.decimals == 0:
        return int(amount)
    return round(amount, currency.decimals)


def _format_percent(value: Any) -> str | None:
    number = _parse_number(value)
    if number is None or number in {-1, -2}:
        return None
    return f"{number:g}%"


def _format_rating(value: Any) -> float | None:
    number = _parse_number(value)
    if number is None or number < 0:
        return None
    return number / 10


def _join_map_counts(value: dict[Any, Any]) -> str:
    items = sorted(value.items(), key=lambda item: (-_sortable_count(item[1]), str(item[0])))
    return ", ".join(f"{key}:{count}" for key, count in items)


def _sortable_count(value: Any) -> float:
    """把排行计数转换为稳定排序值，异常值排到末尾。"""
    number = _parse_number(value)
    return number if number is not None else float("-inf")


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
