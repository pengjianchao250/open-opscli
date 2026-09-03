"""Keepa 场景 API 的稳定请求合同。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class KeepaRunRequest(BaseModel):
    """Keepa 场景 API 的稳定请求合同。"""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    site: str = Field(default="US", min_length=2, max_length=8)
    export_format: Literal["xls", "xlsx", "json"] = "xls"
    job_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    reserve_tokens: int | None = Field(default=None, ge=0)
    force: bool = False
    wait: bool = False
