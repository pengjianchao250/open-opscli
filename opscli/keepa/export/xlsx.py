"""Keepa XLSX export."""

from __future__ import annotations

import json
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

from opscli.keepa.domain.exceptions import KeepaConfigError
from opscli.keepa.domain.models import KeepaExportResult


@dataclass(frozen=True)
class ExportColumn:
    title: str
    source: str | None = None
    transform: str | None = None
    fallback: str | None = None


PRODUCT_COLUMNS = [
    ExportColumn("ASIN", "asin"),
    ExportColumn("父ASIN", "parentAsin"),
    ExportColumn("标题", "title"),
    ExportColumn("品牌", "brand"),
    ExportColumn("制造商", "manufacturer"),
    ExportColumn("产品组", "productGroup"),
    ExportColumn("类目树", "categoryTree", "categoryTree"),
    ExportColumn("根类目", "rootCategory"),
    ExportColumn("上架时间(UTC)", "listedSinceUtc"),
    ExportColumn("最近更新(UTC)", "lastUpdateUtc"),
    ExportColumn("最近价格变化(UTC)", "lastPriceChangeUtc"),
    ExportColumn("评分", "stats.current.16", "rating"),
    ExportColumn("评论数", "stats.current.17", "emptyIfNegative"),
    ExportColumn("月销量", "monthlySold"),
    ExportColumn("当前Buy Box价格", "stats.current.18", "price"),
    ExportColumn("当前Amazon价格", "stats.current.0", "price"),
    ExportColumn("当前新品价格", "stats.current.1", "price"),
    ExportColumn("当前二手价格", "stats.current.2", "price"),
    ExportColumn("当前销售排名", "stats.current.3", "emptyIfNegative"),
    ExportColumn("Buy Box卖家ID", "buyBoxSellerId"),
    ExportColumn("FBA Offer数", "fbaFees.pickAndPackFee", "price"),
    ExportColumn("主图链接", "imagesCSV", "firstImage"),
    ExportColumn("Amazon链接", "asin", "amazonProductUrl"),
]

ASIN_COLUMNS = [
    ExportColumn("ASIN", "asin"),
    ExportColumn("Amazon链接", "asin", "amazonProductUrl"),
]

SELLER_COLUMNS = [
    ExportColumn("Seller ID", "sellerId"),
    ExportColumn("店铺名称", "sellerName", fallback="name"),
    ExportColumn("最近更新(UTC)", "lastUpdateUtc"),
    ExportColumn("评分", "rating"),
    ExportColumn("评分数", "ratingCount"),
    ExportColumn("店铺ASIN数", "asinList", "listLength"),
    ExportColumn("店铺链接", "sellerId", "amazonSellerUrl"),
]

CATEGORY_COLUMNS = [
    ExportColumn("类目ID", "catId", fallback="categoryId"),
    ExportColumn("类目名称", "name"),
    ExportColumn("父类目ID", "parent"),
    ExportColumn("产品数量", "productCount"),
    ExportColumn("最高排名", "highestRank"),
    ExportColumn("子类目", "children", "listJoin"),
]

GENERIC_COLUMNS = [
    ExportColumn("ASIN", "asin"),
    ExportColumn("标题", "title"),
    ExportColumn("品牌", "brand"),
    ExportColumn("最近更新(UTC)", "lastUpdateUtc"),
    ExportColumn("原始数据", None, "rowJson"),
]


