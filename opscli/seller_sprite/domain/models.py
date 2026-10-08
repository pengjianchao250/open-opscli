"""卖家精灵接口直连数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SellerSpriteExportResult:
    """单次任务导出文件信息。"""

    path: str
    filename: str
    url: str | None = None
    format: str = "xlsx"
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteScenarioRequest:
    """卖家精灵场景执行请求。"""

    scenario: str
    site: str
    period: str
    params: dict[str, Any] = field(default_factory=dict)
    page_size: int = 100
    job_id: str | None = None
    output_dir: str | None = None
    attempt_output_dir: str | None = None
    export_format: str = "xls"
    mode: str | None = None
    page_prepare: bool | None = None
    task_interval_seconds: float | None = None
    cooldown_seconds: float | None = None
    collection_scope: str = "page"

    def __post_init__(self) -> None:
        """在认证与入队前校验分页全量采集边界。"""
        from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError

        all_scenarios = {
            "product-research",
            "competitor-lookup",
            "keyword-miner",
            "keyword-reverse",
            "traffic-source",
            "association-traffic",
            "aba-research",
            "keyword-research",
            "market-research",
        }

        if self.collection_scope not in {"page", "all"}:
            raise SellerSpriteConfigError("collection_scope 仅支持 page/all")
        if self.collection_scope == "page":
            return
        if self.scenario not in all_scenarios:
            raise SellerSpriteConfigError(
                "collection_scope=all 仅支持已核验的列表场景；官方文件、单报告和远程任务场景暂不支持"
            )
        if self.mode not in {None, "browser-route"}:
            raise SellerSpriteConfigError("全量分页采集仅支持 browser-route")
        if self.export_format.lower() not in {"xls", "xlsx"}:
            raise SellerSpriteConfigError("全量分页采集仅支持 xls/xlsx 文件导出")
        if isinstance(self.page_size, bool) or not isinstance(self.page_size, int) or not 0 < self.page_size <= 100:
            raise SellerSpriteConfigError("全量分页采集要求 page_size 为 1-100 的整数")
        if self.scenario == "product-research":
            if self.page_size != 100:
                raise SellerSpriteConfigError("选产品全量采集要求 page_size=100")
            for name, value, expected in [
                *[(name, self.params[name], 100) for name in ("size", "pageSize") if name in self.params],
            ]:
                if isinstance(value, bool) or str(value) != str(expected):
                    raise SellerSpriteConfigError(f"选产品全量采集要求 {name}={expected}")
        for name in ("page", "startPage", "pageNum", "pageNo"):
            if name in self.params and str(self.params[name]) != "1":
                raise SellerSpriteConfigError(f"全量分页采集要求 {name}=1，从第一页开始")

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteScenarioResult:
    """卖家精灵场景执行结果。"""

    job_id: str
    scenario: str
    site: str
    period: str
    row_count: int
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    export: SellerSpriteExportResult | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    collection: dict[str, Any] | None = None
    preview: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP/CLI 返回结构。"""
        payload = asdict(self)
        payload["export"] = self.export.to_dict() if self.export else None
        if self.collection is None:
            payload.pop("collection")
            payload.pop("preview")
        return payload

    @classmethod
    def empty(
        cls,
        *,
        job_id: str,
        scenario: str,
        site: str,
        period: str,
        root_dir: Path,
        params_path: Path,
        raw_path: Path,
        result_path: Path,
    ) -> "SellerSpriteScenarioResult":
        """构造无数据的初始结果。"""
        return cls(
            job_id=job_id,
            scenario=scenario,
            site=site,
            period=period,
            row_count=0,
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
        )
