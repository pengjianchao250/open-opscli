"""Scenario registry for Xiyou API integrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.xiyou.api.payloads import (
    make_ad_analysis_payload,
    make_ad_insight_payload,
    make_asin_compare_payload,
    make_flow_diagnosis_payload,
    make_flow_insight_payload,
    make_flow_weekly_payload,
    make_keyword_ad_replay_payload,
    make_keyword_ad_toppers_payload,
    make_keyword_analysis_payload,
    make_keyword_explorer_payload,
    make_keyword_historical_traffic_payload,
    make_keyword_organic_replay_payload,
    make_parent_analysis_payload,
    make_ranking_payload,
    make_reverse_keyword_payload,
    make_sales_analysis_payload,
)
from opscli.xiyou.domain.exceptions import XiyouConfigError


PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class XiyouRankingScenario:
    function: str
    target: str
    title: str
    endpoint: str
    allowed_rank_patterns: tuple[str, ...]
    default_rank_pattern: str
    allowed_periods: tuple[str, ...]
    default_period: str
    mode: str = "rows"
    default_dataset: str | None = None
    status_endpoint: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
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
        rank_pattern = (value or self.default_rank_pattern).lower()
        if rank_pattern not in self.allowed_rank_patterns:
            allowed = ", ".join(self.allowed_rank_patterns)
            raise XiyouConfigError(f"{self.target} ranking rank_pattern only supports: {allowed}")
        return rank_pattern

    def normalize_period(self, value: str | None) -> str:
        period = (value or self.default_period).lower()
        if period not in self.allowed_periods:
            allowed = ", ".join(self.allowed_periods)
            raise XiyouConfigError(f"{self.target} ranking period only supports: {allowed}")
        return period


SCENARIOS: dict[str, XiyouRankingScenario] = {
    "asin": XiyouRankingScenario(
        function="ranking",
        target="asin",
        title="ASIN ranking",
        endpoint="/v2/rankingList/asins",
        allowed_rank_patterns=("flow", "surge"),
        default_rank_pattern="flow",
        allowed_periods=("week", "month"),
        default_period="week",
    ),
    "keyword": XiyouRankingScenario(
        function="ranking",
        target="keyword",
        title="Keyword ranking",
        endpoint="/v3/rankingList/searchTerms",
        allowed_rank_patterns=("aba", "surge"),
        default_rank_pattern="aba",
        allowed_periods=("week",),
        default_period="week",
    ),
}


@dataclass(frozen=True)
class XiyouResourceScenario:
    function: str
    title: str
    endpoint: str
    status_endpoint: str
    required_params: tuple[str, ...]
    payload_builder: PayloadBuilder
    default_dataset: str = "keywords"
    mode: str = "resource"

    def to_public_dict(self) -> dict[str, Any]:
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
        parent_asin: str | None = None,
        cycle_period: str | None = None,
        start_month: str | None = None,
        end_month: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        report_date: str | None = None,
        search_terms: list[str] | str | None = None,
        page: int = 1,
        page_size: int = 50,
        view_mode: str | None = None,
        keyword_type: str | None = None,
    ) -> dict[str, Any]:
        return self.payload_builder(
            {
                "site": site,
                "asin": asin,
                "asins": asins,
                "keyword": keyword,
                "query": query,
                "parent_asin": parent_asin,
                "cycle_period": cycle_period,
                "start_month": start_month,
                "end_month": end_month,
                "start_date": start_date,
                "end_date": end_date,
                "report_date": report_date,
                "search_terms": search_terms,
                "view_mode": view_mode,
                "keyword_type": keyword_type,
                "page": page,
                "page_size": page_size,
            }
        )


RESOURCE_SCENARIOS: dict[str, XiyouResourceScenario] = {
    "reverse-keyword": XiyouResourceScenario(
        function="reverse-keyword",
        title="Reverse keyword",
        endpoint="/v3/asins/research/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("asin",),
        payload_builder=make_reverse_keyword_payload,
        default_dataset="keywords",
    ),
    "asin-compare": XiyouResourceScenario(
        function="asin-compare",
        title="ASIN compare",
        endpoint="/v4/asins/compare/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("asins",),
        payload_builder=make_asin_compare_payload,
        default_dataset="keywords",
    ),
    "keyword-analysis": XiyouResourceScenario(
        function="keyword-analysis",
        title="Keyword analysis",
        endpoint="/v4/searchTerms/analysis/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_analysis_payload,
        default_dataset="analysis",
    ),
    "keyword-explorer": XiyouResourceScenario(
        function="keyword-explorer",
        title="Keyword explorer",
        endpoint="/v4/searchTermExplorer/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_explorer_payload,
        default_dataset="keywords",
    ),
    "keyword-historical-traffic": XiyouResourceScenario(
        function="keyword-historical-traffic",
        title="Keyword historical traffic",
        endpoint="/v3/searchTerms/historicalTrafficRatio/list",
        status_endpoint="",
        required_params=("keyword",),
        payload_builder=make_keyword_historical_traffic_payload,
        default_dataset="analysis",
        mode="rows",
    ),
    "keyword-ad-replay": XiyouResourceScenario(
        function="keyword-ad-replay",
        title="Keyword ad replay",
        endpoint="/v4/searchTerms/advertisingReplay/resource",
        status_endpoint="/v4/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_ad_replay_payload,
        default_dataset="analysis",
    ),
    "keyword-organic-replay": XiyouResourceScenario(
        function="keyword-organic-replay",
        title="Keyword organic replay",
        endpoint="/v3/searchTerms/organic/replay/resource",
        status_endpoint="/v2/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_organic_replay_payload,
        default_dataset="analysis",
    ),
    "keyword-ad-toppers": XiyouResourceScenario(
        function="keyword-ad-toppers",
        title="Keyword ad toppers",
        endpoint="/v2/searchTerms/advertising/toppers/excel/resource",
        status_endpoint="/v2/resource/status",
        required_params=("keyword",),
        payload_builder=make_keyword_ad_toppers_payload,
        default_dataset="analysis",
    ),
    "ad-analysis": XiyouResourceScenario(
        function="ad-analysis",
        title="Ad analysis",
        endpoint="/v3/advertising/research/searchTerm/list/resource",
        status_endpoint="/v2/resource/status",
        required_params=("asin",),
        payload_builder=make_ad_analysis_payload,
        default_dataset="analysis",
    ),
    "parent-analysis": XiyouResourceScenario(
        function="parent-analysis",
        title="Parent analysis",
        endpoint="/v4/variation/compare/list/resource",
        status_endpoint="/v4/resource/status",
        required_params=("parent_asin", "asins"),
        payload_builder=make_parent_analysis_payload,
        default_dataset="analysis",
    ),
    "sales-analysis": XiyouResourceScenario(
        function="sales-analysis",
        title="Sales analysis",
        endpoint="/v3/asins/sales/list/resource",
        status_endpoint="/v3/resource/status",
        required_params=("asin", "parent_asin"),
        payload_builder=make_sales_analysis_payload,
        default_dataset="analysis",
    ),
    "flow-diagnosis": XiyouResourceScenario(
        function="flow-diagnosis",
        title="Flow diagnosis",
        endpoint="/v3/asins/traffic/diagnosis/list",
        status_endpoint="",
        required_params=("asin",),
        payload_builder=make_flow_diagnosis_payload,
        default_dataset="analysis",
        mode="rows",
    ),
    "flow-insight": XiyouResourceScenario(
        function="flow-insight",
        title="Flow insight",
        endpoint="/v2/asins/flow/insights/resource",
        status_endpoint="/v2/asins/flow/insights/resource/status",
        required_params=("asin", "start_date", "end_date"),
        payload_builder=make_flow_insight_payload,
        default_dataset="analysis",
    ),
    "ad-insight": XiyouResourceScenario(
        function="ad-insight",
        title="Ad insight",
        endpoint="/v2/asins/advertising/insights/resource",
        status_endpoint="/v2/asins/advertising/insights/resource/status",
        required_params=("asin", "start_date", "end_date"),
        payload_builder=make_ad_insight_payload,
        default_dataset="analysis",
    ),
    "flow-weekly": XiyouResourceScenario(
        function="flow-weekly",
        title="Flow weekly",
        endpoint="/v2/asins/flow/weeklyReport/resource",
        status_endpoint="/v2/asins/flow/weeklyReport/resource/status",
        required_params=("asin", "start_date", "end_date"),
        payload_builder=make_flow_weekly_payload,
        default_dataset="analysis",
    ),
}


def list_scenarios() -> list[dict[str, Any]]:
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def list_resource_scenarios() -> list[dict[str, Any]]:
    return [scenario.to_public_dict() for scenario in RESOURCE_SCENARIOS.values()]


def get_scenario(target: str) -> XiyouRankingScenario:
    scenario = SCENARIOS.get((target or "").lower())
    if not scenario:
        raise XiyouConfigError("ranking target only supports: asin, keyword")
    return scenario


def get_resource_scenario(function: str) -> XiyouResourceScenario:
    scenario = RESOURCE_SCENARIOS.get((function or "").lower())
    if not scenario:
        allowed = ", ".join(["ranking", *RESOURCE_SCENARIOS.keys()])
        raise XiyouConfigError(f"opscli xiyou run supports: {allowed}")
    return scenario
