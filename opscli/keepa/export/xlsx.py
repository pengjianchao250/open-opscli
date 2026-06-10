"""Keepa XLSX export."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opscli.keepa.domain.exceptions import KeepaConfigError
from opscli.keepa.domain.models import KeepaExportResult


@dataclass(frozen=True)
class ExportColumn:
    title: str
    source: str


EMPTY_COLUMNS = [ExportColumn("原始数据", "value")]

EXCLUDED_FIELDS = {
    "timestamp",
    "tokensLeft",
    "tokensConsumed",
    "refillIn",
    "refillRate",
    "rowSource",
}

FIELD_TITLES = {
    "asin": "ASIN",
    "asins": "ASIN列表",
    "parentAsin": "父ASIN",
    "title": "标题",
    "brand": "品牌",
    "manufacturer": "制造商",
    "productGroup": "产品组",
    "categoryTree": "类目树",
    "rootCategory": "根类目",
    "categories": "类目",
    "categoryId": "类目ID",
    "catId": "类目ID",
    "name": "名称",
    "parent": "父类目ID",
    "children": "子类目",
    "productCount": "产品数量",
    "highestRank": "最高排名",
    "sellerId": "Seller ID",
    "sellerName": "店铺名称",
    "businessName": "公司名称",
    "sellerBrand": "卖家品牌",
    "rating": "评分",
    "ratingCount": "评分数",
    "asinList": "ASIN列表",
    "sellerIdList": "Seller ID列表",
    "monthlySold": "月销量",
    "buyBoxSellerId": "Buy Box卖家ID",
    "imagesCSV": "图片CSV",
    "description": "描述",
    "features": "五点描述",
    "lastUpdate": "最近更新(Keepa分钟)",
    "lastUpdateUtc": "最近更新(UTC)",
    "lastUpdateUnixSeconds": "最近更新Unix秒",
    "lastUpdateUnixMilliseconds": "最近更新Unix毫秒",
    "listedSince": "上架时间(Keepa分钟)",
    "listedSinceUtc": "上架时间(UTC)",
    "lastPriceChange": "最近价格变化(Keepa分钟)",
    "lastPriceChangeUtc": "最近价格变化(UTC)",
    "stats": "统计数据",
    "csv": "CSV原始数据",
    "offers": "Offer数据",
    "fbaFees": "FBA费用",
    "variations": "变体",
    "eans": "EAN",
    "eanList": "EAN列表",
    "upcList": "UPC列表",
    "model": "型号",
    "color": "颜色",
    "size": "尺寸",
    "packageHeight": "包装高度",
    "packageLength": "包装长度",
    "packageWidth": "包装宽度",
    "packageWeight": "包装重量",
    "itemHeight": "商品高度",
    "itemLength": "商品长度",
    "itemWidth": "商品宽度",
    "itemWeight": "商品重量",
    "isAdultProduct": "成人产品",
    "isEligibleForTradeIn": "可Trade-In",
    "isEligibleForSuperSaverShipping": "可Super Saver配送",
    "trackingSince": "跟踪开始时间(Keepa分钟)",
    "totalResults": "总结果数",
    "timestamp": "响应时间戳",
    "tokensLeft": "剩余Token",
    "tokensConsumed": "消耗Token",
    "refillIn": "Token恢复倒计时",
    "refillRate": "Token恢复速率",
    "rowSource": "行来源",
    "productsRaw": "products原始数据",
    "sellersRaw": "sellers原始数据",
    "categoriesRaw": "categories原始数据",
    "dealsRaw": "deals原始数据",
    "bestSellersListRaw": "bestSellersList原始数据",
    "asinListRaw": "asinList原始数据",
    "sellerIdListRaw": "sellerIdList原始数据",
    "lightningDealsRaw": "lightningDeals原始数据",
    "trackingsRaw": "trackings原始数据",
    "notificationsRaw": "notifications原始数据",
    "value": "原始数据",
}

EXCEL_CELL_LIMIT = 32767


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

    normalized_rows = [_normalize_row(row, scenario=scenario) for row in rows]
    columns = _columns_from_rows(normalized_rows)

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
            sheet.cell(row=row_index, column=column_index, value=_cell_value(row.get(column.source)))

    sheet.freeze_panes = "A2"
    for column_index, column in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(column_index)].width = _column_width(column.title)

    workbook.save(output_path)
    resolved = output_path.resolve()
    return KeepaExportResult(path=str(resolved), filename=resolved.name, url=resolved.as_uri())


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[ExportColumn]:
    if not rows:
        return EMPTY_COLUMNS
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key in EXCLUDED_FIELDS:
                continue
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return [ExportColumn(_title_for_field(field), field) for field in fields] or EMPTY_COLUMNS


def _normalize_row(row: Any, *, scenario: str) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, str):
        if scenario in {"seller", "top-seller"}:
            return {"sellerId": row}
        return {"asin": row}
    return {"value": row}


def _cell_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and len(value) > EXCEL_CELL_LIMIT:
        return value[:EXCEL_CELL_LIMIT]
    return value


def _sheet_title(*, scenario: str, site: str, params: dict[str, Any], rows: list[Any]) -> str:
    target = params.get("keyword") or params.get("term") or params.get("asin") or params.get("seller") or ""
    suffix = f"-{target}" if target else ""
    return f"Keepa-{site.upper()}-{scenario}{suffix}({len(rows)})"


def _safe_sheet_title(value: str) -> str:
    title = "".join(char for char in value if char not in r"[]:*?/\\")
    return (title or "Keepa")[:31]


def _column_width(title: str) -> int:
    if any(key in title for key in ["标题", "原始数据", "类目树", "统计数据", "CSV原始数据", "Offer数据"]):
        return 48
    if any(key in title for key in ["ASIN", "品牌", "Seller"]):
        return 18
    return max(12, min(24, len(str(title)) * 2 + 4))


def _title_for_field(field: str) -> str:
    # 暂停 XLSX 表头中文翻译，保持与 Keepa API 字段名一致，避免字段含义不清晰。
    return field
    # return FIELD_TITLES.get(field, field)
