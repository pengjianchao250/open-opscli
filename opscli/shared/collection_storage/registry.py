"""共享采集数据来源 Parser 注册表。"""

from __future__ import annotations

from typing import Protocol

from opscli.shared.collection_storage.models import CollectionSubmission, ParsedCollection


class CollectionParser(Protocol):
    """来源模块把成功文件转换为统一采集文档的接口。"""

    source_system: str

    def parse(self, submission: CollectionSubmission) -> ParsedCollection:
        """将来源成功任务引用解析为通用采集文档。"""
        ...


class CollectionParserRegistry:
    """使用稳定来源标识解析 Parser，避免 Worker 出现来源分支。"""

    def __init__(self) -> None:
        self._parsers: dict[str, CollectionParser] = {}

    def register(self, parser: CollectionParser) -> None:
        source_system = str(parser.source_system or "").strip()
        if not source_system:
            raise ValueError("Collection Parser source_system 不能为空")
        if source_system in self._parsers:
            raise ValueError(f"Collection Parser 重复注册：{source_system}")
        self._parsers[source_system] = parser

    def resolve(self, source_system: str) -> CollectionParser:
        try:
            return self._parsers[source_system]
        except KeyError as exc:
            raise ValueError(f"未注册 Collection Parser：{source_system}") from exc

    def unregister(self, source_system: str) -> None:
        """在来源生命周期结束时移除 Parser。"""
        self._parsers.pop(source_system, None)
