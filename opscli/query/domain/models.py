"""query 模块数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryMetadataResult:
    """query metadata 查询结果。"""

    dataset: dict
    fields: list[dict]
    source: str

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "fields": self.fields,
            "source": self.source,
        }
