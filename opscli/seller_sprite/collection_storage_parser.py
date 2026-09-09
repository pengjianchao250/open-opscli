"""卖家精灵采集结果解析 Adapter。"""

from __future__ import annotations

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

# Parser 版本写入 collection_runs，便于未来格式升级后追踪解析口径。
PARSER_VERSION = "seller-sprite-v2"


class SellerSpriteCollectionParser:
    """将卖家精灵成功任务转换为跨场景的逻辑 Dataset。"""

    source_system = "seller_sprite"
    parser_version = PARSER_VERSION

    def parse(self, submission: CollectionSubmission) -> ParsedCollection:
        """解析 SellerSprite JSON 或 XLSX 格式化导出。"""
        if submission.source_system != self.source_system:
            raise CollectionParseError(
                f"SellerSprite Parser 不支持来源：{submission.source_system}"
            )
        files = load_result_files(submission, source_name="卖家精灵")
        export_format = str(
            files.export.get("format") or files.export_path.suffix.lstrip(".")
        ).lower()
        if export_format == "json" or files.export_path.suffix.lower() == ".json":
            datasets = json_datasets(
                read_json_object(files.export_path, source_name="卖家精灵"),
                source_name="卖家精灵",
            )
        elif (
            export_format in {"xls", "xlsx"}
            or files.export_path.suffix.lower() == ".xlsx"
        ):
            datasets = xlsx_datasets(files.export_path, source_name="卖家精灵")
        else:
            raise CollectionParseError(f"不支持的卖家精灵导出格式：{export_format}")
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
                default_export_mime_type="application/json",
            ),
            datasets=datasets,
        )


__all__ = ["CollectionParseError", "SellerSpriteCollectionParser"]
