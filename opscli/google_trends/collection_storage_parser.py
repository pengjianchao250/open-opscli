"""Google Trends 采集结果解析 Adapter。"""

from __future__ import annotations

from typing import Any

from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    ParsedCollection,
)
from opscli.shared.collection_storage.parser_utils import (
    CollectionParseError,
    json_datasets,
    load_result_files,
    standard_artifacts,
)

# Parser 版本写入 collection_runs，解析合同变化时递增以便追踪口径。
PARSER_VERSION = "google-trends-v1"
# 按常见趋势结果实体依次选择首个非空值作为跨批次业务键。
_BUSINESS_KEY_FIELDS = (
    "date",
    "search_term",
    "query",
    "topic_id",
    "geo",
    "geoCode",
    "title",
    "mid",
)


class GoogleTrendsCollectionParser:
    """将 Google Trends 成功任务转换为通用 Artifact 和 Dataset。"""

    source_system = "google_trends"
    parser_version = PARSER_VERSION

    def parse(self, submission: CollectionSubmission) -> ParsedCollection:
        """解析 Google Trends 成功合同与规范化结果数据。

        Args:
            submission: Outbox 中的 Google Trends 成功任务。

        Returns:
            可交给共享 MySQL Adapter 的完整采集文档。

        Raises:
            CollectionParseError: 结果合同、制品路径或导出格式不合法。
        """
        if submission.source_system != self.source_system:
            raise CollectionParseError(
                f"Google Trends Parser 不支持来源：{submission.source_system}"
            )
        files = load_result_files(submission, source_name="Google Trends")
        export_format = str(
            files.export.get("format") or files.export_path.suffix.lstrip(".")
        ).lower()
        if export_format == "json" or files.export_path.suffix.lower() == ".json":
            default_mime_type = "application/json"
        elif (
            export_format in {"xls", "xlsx"}
            or files.export_path.suffix.lower() == ".xlsx"
        ):
            default_mime_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            raise CollectionParseError(
                f"不支持的 Google Trends 导出格式：{export_format}"
            )
        datasets = _result_datasets(files.result)
        return ParsedCollection(
            submission=submission,
            parser_version=self.parser_version,
            request_params=files.params,
            artifacts=standard_artifacts(
                files,
                default_export_mime_type=default_mime_type,
            ),
            datasets=datasets,
        )


def _result_datasets(payload: dict[str, Any]):
    """把规范化结果字典行转换为通用列/行 JSON Dataset。"""
    raw_rows = payload.get("data")
    if not isinstance(raw_rows, list) or not all(
        isinstance(row, dict) for row in raw_rows
    ):
        raise CollectionParseError("Google Trends result.json data 必须是对象数组")

    # 不同记录可能出现不同字段，按首次出现顺序并集可避免丢失后续列。
    columns: list[str] = []
    seen: set[str] = set()
    for row in raw_rows:
        for key in row:
            name = str(key)
            if name not in seen:
                seen.add(name)
                columns.append(name)
    compatible: dict[str, Any] = {
        "sheet_name": "main",
        "columns": columns,
        "rows": [[row.get(column) for column in columns] for row in raw_rows],
    }
    return json_datasets(
        compatible,
        source_name="Google Trends",
        business_key_fields=_BUSINESS_KEY_FIELDS,
    )
