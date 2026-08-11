"""把 Keepa 格式化工作表导出为支持 SheetN 分页的 JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opscli.keepa.domain.models import KeepaExportResult
from opscli.keepa.export.xlsx import build_formatted_worksheets


def export_rows_to_json(
    *,
    rows: list[Any],
    output_path: Path,
    scenario: str,
    site: str = "US",
    params: dict[str, Any] | None = None,
    extra_sheets: dict[str, list[Any]] | None = None,
) -> KeepaExportResult:
    """按场景把主表与附加表导出为 SheetN JSON，返回文件路径、格式和 MIME 元数据。"""
    sheets: dict[str, dict[str, Any]] = {}
    worksheets = build_formatted_worksheets(
        rows=rows,
        scenario=scenario,
        site=site,
        params=params,
        extra_sheets=extra_sheets,
    )
    for index, worksheet in enumerate(worksheets, start=1):
        sheets[f"Sheet{index}"] = {
            "name": worksheet.name,
            "columns": [column.title for column in worksheet.columns],
            "row_count": len(worksheet.rows),
            "rows": list(worksheet.iter_values()),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {"schema_version": "1.0", "sheets": sheets},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    resolved = output_path.resolve()
    return KeepaExportResult(
        path=str(resolved),
        filename=resolved.name,
        url=resolved.as_uri(),
        format="json",
        mime_type="application/json",
    )
