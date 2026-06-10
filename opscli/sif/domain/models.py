"""Sif 领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SifSalesApiResult:
    """Sif 查销量接口结果。"""

    listing_history: dict[str, Any]
    group_variants: dict[str, Any]
    listing_history_xlsx: bytes | None = None
    bought_by_asin_xlsx: bytes | None = None


@dataclass
class SifRunRequest:
    """Generic Sif feature runtime request."""

    feature: str
    asin: str
    site: str = "US"
    asins: list[str] = field(default_factory=list)
    time_piece_type: str = "latelyDay"
    time_piece_value: str = "7"
    sections: list[str] = field(default_factory=list)
    my_asin: str | None = None
    page_num: int = 1
    page_size: int | None = None
    output_dir: str | None = None
    job_id: str | None = None
    sif_username: str | None = None
    sif_password: str | None = None
    timeout: float = 60.0
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SifExportResult:
    """Sif exported file metadata."""

    path: str
    filename: str
    url: str | None = None
    format: str = "xlsx"
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SifRunResult:
    """Generic Sif feature runtime result."""

    job_id: str
    feature: str
    provider: str
    site: str
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    asin: str | None = None
    asins: list[str] = field(default_factory=list)
    exports: dict[str, SifExportResult] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["exports"] = {key: value.to_dict() for key, value in self.exports.items()}
        return payload

