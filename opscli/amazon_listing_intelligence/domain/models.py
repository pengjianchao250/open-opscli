"""Amazon Listing Intelligence 数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DataSourcePlan:
    """Listing 优化数据源接入计划。"""

    source_id: str
    name: str
    phase: str
    priority: str
    access_mode: str
    account_required: bool
    paid_required: bool
    value: str
    fields: list[str]
    use_cases: list[str]
    onboarding: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    existing_entry: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP 友好的字典。"""
        return asdict(self)


@dataclass(frozen=True)
class ListingIntelligenceRequest:
    """Listing 优化分析接入请求。"""

    asin: str | None = None
    keyword: str | None = None
    marketplace: str = "US"
    objective: str = "listing_audit"
    available_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return asdict(self)
