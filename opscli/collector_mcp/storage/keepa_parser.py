"""Keepa 采集结果解析 Adapter。"""

from __future__ import annotations

from opscli.collector_mcp.storage.models import CollectionSubmission, ParsedCollection
from opscli.collector_mcp.storage.parser_utils import (
    CollectionParseError,
    load_result_files,
    standard_artifacts,
    xlsx_datasets,
)

# Parser 版本参与 Collection 幂等键；解析合同变化时必须递增。
PARSER_VERSION = "keepa-v1"
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
        if (
            export_format not in {"xls", "xlsx"}
            and files.export_path.suffix.lower() != ".xlsx"
        ):
            raise CollectionParseError(f"不支持的 Keepa 导出格式：{export_format}")

        datasets = xlsx_datasets(
            files.export_path,
            source_name="Keepa",
            business_key_fields=_BUSINESS_KEY_FIELDS,
        )
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
