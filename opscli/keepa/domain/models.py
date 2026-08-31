"""Keepa API 数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KeepaExportResult:
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
class KeepaScenarioRequest:
    """Keepa 场景执行请求。"""

    scenario: str
    site: str = "US"
    params: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    output_dir: str | None = None
    export_format: str = "xls"
    reserve_tokens: int | None = None
    force: bool = False
    wait: bool = False
    upload_export: bool = True

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class KeepaScenarioResult:
    """Keepa 场景执行结果。"""

    job_id: str
    scenario: str
    site: str
    row_count: int
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    export: KeepaExportResult | None = None
    data: list[Any] = field(default_factory=list)
    quota: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP/CLI 返回结构。"""
        payload = asdict(self)
        payload["export"] = self.export.to_dict() if self.export else None
        return payload

    @classmethod
    def empty(
        cls,
        *,
        job_id: str,
        scenario: str,
        site: str,
        root_dir: Path,
        params_path: Path,
        raw_path: Path,
        result_path: Path,
    ) -> "KeepaScenarioResult":
        """构造无数据的初始结果。"""
        return cls(
            job_id=job_id,
            scenario=scenario,
            site=site,
            row_count=0,
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
        )
