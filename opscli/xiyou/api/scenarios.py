"""西柚洞察接口场景注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.xiyou.api.payloads import (
    make_asin_compare_payload,
    make_keyword_analysis_payload,
    make_keyword_explorer_payload,
    make_ranking_payload,
    make_reverse_keyword_payload,
)
from opscli.xiyou.domain.exceptions import XiyouConfigError


PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class XiyouRankingScenario:
    """西柚洞察排行榜场景定义。"""

    function: str
    target: str
    title: str
    endpoint: str
    allowed_rank_patterns: tuple[str, ...]
    default_rank_pattern: str
    mode: str = "rows"
    default_dataset: str | None = None
    status_endpoint: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回 MCP 可公开的场景说明。"""
        return asdict(self)

    def build_payload(
        self,
        *,
        site: str,
        period: str,
        rank_pattern: str | None,
        query: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """构造排行榜 payload。"""
        normalized_rank_pattern = self.normalize_rank_pattern(rank_pattern)
        return make_ranking_payload(
            {
                "site": site,
                "period": period,
                "rank_pattern": normalized_rank_pattern,
                "query": query,
                "page": page,
                "page_size": page_size,
            }
        )

    def normalize_rank_pattern(self, value: str | None) -> str:
        """校验并返回排行榜类型。"""
        rank_pattern = (value or self.default_rank_pattern).lower()
        if rank_pattern not in self.allowed_rank_patterns:
            allowed = ", ".join(self.allowed_rank_patterns)
            raise XiyouConfigError(f"{self.target} 排行榜 rank_pattern 仅支持：{allowed}")
        return rank_pattern


SCENARIOS: dict[str, XiyouRankingScenario] = {
    "asin": XiyouRankingScenario(
        function="ranking",
        target="asin",
        title="ASIN 排行榜",
        endpoint="/v2/rankingList/asins",
        allowed_rank_patterns=("flow", "surge"),
        default_rank_pattern="flow",
    ),
    "keyword": XiyouRankingScenario(
        function="ranking",
        target="keyword",
        title="关键词排行榜",
        endpoint="/v3/rankingList/searchTerms",
        allowed_rank_patterns=("aba", "surge"),
        default_rank_pattern="aba",
    ),
}


@dataclass(frozen=True)
class XiyouResourceScenario:
    """西柚洞察 resource 导出场景定义。"""

    function: str
    title: str
    endpoint: str
    status_endpoint: str
    required_params: tuple[str, ...]
    payload_builder: PayloadBuilder
    default_dataset: str = "keywords"
    mode: str = "resource"

    def to_public_dict(self) -> dict[str, Any]:
        """返回 MCP 可公开的场景说明。"""
        payload = asdict(self)
        payload.pop("payload_builder", None)
        return payload

    def build_payload(
        self,
        *,
        site: str,
        asin: str | None,
        asins: list[str] | str | None,
        keyword: str | None,
        query: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """构造 resource 场景 payload。"""
        return self.payload_builder(
            {
                "site": site,
                "asin": asin,
                "asins": asins,
                "keyword": keyword,
                "query": query,
                "page": page,
                "page_size": page_size,
            }
        )


RESOURCE_SCENARIOS: dict[str, XiyouResourceScenario] = {
    "reverse-keyword": XiyouResourceScenario(
        function="reverse-keyword",
        title="反查关键词",
        endpoint="/v3/asins/research/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("asin",),
        payload_builder=make_reverse_keyword_payload,
        default_dataset="keywords",
    ),
    "asin-compare": XiyouResourceScenario(
        function="asin-compare",
        title="多ASIN对比",
        endpoint="/v4/asins/compare/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("asins",),
        payload_builder=make_asin_compare_payload,
        default_dataset="keywords",
    ),
    "keyword-analysis": XiyouResourceScenario(
        function="keyword-analysis",
        title="关键词分析",
        endpoint="/v4/searchTerms/analysis/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_analysis_payload,
        default_dataset="analysis",
    ),
    "keyword-explorer": XiyouResourceScenario(
        function="keyword-explorer",
        title="以词找词",
        endpoint="/v4/searchTermExplorer/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_explorer_payload,
        default_dataset="keywords",
    ),
}


def list_scenarios() -> list[dict[str, Any]]:
    """列出可用排行榜场景。"""
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def list_resource_scenarios() -> list[dict[str, Any]]:
    """列出可用 resource 导出场景。"""
    return [scenario.to_public_dict() for scenario in RESOURCE_SCENARIOS.values()]


def get_scenario(target: str) -> XiyouRankingScenario:
    """按 target 获取排行榜场景。"""
    key = (target or "").lower()
    scenario = SCENARIOS.get(key)
    if not scenario:
        raise XiyouConfigError("ranking target 仅支持：asin, keyword")
    return scenario


def get_resource_scenario(function: str) -> XiyouResourceScenario:
    """按 function 获取 resource 导出场景。"""
    scenario = RESOURCE_SCENARIOS.get((function or "").lower())
    if not scenario:
        allowed = ", ".join(["ranking", *RESOURCE_SCENARIOS.keys()])
        raise XiyouConfigError(f"opscli xiyou run 支持功能：{allowed}")
    return scenario
