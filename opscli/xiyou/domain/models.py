"""西柚洞察接口直连数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class XiyouExportResult:
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
class XiyouRankingRequest:
    """西柚洞察接口场景执行请求。"""

    function: str = "ranking"
    provider: str = "xiyou"
    target: str = "asin"
    site: str = "US"
    period: str = "week"
    rank_pattern: str | None = None
    dataset: str | None = None
    asin: str | None = None
    asins: list[str] | str | None = None
    keyword: str | None = None
    query: str = ""
    parent_asin: str | None = None
    cycle_period: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    report_date: str | None = None
    search_terms: list[str] | str | None = None
    view_mode: str | None = None
    replay_type: str | None = None
    keyword_type: str | None = None
    page: int = 1
    page_size: int = 50
    job_id: str | None = None
    output_dir: str | None = None
    export_format: str = "xlsx"

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class XiyouRankingResult:
    """西柚洞察接口场景执行结果。"""

    job_id: str
    function: str
    provider: str
    target: str
    site: str
    period: str
    rank_pattern: str
    row_count: int
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    dataset: str | None = None
    data_mode: str = "rows"
    resource_id: str | None = None
    resource_url: str | None = None
    export: XiyouExportResult | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP/CLI 返回结构。"""
        payload = asdict(self)
        if self.export:
            export_payload = self.export.to_dict()
            if self.resource_url:
                export_payload["download_url"] = self.resource_url
                local_url = None
                if export_payload.get("path"):
                    local_url = Path(export_payload["path"]).expanduser().resolve().as_uri()

                if local_url:
                    export_payload.setdefault("local_url", local_url)
                if not export_payload.get("url") or str(export_payload["url"]).startswith("file:"):
                    export_payload["url"] = self.resource_url

            payload["export"] = export_payload
        else:
            payload["export"] = None
        return payload

    @classmethod
    def empty(
        cls,
        *,
        job_id: str,
        request: XiyouRankingRequest,
        rank_pattern: str,
        root_dir: Path,
        params_path: Path,
        raw_path: Path,
        result_path: Path,
    ) -> "XiyouRankingResult":
        """构造无数据的初始结果。"""
        return cls(
            job_id=job_id,
            function=request.function,
            provider=request.provider,
            target=request.target,
            site=request.site,
            period=request.period,
            rank_pattern=rank_pattern,
            row_count=0,
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
        )
