"""选市场页面结果解析。"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse


def parse_market_research_html(html: str) -> list[dict[str, Any]]:
    """从 /v2/market-research 页面表格提取行数据。"""
    parser = _MarketResearchTableParser()
    parser.feed(html)

    rows: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for cells in parser.rows:
        if len(cells) >= 15:
            pending = _parse_main_row(cells)
            rows.append(pending)
        elif pending and cells:
            _merge_detail_row(pending, cells[0])
            pending = None
    return rows


class _MarketResearchTableParser(HTMLParser):
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
            self._cell = {"parts": [], "links": []}
        elif tag == "a" and self._cell is not None:
            self._cell["links"].append(attributes)
        elif tag == "br" and self._cell is not None:
            self._cell["parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(
                {
                    "lines": _clean_lines(self._cell["parts"]),
                    "links": self._cell["links"],
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
    row: dict[str, Any] = {
        "rank": _number(_first(cells[0])),
        "market": _market_title(cells[1]),
        "marketCn": _market_cn(cells[1]),
        "sampleQuantity": _join_lines(cells[2]),
        "totalSales": _number(_first(cells[3])),
        "avgSales": _number(_nth(cells[4], 0)),
        "headListingAvgSales": _number(_nth(cells[4], 1)),
        "monopoly": _number(_nth(cells[4], 2)),
        "avgRevenue": _number(_nth(cells[5], 0)),
        "headListingAvgRevenue": _number(_nth(cells[5], 1)),
        "avgReviews": _number(_nth(cells[6], 0)),
        "avgRating": _number(_nth(cells[6], 1)),
        "avgBsr": _number(_nth(cells[7], 0)),
        "headListingAvgBsr": _number(_nth(cells[7], 1)),
        "avgSellers": _number(_nth(cells[8], 0)),
        "avgPrice": _number(_last_number_line(cells[8])),
        "sellerTypes": _join_lines(cells[9]),
        "productConcentration": _percent_after_label(cells[10], "商品"),
        "brandConcentration": _percent_after_label(cells[10], "品牌"),
        "sellerConcentration": _percent_after_label(cells[10], "卖家"),
        "newCount": _number(_nth(cells[11], 0)),
        "newRatio": _number(_nth(cells[11], 1)),
        "totalProducts": _number(_first(cells[12])),
        "returnRate": _nth(cells[13], 0),
        "searchPurchaseRatio": _nth(cells[13], 1),
    }
    row.update(_sample_counts(cells[2]))
    row.update(_seller_type_ratios(cells[9]))
    return row


def _merge_detail_row(row: dict[str, Any], cell: dict[str, Any]) -> None:
    path_links = [
        link
        for link in cell.get("links", [])
        if "/v2/market-research?marketId=" in link.get("href", "") and "nodeIdPath=" in link.get("href", "")
    ]
    if path_links:
        last = path_links[-1]
        href = last.get("href", "")
        query = parse_qs(urlparse(href).query)
        row["nodeIdPath"] = (query.get("nodeIdPath") or [""])[0]
        tips = last.get("data-tips") or ""
        if "查询该市场:" in tips:
            row["marketPath"] = tips.split("查询该市场:", 1)[1].strip().replace(" › ", ":")

    lines = cell.get("lines", [])
    row["marketPathCn"] = _path_after(lines, "市场路径(中文):")
    row["ebcRatio"] = _number(_value_after(lines, "A+数量占比:"))
    row["newAvgReviews"] = _number(_value_after(lines, "新品平均评分数:"))
    row["newAvgPrice"] = _number(_value_after(lines, "新品平均价格:"))
    row["newAvgRating"] = _number(_value_after(lines, "新品平均星级:"))
    row["newAvgSales"] = _number(_value_after(lines, "新品月均销量:"))
    row["newAvgRevenue"] = _number(_value_after(lines, "新品月均销售额:"))
    row["avgWeight"] = _value_after(lines, "平均重量:")
    row["avgVolume"] = _value_after(lines, "平均体积:")
    row["avgProfit"] = _number(_value_after(lines, "平均毛利率:"))
    row["sellerNation"] = _value_after(lines, "卖家所属地:")


def _clean_lines(parts: list[str]) -> list[str]:
    text = "".join(parts)
    lines = []
    for line in unescape(text).splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def _first(cell: dict[str, Any]) -> str:
    return _nth(cell, 0)


def _nth(cell: dict[str, Any], index: int) -> str:
    lines = cell.get("lines") or []
    return lines[index] if index < len(lines) else ""


def _market_title(cell: dict[str, Any]) -> str:
    for line in cell.get("lines") or []:
        if not line.startswith("第") and not (line.startswith("(") and line.endswith(")")):
            return line
    return ""


def _market_cn(cell: dict[str, Any]) -> str:
    for line in reversed(cell.get("lines") or []):
        if line.startswith("(") and line.endswith(")"):
            return line[1:-1]
    return ""


def _join_lines(cell: dict[str, Any]) -> str:
    return "\n".join(cell.get("lines") or [])


def _sample_counts(cell: dict[str, Any]) -> dict[str, Any]:
    text = _join_lines(cell)
    return {
        "sampleProducts": _number(_match(text, r"商品:\s*([\d,.]+)")),
        "sampleBrands": _number(_match(text, r"品牌:\s*([\d,.]+)")),
        "sampleSellers": _number(_match(text, r"卖家:\s*([\d,.]+)")),
    }


def _seller_type_ratios(cell: dict[str, Any]) -> dict[str, Any]:
    text = _join_lines(cell)
    return {
        "fbaRatio": _number(_match(text, r"FBA:\s*([\d,.]+%)")),
        "amzRatio": _number(_match(text, r"AMZ:\s*([\d,.]+%)")),
        "fbmRatio": _number(_match(text, r"FBM:\s*([\d,.]+%)")),
    }


def _percent_after_label(cell: dict[str, Any], label: str) -> float | None:
    lines = cell.get("lines") or []
    for index, line in enumerate(lines):
        if line.rstrip(":") == label and index + 1 < len(lines):
            return _number(lines[index + 1])
    return None


def _last_number_line(cell: dict[str, Any]) -> str:
    for line in reversed(cell.get("lines") or []):
        if re.search(r"\d", line):
            return line
    return ""


def _path_after(lines: list[str], label: str) -> str:
    if label not in lines:
        return ""
    start = lines.index(label) + 1
    parts = []
    for line in lines[start:]:
        if line in {"›", "市场分析"}:
            continue
        if ":" in line:
            break
        parts.append(line)
    return ":".join(parts)


def _value_after(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        if line.startswith(label):
            value = line.split(label, 1)[1].strip()
            if value:
                return value
            for next_line in lines[index + 1 : index + 4]:
                if next_line and ":" not in next_line and re.search(r"\d", next_line):
                    return next_line
    return ""


def _number(value: Any) -> float | int | None:
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return None
    matched = re.search(r"-?[\d,.]+", text)
    if not matched:
        return None
    number = matched.group(0).replace(",", "")
    try:
        parsed = float(number)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _match(text: str, pattern: str) -> str:
    matched = re.search(pattern, text)
    return matched.group(1) if matched else ""
