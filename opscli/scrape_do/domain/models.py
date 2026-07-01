"""Scrape.do 数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScrapeDoCredential:
    """Scrape.do API token 记录。"""

    name: str
    token: str
    source: str

    def to_public_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source, "has_token": bool(self.token)}


@dataclass
class ScrapeDoExportResult:
    """单次任务导出文件信息。"""

    path: str
    filename: str
    url: str | None = None
    format: str = "xlsx"
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapeDoScenarioRequest:
    """Scrape.do 场景执行请求。"""

    scenario: str
    site: str = "US"
    params: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    output_dir: str | None = None
    export_format: str = "xls"
    timeout_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapeDoScenarioResult:
    """Scrape.do 场景执行结果。"""

    job_id: str
    scenario: str
    site: str
    row_count: int
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    export: ScrapeDoExportResult | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)
    billing: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
    ) -> "ScrapeDoScenarioResult":
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
