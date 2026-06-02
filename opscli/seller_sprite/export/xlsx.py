"""卖家精灵 XLSX 导出。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError
from opscli.seller_sprite.domain.models import SellerSpriteExportResult
from opscli.seller_sprite.export.columns import ExportColumn, columns_for_scenario

def export_rows_to_xlsx(
    *,
    rows: list[dict[str, Any]],
    output_path: Path,
    scenario: str,
    site: str = "US",
    period: str = "30d",
    params: dict[str, Any] | None = None,
    high_frequency_rows: list[dict[str, Any]] | None = None,
) -> SellerSpriteExportResult:
    """将接口 rows 导出为 XLSX。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:
        raise SellerSpriteConfigError("缺少 openpyxl 依赖，无法导出 XLSX") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns_for_scenario(scenario, site)
    if not columns:
        columns = [ExportColumn(dictionary_title, dictionary_title) for dictionary_title in _collect_fields(rows)]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _main_sheet_title(scenario=scenario, site=site, period=period, params=params or {}, rows=rows)

    header_fill = PatternFill("solid", fgColor="EAF2F8")
    header_font = Font(bold=True)
    for column_index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=column_index, value=column.title)
        cell.font = header_font
        cell.fill = header_fill

    for row_index, row in enumerate(rows, start=2):
        for column_index, column in enumerate(columns, start=1):
            sheet.cell(row=row_index, column=column_index, value=_cell_value(_column_value(row, column)))

    sheet.freeze_panes = "A2"
    for column_index, column in enumerate(columns, start=1):
        width = _column_width(column.title)
        sheet.column_dimensions[get_column_letter(column_index)].width = width

    if high_frequency_rows:
        _add_high_frequency_sheet(workbook, high_frequency_rows)

    workbook.save(output_path)
    resolved_output = output_path.resolve()
    return SellerSpriteExportResult(
        path=str(resolved_output),
        filename=resolved_output.name,
        url=resolved_output.as_uri(),
    )


