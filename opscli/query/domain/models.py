"""query 模块数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryMetadataResult:
    """query metadata 查询结果。"""

    dataset: dict
    fields: list[dict]
    source: str
    all_datasets: list[dict] | None = None

    def to_dict(self) -> dict:
        result: dict = {
            "dataset": self.dataset,
            "fields": self.fields,
            "source": self.source,
        }
        if self.all_datasets is not None:
            result["all_datasets"] = self.all_datasets
        return result
