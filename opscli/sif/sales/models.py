"""Sif sales request and result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SifSalesRunRequest:
    """Runtime request for a Sif sales feature."""

    feature: str
    provider: str | None
    asin: str
    site: str = "US"
    range_value: str | None = None
    time_piece_type: str = "latelyDay"
    time_piece_value: str = "30"
    page_num: int = 1
    page_size: int = 100
    sections: list[str] = field(default_factory=list)
    output_dir: str | None = None
    job_id: str | None = None
    cdp_url: str = "http://127.0.0.1:9222"
    new_chrome: bool = False
    sif_username: str | None = None
    sif_password: str | None = None
    timeout: float = 60.0
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SifSalesExportResult:
    """Sif exported file metadata."""

    path: str
    filename: str
    url: str | None = None
    format: str = "xlsx"
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SifSalesRunResult:
    """Runtime result for a Sif sales feature."""

    job_id: str
    feature: str
    provider: str
    asin: str
    site: str
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    exports: dict[str, SifSalesExportResult] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["exports"] = {key: value.to_dict() for key, value in self.exports.items()}
        return payload