def _collect_fields(rows: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return fields


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


def _column_value(row: dict[str, Any], column: ExportColumn) -> Any:
    if column.source is None:
        return ""
    value = _get_value(row, column.source)
    if _is_blank(value) and column.fallback:
        value = _get_value(row, column.fallback)
    return _apply_transform(value, column.transform, row)


def _apply_transform(value: Any, transform: str | None, row: dict[str, Any]) -> Any:
    if not transform:
        return value
    if transform == "emptyIfNegative":
        return "" if _is_number(value) and float(value) < 0 else value
    if transform == "jsonObjectLines":
        return _json_object_lines(value)
    if transform == "amazonProductUrl":
        return _amazon_product_url(value, row)
    if transform == "amazonSellerUrl":
        return _amazon_seller_url(value, row)
    if transform == "badgeFlag":
        return "" if _is_blank(value) else "Y"
    if transform == "amazonChoiceKeyword":
        return "" if _is_blank(value) else "Amazon's Choice"
    if transform == "booleanY":
        return "Y" if bool(value) else ""
    if transform == "departmentsJoin":
        return _departments_join(value)
    if transform == "yen":
        return "" if _is_blank(value) else f"円{float(value):.2f}"
    if transform == "bidRange":
        return _bid_range(row)
    if transform == "asinList":
        return _asin_list(value)
    if transform == "listJoin":
        return _list_join(value)
    return value


def _cell_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _add_high_frequency_sheet(workbook, rows: list[dict[str, Any]]) -> None:
    from openpyxl.styles import Font

    sheet = workbook.create_sheet("Unique Words")
    headers = ["词语", "出现频次", "百分比"]
    for column_index, title in enumerate(headers, start=1):
        sheet.cell(row=1, column=column_index, value=title)
        sheet.cell(row=1, column=column_index).font = Font(bold=True)
    for row_index, row in enumerate(rows, start=2):
        sheet.cell(row=row_index, column=1, value=row.get("keyword") or row.get("词语") or row.get("word"))
        sheet.cell(row=row_index, column=2, value=row.get("frequency") or row.get("出现频次"))
        sheet.cell(row=row_index, column=3, value=row.get("percentage") or row.get("百分比"))
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 14


def _main_sheet_title(*, scenario: str, site: str, period: str, params: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if scenario == "keyword-miner":
        keyword = params.get("keyword") or params.get("q") or "keyword"
        title = f"{site.upper()}-{keyword}({len(rows)})_"
    elif scenario == "keyword-reverse":
        asin = params.get("asin") or params.get("q") or "ASIN"
        title = f"{site.upper()}-{asin}-Keywords({len(rows)})_"
    elif scenario == "product-research":
        title = f"Product-{site.upper()}-{_period_label(period)}"
    elif scenario == "competitor-lookup":
        title = f"Competitor-{site.upper()}-{_period_label(period)}"
    elif scenario == "market-research":
        title = f"Market-research-{site.upper()}-{_period_label(period)}"
    else:
        title = scenario
    return _safe_sheet_title(title)


def _safe_sheet_title(value: str) -> str:
    title = "".join(char for char in value if char not in r"[]:*?/\\")
    return (title or "seller-sprite")[:31]


def _period_label(period: str) -> str:
    text = str(period or "")
    if text in {"30d", "nearly", "latest30", "last30", ""}:
        return "Last-30-days"
    return text.replace("-", "")


def _column_width(title: str) -> int:
    if any(key in title for key in ["标题", "详细参数", "卖家信息"]):
        return 48
    if any(key in title for key in ["链接", "主图", "前十ASIN"]):
        return 38
    if any(key in title for key in ["类目路径", "尺寸"]):
        return 32
    if any(key in title for key in ["ASIN", "SKU", "品牌"]):
        return 18
    return max(12, min(22, len(str(title)) * 2 + 4))


def _json_object_lines(value: Any) -> Any:
    if _is_blank(value):
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    if not isinstance(value, dict):
        return value
    return "\n".join(f"{key}:{item}" for key, item in value.items())


def _amazon_product_url(value: Any, row: dict[str, Any]) -> str:
    if str(value or "").startswith("http"):
        return str(value)
    asin = value or row.get("asin")
    return f"https://{_amazon_domain(row)}/dp/{asin}" if asin else ""


def _amazon_seller_url(value: Any, row: dict[str, Any]) -> str:
    if not value:
        return ""
    return f"https://{_amazon_domain(row)}/gp/help/seller/at-a-glance.html?seller={value}"


def _amazon_domain(row: dict[str, Any]) -> str:
    station = str(row.get("station") or "").upper()
    market_id = row.get("marketId")
    if station == "JAPAN" or market_id == 6:
        return "www.amazon.co.jp"
    if station == "GERMANY" or market_id == 4:
        return "www.amazon.de"
    if station == "UNITED_KINGDOM" or market_id == 3:
        return "www.amazon.co.uk"
    if station == "CANADA" or market_id == 7:
        return "www.amazon.ca"
    if station == "FRANCE" or market_id == 5:
        return "www.amazon.fr"
    if station == "ITALY" or market_id == 8:
        return "www.amazon.it"
    if station == "SPAIN" or market_id == 9:
        return "www.amazon.es"
    if station == "INDIA" or market_id == 10:
        return "www.amazon.in"
    return "www.amazon.com"


def _departments_join(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "&".join(str(item.get("label")) for item in value if isinstance(item, dict) and item.get("label"))


def _bid_range(row: dict[str, Any]) -> str:
    bid_min = row.get("bidMin")
    bid_max = row.get("bidMax")
    if _is_blank(bid_min) or _is_blank(bid_max):
        return "-"
    return f"円{float(bid_min):.2f}-円{float(bid_max):.2f}"


def _asin_list(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return ",".join(str(item.get("asin")) for item in value if isinstance(item, dict) and item.get("asin"))


def _list_join(value: Any) -> str:
    if not isinstance(value, list):
        return "" if _is_blank(value) else str(value)
    parts = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(item.get("label") or item.get("name") or item.get("code") or item.get("value") or json.dumps(item, ensure_ascii=False)))
        elif item is not None:
            parts.append(str(item))
    return "/".join(part for part in parts if part)


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
