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
    select_columns: list[dict] | None = None
    # 数据集默认条件（服务端按"自身+组件字段"聚合下发，见需求文档 R1）
    filter_configs: list[dict] | None = None

    def to_dict(self) -> dict:
        result: dict = {
            "dataset": self.dataset,
            "fields": self.fields,
            "source": self.source,
        }
        if self.all_datasets is not None:
            result["all_datasets"] = self.all_datasets
        if self.select_columns is not None:
            result["select_columns"] = self.select_columns
        if self.filter_configs is not None:
            result["filter_configs"] = self.filter_configs
        return result
