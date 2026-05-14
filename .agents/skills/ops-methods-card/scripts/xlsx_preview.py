"""读取方法卡分析用 Excel，并输出适合 AI 消费的 JSON 摘要。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _column_index(cell_ref: str) -> int:
    """将 Excel 单元格列名转换为 0-based 索引。"""
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(index - 1, 0)


def _read_shared_strings(zf: ZipFile) -> list[str]:
    """读取 sharedStrings.xml，普通数值型工作簿可能没有该文件。"""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("a:si", NS):
        texts = [node.text or "" for node in item.findall(".//a:t", NS)]
        values.append("".join(texts))
    return values


def _read_sheet_paths(zf: ZipFile) -> list[tuple[str, str]]:
    """读取工作表名称和对应 XML 路径。"""
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_index = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.findall("rel:Relationship", NS)
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib.get(f"{{{NS['r']}}}id")
        target = rel_index.get(rel_id, "")
        if not target:
            continue
        path = target.lstrip("/")
        if not path.startswith("xl/"):
            path = f"xl/{path}"
        sheets.append((sheet.attrib.get("name", "sheet"), path))
    return sheets


def _coerce_value(value: str | None, cell_type: str | None, shared_strings: list[str]):
    """按单元格类型转换值，优先保留数字便于后续统计。"""
    if value is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value)] if value.isdigit() and int(value) < len(shared_strings) else value
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _read_rows(zf: ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[object]]:
    """读取单个 sheet 的二维行数据，补齐空列。"""
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[object]] = []
    for row in root.findall("a:sheetData/a:row", NS):
        values: list[object] = []
        for cell in row.findall("a:c", NS):
            index = _column_index(cell.attrib.get("r", "A1"))
            while len(values) < index:
                values.append("")
            inline_text = cell.find("a:is/a:t", NS)
            node = cell.find("a:v", NS)
            raw_value = inline_text.text if inline_text is not None else (node.text if node is not None else None)
            values.append(_coerce_value(raw_value, cell.attrib.get("t"), shared_strings))
        rows.append(values)
    return rows


def _summarize_numeric(headers: list[str], data_rows: list[list[object]]) -> list[dict]:
    """汇总数值列的基础统计。"""
    summary: list[dict] = []
    for index, header in enumerate(headers):
        numbers: list[float] = []
        for row in data_rows:
            if index >= len(row):
                continue
            value = row[index]
            if isinstance(value, (int, float)):
                numbers.append(float(value))
        if not numbers:
            continue
        summary.append(
            {
                "field": header,
                "count": len(numbers),
                "sum": sum(numbers),
                "min": min(numbers),
                "max": max(numbers),
                "avg": sum(numbers) / len(numbers),
            }
        )
    return summary


def build_preview(path: Path, *, max_rows: int) -> dict:
    """生成 Excel 预览 JSON。"""
    with ZipFile(path) as zf:
        shared_strings = _read_shared_strings(zf)
        sheets = []
        for sheet_name, sheet_path in _read_sheet_paths(zf):
            rows = _read_rows(zf, sheet_path, shared_strings)
            headers = [str(value) for value in rows[0]] if rows else []
            data_rows = rows[1:] if rows else []
            sheets.append(
                {
                    "name": sheet_name,
                    "headers": headers,
                    "row_count": len(data_rows),
                    "preview_rows": data_rows[:max_rows],
                    "numeric_summary": _summarize_numeric(headers, data_rows),
                }
            )
    return {"source": str(path), "sheets": sheets}


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="预览方法卡 Excel 数据")
    parser.add_argument("--input", required=True, help="Excel 文件路径")
    parser.add_argument("--max-rows", type=int, default=20, help="每个 sheet 输出的最大预览行数")
    args = parser.parse_args()

    # Windows 管道输出默认编码可能不是 UTF-8，显式固定以支持中文路径。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    preview = build_preview(Path(args.input), max_rows=max(args.max_rows, 1))
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
