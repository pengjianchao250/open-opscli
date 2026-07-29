"""关键词选品页面结果解析。"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


def parse_keyword_research_html(html: str) -> list[dict[str, Any]]:
    """从关键词选品页面表格提取官方导出字段。

    参数：
        html: 官网关键词选品页面的完整 HTML 文本。

    返回：
        按官方 28 列导出口径归一化的数据行；页面附加的市场周期保留为扩展字段。

    异常：
        本函数不主动抛出业务异常；页面缺失字段会转换为空值。
    """
    parser = _KeywordResearchTableParser()
    parser.feed(html)

    rows: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    # 官网每条记录由“18 单元格主行 + 1 单元格详情行 + 间隔行”组成，详情必须并入上一主行。
    for cells in parser.rows:
        if len(cells) >= 18:
            pending = _parse_main_row(cells)
            rows.append(pending)
        elif pending and len(cells) == 1 and _first(cells[0]):
            _merge_detail_row(pending, cells[0])
            pending = None
    return rows


class _KeywordResearchTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._in_table = False
        self._table_depth = 0
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "table":
            if self._in_table:
                self._table_depth += 1
            elif attributes.get("id") == "table-condition-search":
                self._in_table = True
                self._table_depth = 1
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = {"parts": [], "elements": []}
        elif self._cell is not None:
            if attributes:
                self._cell["elements"].append({"tag": tag, "attrs": attributes})
            if tag == "br":
                self._cell["parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(
                {
                    "lines": _clean_lines(self._cell["parts"]),
                    "elements": self._cell["elements"],
                }
            )
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)


def _parse_main_row(cells: list[dict[str, Any]]) -> dict[str, Any]:
    # 主行的视觉文本有折行和弹层内容；优先读取 data-keyword，避免把翻译误识别成关键词。
    keyword = _attribute_value(cells[2], "data-keyword") or _first(cells[2])
    keyword_lines = cells[2].get("lines") or []
    translation = ""
    if keyword in keyword_lines:
        index = keyword_lines.index(keyword)
        if index + 1 < len(keyword_lines):
            translation = keyword_lines[index + 1]
    elif len(keyword_lines) > 1:
        translation = keyword_lines[1]

    # 增长、集中度和 PPC 在一个单元格内复合展示，需按页面结构拆成官方导出的独立列。
    yearly, nearly = _growth_pairs(_text(cells[9]))
    concentration = _standalone_percents(cells[10])
    bids = _ppc_values(cells[13])
    review_values = _numbers(_text(cells[16]))
    row: dict[str, Any] = {
        "keyword": keyword,
        "keywordCn": translation,
        "searchRank": _number(_first(cells[11])),
        "searches": _number(_first(cells[5])),
        "searchesCr": _percent(_first(cells[8])),
        "purchases": _number(_nth(cells[6], 0)),
        "purchaseRate": _percent(_nth(cells[6], 1)),
        "impressions": _number(_nth(cells[7], 0)),
        "clicks": _number(_nth(cells[7], 1)),
        "products": _number(_nth(cells[15], 1)),
        "supplyDemandRatio": _number(_nth(cells[15], 0)),
        "spr": None,
        "titleDensity": None,
        "monopolyClickRate": concentration[0] if concentration else None,
        "cvsShareRate": concentration[-1] if len(concentration) > 1 else None,
        "goodsValue": _percent(_first(cells[12])),
        "avgPrice": _currency_text(_nth(cells[16], 0)),
        "avgReviews": review_values[1] if len(review_values) > 1 else None,
        "avgRating": review_values[2] if len(review_values) > 2 else None,
        "bidMin": bids.get("bidMin"),
        "bid": bids.get("bid"),
        "bidMax": bids.get("bidMax"),
        "searchMonthCv": yearly[0] if yearly else None,
        "searchMonthCr": yearly[1] if yearly else None,
        "searchNearlyCv": nearly[0] if nearly else None,
        "searchNearlyCr": nearly[1] if nearly else None,
        "departments": "",
        "gkDatas": [{"asin": asin} for asin in _asins(cells[2])],
    }
    return row


def _merge_detail_row(row: dict[str, Any], cell: dict[str, Any]) -> None:
    lines = cell.get("lines") or []
    row["departments"] = "; ".join(_department_lines(lines))
    row["marketPeriod"] = _market_period(lines)
    row["spr"] = _number(_value_after_label(lines, "SPR:"))
    # 官方工作簿会把标题密度的 N/A 保留为字符串，不能按普通缺失数值转成空白单元格。
    row["titleDensity"] = _number_or_na(_value_after_label(lines, "标题密度:"))


def _clean_lines(parts: list[str]) -> list[str]:
    text = "".join(parts).replace("\u200b", "")
    return [
        line
        for raw_line in unescape(text).splitlines()
        if (line := re.sub(r"\s+", " ", raw_line).strip())
    ]


def _text(cell: dict[str, Any]) -> str:
    return "\n".join(cell.get("lines") or [])


def _first(cell: dict[str, Any]) -> str:
    return _nth(cell, 0)


def _nth(cell: dict[str, Any], index: int) -> str:
    lines = cell.get("lines") or []
    return lines[index] if index < len(lines) else ""


def _attribute_value(cell: dict[str, Any], name: str) -> str:
    for element in cell.get("elements") or []:
        value = element.get("attrs", {}).get(name)
        if value:
            return str(value).strip()
    return ""


def _asins(cell: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for element in cell.get("elements") or []:
        href = str(element.get("attrs", {}).get("href") or "")
        matched = re.search(r"/dp/([A-Z0-9]{10})(?:[/?]|$)", urlparse(href).path + ("?" if "?" in href else ""))
        if matched and matched.group(1) not in values:
            values.append(matched.group(1))
    return values[:10]


def _ppc_values(cell: dict[str, Any]) -> dict[str, float | int | None]:
    raw = ""
    for element in cell.get("elements") or []:
        attrs = element.get("attrs", {})
        if "ppc-item-obj" in attrs:
            raw = str(attrs.get("value") or "")
            break
    values: dict[str, float | int | None] = {}
    for part in raw.split(","):
        key, separator, value = part.partition(":")
        if separator and key in {"bidMin", "bid", "bidMax"}:
            values[key] = _number(value)
    return values


def _growth_pairs(text: str) -> tuple[tuple[float | int, float] | None, tuple[float | int, float] | None]:
    matches = re.findall(r"(-?[\d,]+)\s*\((-?[\d,.]+)%\)", text)
    pairs = [(_number(value), _percent(f"{rate}%")) for value, rate in matches]
    valid = [(value, rate) for value, rate in pairs if value is not None and rate is not None]
    return (valid[0] if valid else None, valid[1] if len(valid) > 1 else None)


def _standalone_percents(cell: dict[str, Any]) -> list[float]:
    values = []
    for line in cell.get("lines") or []:
        if re.fullmatch(r"-?[\d,.]+%", line):
            value = _percent(line)
            if value is not None:
                values.append(value)
    return values


def _department_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    active = False
    for line in lines:
        if line.startswith("所属类目:"):
            active = True
            remainder = line.split("所属类目:", 1)[1].strip()
            if remainder:
                result.append(re.sub(r"\([^)]*\)$", "", remainder).strip())
            continue
        if not active:
            continue
        if line.startswith("市场周期:"):
            break
        cleaned = re.sub(r"\([^)]*\)$", "", line).strip()
        if cleaned:
            result.append(cleaned)
    return result


def _market_period(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if not line.startswith("市场周期:"):
            continue
        value = line.split("市场周期:", 1)[1].strip()
        if value:
            return value
        parts = []
        for next_line in lines[index + 1 :]:
            if next_line.startswith(("SPR:", "标题密度:")):
                break
            parts.append(next_line)
        return "".join(parts)
    return ""


def _value_after_label(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        if not line.startswith(label):
            continue
        value = line.split(label, 1)[1].strip()
        if value:
            return value
        return lines[index + 1] if index + 1 < len(lines) else ""
    return ""


def _currency_text(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return "$0.00"
    return text.replace("\xa0", " ").replace(" ", "")


def _numbers(value: Any) -> list[float | int]:
    return [number for token in re.findall(r"-?[\d,.]+", str(value or "")) if (number := _number(token)) is not None]


def _percent(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else float(number) / 100


def _number(value: Any) -> float | int | None:
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return None
    matched = re.search(r"-?[\d,.]+", text)
    if not matched:
        return None
    try:
        parsed = float(matched.group(0).replace(",", ""))
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _number_or_na(value: Any) -> float | int | str | None:
    """保留官网显式 N/A，其余内容沿用普通数值解析。"""
    text = str(value or "").strip()
    return "N/A" if text.upper() == "N/A" else _number(text)
