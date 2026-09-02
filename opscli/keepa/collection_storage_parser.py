"""Keepa 采集结果解析 Adapter。"""

from __future__ import annotations

from pathlib import Path

from opscli.keepa.services.api_manager import extract_rows
from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    ParsedCollection,
)
from opscli.shared.collection_storage.parser_utils import (
    CollectionParseError,
    json_datasets,
    load_result_files,
    read_json_object,
    standard_artifacts,
    xlsx_datasets,
)
from opscli.shared.collection_storage.result_cache import attach_cache_metadata

# Parser 版本写入 collection_runs，解析合同变化时递增以便追踪口径。
PARSER_VERSION = "keepa-v4"
# 按 Keepa 常用实体标识依次选择首个非空值作为跨批次业务键。
_BUSINESS_KEY_FIELDS = ("asin", "sellerId", "categoryId", "catId")


class KeepaCollectionParser:
    """将 Keepa 成功任务转换为通用 Artifact 和 Dataset。"""

    source_system = "keepa"
    parser_version = PARSER_VERSION

    def parse(self, submission: CollectionSubmission) -> ParsedCollection:
        """解析 Keepa 成功合同与 XLSX 导出。"""
        if submission.source_system != self.source_system:
            raise CollectionParseError(
                f"Keepa Parser 不支持来源：{submission.source_system}"
            )
        files = load_result_files(submission, source_name="Keepa")
        export_format = str(
            files.export.get("format") or files.export_path.suffix.lstrip(".")
        ).lower()
        if export_format == "json" or files.export_path.suffix.lower() == ".json":
            datasets = _json_datasets(files.export_path)
        elif export_format in {"xls", "xlsx"} or files.export_path.suffix.lower() == ".xlsx":
            datasets = xlsx_datasets(
                files.export_path,
                source_name="Keepa",
                business_key_fields=_BUSINESS_KEY_FIELDS,
            )
        else:
            raise CollectionParseError(f"不支持的 Keepa 导出格式：{export_format}")
        return ParsedCollection(
            submission=submission,
            parser_version=self.parser_version,
            request_params=attach_cache_metadata(
                files.params,
                cache_key=submission.cache_key,
                cache_scope=submission.cache_scope,
                result_metadata=submission.result_metadata,
            ),
            artifacts=standard_artifacts(
                files,
                default_export_mime_type=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            ),
            datasets=datasets,
        )


def _json_datasets(path: Path):
    payload = read_json_object(path, source_name="Keepa")
    sheets = payload.get("sheets")
    if isinstance(sheets, dict) and sheets:
        worksheet_payload = _v1_sheets_payload(sheets)
    else:
        worksheet_payload = _v2_response_payload(payload)
    return json_datasets(
        worksheet_payload,
        source_name="Keepa",
        business_key_fields=_BUSINESS_KEY_FIELDS,
    )


def _v1_sheets_payload(sheets: dict[str, object]) -> dict[str, object]:
    """把历史 JSON v1 SheetN 合同转换为共享工作表结构。"""
    ordered = list(sheets.values())
    if not all(isinstance(sheet, dict) for sheet in ordered):
        raise CollectionParseError("Keepa sheets 条目必须是对象")
    main, *additional = ordered
    return {
        "sheet_name": main.get("name"),
        "columns": main.get("columns"),
        "rows": main.get("rows"),
        "additional_sheets": additional,
    }


def _v2_response_payload(payload: dict[str, object]) -> dict[str, object]:
    """把 JSON v2 原始响应主对象转换为单个 Dataset，并保留嵌套值。"""
    response = payload.get("response")
    if not isinstance(response, dict):
        raise CollectionParseError("Keepa JSON 必须包含非空 sheets 或 response 对象")
    raw_rows = extract_rows(response)
    scalar_field = _scalar_row_field(response)
    rows = [row if isinstance(row, dict) else {scalar_field: row} for row in raw_rows]
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {
        "sheet_name": f"Keepa {payload.get('scenario') or 'response'}",
        "columns": columns,
        "rows": [[row.get(column) for column in columns] for row in rows],
    }


def _scalar_row_field(response: dict[str, object]) -> str:
    """为 ASIN/Seller ID 标量列表选择可形成业务键的字段名。"""
    if isinstance(response.get("sellerIdList"), list):
        return "sellerId"
    if isinstance(response.get("asinList"), list) or isinstance(
        response.get("bestSellersList"), dict
    ):
        return "asin"
    return "value"