def export_rows_to_xlsx(
    *,
    rows: list[Any],
    output_path: Path,
    scenario: str,
    site: str = "US",
    params: dict[str, Any] | None = None,
) -> KeepaExportResult:
    """Export Keepa rows to a user-friendly XLSX workbook."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:
        raise KeepaConfigError("缺少 openpyxl 依赖，无法导出 XLSX") from exc

    normalized_rows = [_normalize_row(row) for row in rows]
    columns = _columns_for_scenario(scenario, normalized_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _safe_sheet_title(_sheet_title(scenario=scenario, site=site, params=params or {}, rows=rows))

    header_fill = PatternFill("solid", fgColor="EAF2F8")
    header_font = Font(bold=True)
    for column_index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=column_index, value=column.title)
        cell.font = header_font
        cell.fill = header_fill

    for row_index, row in enumerate(normalized_rows, start=2):
        for column_index, column in enumerate(columns, start=1):
            value = _cell_value(_column_value(row, column, site=site))
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            _apply_number_format(cell)

    sheet.freeze_panes = "A2"
    for column_index, column in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(column_index)].width = _column_width(column.title)

    workbook.save(output_path)
    resolved = output_path.resolve()
    return KeepaExportResult(path=str(resolved), filename=resolved.name, url=resolved.as_uri())


def _columns_for_scenario(scenario: str, rows: list[dict[str, Any]]) -> list[ExportColumn]:
    if scenario in {"product", "product-search", "product-finder", "deals", "lightning-deals"}:
        if rows and all(set(row.keys()) <= {"asin"} for row in rows):
            return ASIN_COLUMNS
        return PRODUCT_COLUMNS
    if scenario in {"seller", "top-seller"}:
        return SELLER_COLUMNS
    if scenario in {"category-search", "category-lookup", "bestsellers"}:
        if rows and all(set(row.keys()) <= {"asin"} for row in rows):
            return ASIN_COLUMNS
        return CATEGORY_COLUMNS
    return _generic_columns(rows)


def _generic_columns(rows: list[dict[str, Any]]) -> list[ExportColumn]:
    if not rows:
        return GENERIC_COLUMNS
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen and not isinstance(row.get(key), (dict, list)):
                seen.add(key)
                fields.append(key)
            if len(fields) >= 24:
                break
    return [ExportColumn(_title_for_field(field), field) for field in fields] or GENERIC_COLUMNS


def _normalize_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, str):
        return {"asin": row}
    return {"value": row}


def _column_value(row: dict[str, Any], column: ExportColumn, *, site: str) -> Any:
    value = row if column.source is None else _get_value(row, column.source)
    if _is_blank(value) and column.fallback:
        value = _get_value(row, column.fallback)
    return _apply_transform(value, column.transform, row, site=site)


def _get_value(row: dict[str, Any], field: str) -> Any:
    value: Any = row
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if index < len(value) else None
        else:
            return None
    return value


def _apply_transform(value: Any, transform: str | None, row: dict[str, Any], *, site: str) -> Any:
    if transform is None:
        return value
    if transform == "emptyIfNegative":
        return "" if _is_number(value) and float(value) < 0 else value
    if transform == "price":
        return "" if _is_blank(value) or (_is_number(value) and float(value) < 0) else round(float(value) / 100, 2)
    if transform == "rating":
        if _is_blank(value) or (_is_number(value) and float(value) < 0):
            return ""
        return round(float(value) / 10, 1)
    if transform == "firstImage":
        return _first_image_url(value)
    if transform == "amazonProductUrl":
        asin = value or row.get("asin")
        return f"https://{_amazon_domain(site)}/dp/{asin}" if asin else ""
    if transform == "amazonSellerUrl":
        return f"https://{_amazon_domain(site)}/sp?seller={value}" if value else ""
    if transform == "categoryTree":
        return _category_tree(value)
    if transform == "listLength":
        return len(value) if isinstance(value, list) else ""
    if transform == "listJoin":
        return _list_join(value)
    if transform == "rowJson":
        return json.dumps(row, ensure_ascii=False)
    return value


def _cell_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _apply_number_format(cell) -> None:
    value = cell.value
    if isinstance(value, bool) or not isinstance(value, Real):
        return
    cell.number_format = "#,##0" if float(value).is_integer() else "#,##0.00"


def _first_image_url(value: Any) -> str:
    if not value:
        return ""
    first = str(value).split(",")[0].strip()
    if not first:
        return ""
    if first.startswith("http"):
        return first
    return f"https://m.media-amazon.com/images/I/{first}"


def _category_tree(value: Any) -> str:
    if not isinstance(value, list):
        return "" if _is_blank(value) else str(value)
    labels = []
    for item in value:
        if isinstance(item, dict):
            labels.append(str(item.get("name") or item.get("catId") or item.get("id") or ""))
        elif item is not None:
            labels.append(str(item))
    return " > ".join(label for label in labels if label)


def _list_join(value: Any) -> str:
    if not isinstance(value, list):
        return "" if _is_blank(value) else str(value)
    return ", ".join(str(item) for item in value if item is not None)


def _sheet_title(*, scenario: str, site: str, params: dict[str, Any], rows: list[Any]) -> str:
    target = params.get("keyword") or params.get("term") or params.get("asin") or params.get("seller") or ""
    suffix = f"-{target}" if target else ""
    return f"Keepa-{site.upper()}-{scenario}{suffix}({len(rows)})"


def _safe_sheet_title(value: str) -> str:
    title = "".join(char for char in value if char not in r"[]:*?/\\")
    return (title or "Keepa")[:31]


def _column_width(title: str) -> int:
    if any(key in title for key in ["标题", "原始数据", "类目树"]):
        return 48
    if any(key in title for key in ["链接"]):
        return 38
    if any(key in title for key in ["ASIN", "品牌", "Seller"]):
        return 18
    return max(12, min(24, len(str(title)) * 2 + 4))


def _title_for_field(field: str) -> str:
    titles = {
        "asin": "ASIN",
        "title": "标题",
        "brand": "品牌",
        "manufacturer": "制造商",
        "lastUpdateUtc": "最近更新(UTC)",
        "lastUpdate": "最近更新(Keepa分钟)",
    }
    return titles.get(field, field)


def _amazon_domain(site: str) -> str:
    domains = {
        "US": "www.amazon.com",
        "GB": "www.amazon.co.uk",
        "UK": "www.amazon.co.uk",
        "DE": "www.amazon.de",
        "FR": "www.amazon.fr",
        "JP": "www.amazon.co.jp",
        "CA": "www.amazon.ca",
        "IT": "www.amazon.it",
        "ES": "www.amazon.es",
        "IN": "www.amazon.in",
        "MX": "www.amazon.com.mx",
        "BR": "www.amazon.com.br",
    }
    return domains.get(str(site or "US").upper(), "www.amazon.com")


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
