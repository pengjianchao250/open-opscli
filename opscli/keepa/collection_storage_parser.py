"""Keepa 采集结果解析 Adapter。"""

from __future__ import annotations

from pathlib import Path

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

# Parser 版本写入 collection_runs，解析合同变化时递增以便追踪口径。
PARSER_VERSION = "keepa-v3"
# 按 Keepa 常用实体标识依次选择首个非空值作为跨批次业务键。
_BUSINESS_KEY_FIELDS = ("asin", "sellerId", "categoryId")


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
            request_params=files.params,
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
    if not isinstance(sheets, dict) or not sheets:
        raise CollectionParseError("Keepa 格式化 JSON 必须包含非空 sheets 对象")
    ordered = list(sheets.values())
    if not all(isinstance(sheet, dict) for sheet in ordered):
        raise CollectionParseError("Keepa sheets 条目必须是对象")
    main, *additional = ordered
    compatible = {
        "sheet_name": main.get("name"),
        "columns": main.get("columns"),
        "rows": main.get("rows"),
        "additional_sheets": additional,
    }
    return json_datasets(
        compatible,
        source_name="Keepa",
        business_key_fields=_BUSINESS_KEY_FIELDS,
    )
