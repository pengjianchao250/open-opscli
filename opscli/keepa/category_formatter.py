"""Keepa Category Object 主表与明细表格式化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.keepa.object_formatting import (
    category_url,
    currency_info,
    money_amount,
    string_id,
)

# Category 主表需要拆出的官方多值字段。
ARRAY_FIELDS = {"children", "relatedCategories", "topBrands"}
# Category Object 中以站点最小货币单位返回的聚合金额字段。
MONEY_FIELDS = {"avgBuyBox", "avgBuyBox90", "avgBuyBox365", "avgBuyBoxDeviation"}
# Keepa 官方约定的“无类目”特殊节点 ID。
BLANK_CATEGORY_ID = "9223372036854775807"


@dataclass
class FormattedCategoryExport:
    """Category Object 的主表和多值明细表。"""

    categories: list[dict[str, Any]]
    children: list[dict[str, Any]]
    related: list[dict[str, Any]]
    brands: list[dict[str, Any]]
    parents: list[dict[str, Any]]
    parent_children: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        """返回非空附加工作表，供 XLSX 与格式化 JSON 共用。"""
        return {
            name: rows
            for name, rows in {
                "category_children": self.children,
                "category_related": self.related,
                "category_brands": self.brands,
                "category_parents": self.parents,
                "category_parent_children": self.parent_children,
            }.items()
            if rows
        }


def format_category_export(
    rows: list[Any],
    *,
    site: str = "US",
    domain_id: Any = None,
    parent_rows: list[Any] | None = None,
) -> FormattedCategoryExport:
    """把 Category Object 列表格式化为主表和多值明细表。

    参数：rows 为原始对象列表，site/domain_id 用于金额和 URL 站点映射。
    parent_rows 为 Category Lookup 可选返回的父级对象列表。
    返回：包含 Category 主表、子类目、相关类目、品牌和父级表的导出对象。
    """
    categories: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []
    brands: list[dict[str, Any]] = []
    currency_code, decimals = currency_info(site=site, domain_id=domain_id)

    for value in rows:
        if not isinstance(value, dict):
            categories.append({"value": value})
            continue
        category_id = string_id(value.get("catId"))
        row = {key: item for key, item in value.items() if key not in ARRAY_FIELDS}
        row["catId"] = category_id
        if "parent" in value:
            row["parent"] = string_id(value.get("parent"))
        row["isBlankCategory"] = category_id == BLANK_CATEGORY_ID
        row["categoryUrl"] = None if row["isBlankCategory"] else category_url(
            category_id, site=site, domain_id=value.get("domainId", domain_id)
        )
        row["currencyCode"] = currency_code
        for field in MONEY_FIELDS:
            if field in value:
                row[f"{field}Amount"] = money_amount(value.get(field), decimals=decimals)
        if isinstance(value.get("avgRating"), (int, float)) and value["avgRating"] >= 0:
            row["avgRatingStars"] = value["avgRating"] / 10
        row["childrenCount"] = len(value.get("children") or [])
        row["relatedCategoryCount"] = len(value.get("relatedCategories") or [])
        row["topBrandCount"] = len(value.get("topBrands") or [])
        categories.append(row)

        children.extend(
            {
                "catId": category_id,
                "childIndex": index,
                "childCategoryId": string_id(child),
            }
            for index, child in enumerate(value.get("children") or [])
        )
        related.extend(
            {
                "catId": category_id,
                "relatedIndex": index,
                "relatedCategoryId": string_id(item),
            }
            for index, item in enumerate(value.get("relatedCategories") or [])
        )
        brands.extend(
            {"catId": category_id, "brandRank": index + 1, "brand": brand}
            for index, brand in enumerate(value.get("topBrands") or [])
        )

    parents: list[dict[str, Any]] = []
    parent_children: list[dict[str, Any]] = []
    for value in parent_rows or []:
        parents.append(_format_parent(value, site=site, domain_id=domain_id))
        if not isinstance(value, dict):
            continue
        parent_id = string_id(value.get("catId"))
        parent_children.extend(
            {
                "parentCategoryId": parent_id,
                "childIndex": index,
                "childCategoryId": string_id(child),
            }
            for index, child in enumerate(value.get("children") or [])
        )
    return FormattedCategoryExport(
        categories, children, related, brands, parents, parent_children
    )


def _format_parent(value: Any, *, site: str, domain_id: Any) -> dict[str, Any]:
    """格式化 Category Lookup 响应中的父级 Category Object。"""
    if not isinstance(value, dict):
        return {"value": value}
    row = {key: item for key, item in value.items() if key not in ARRAY_FIELDS}
    row["catId"] = string_id(value.get("catId"))
    if "parent" in value:
        row["parent"] = string_id(value.get("parent"))
    row["categoryUrl"] = category_url(
        row["catId"], site=site, domain_id=value.get("domainId", domain_id)
    )
    return row
