"""卖家精灵接口场景注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.seller_sprite.api.payloads import (
    build_referer,
    make_competitor_payload,
    make_keyword_miner_payload,
    make_keyword_reverse_payload,
    make_listing_analysis_payload,
    make_market_research_payload,
    make_product_research_payload,
    make_traffic_source_payload,
)
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SellerSpriteScenario:
    """单个卖家精灵接口场景定义。"""

    scenario_id: str
    title: str
    endpoint: str
    required_params: tuple[str, ...]
    payload_builder: PayloadBuilder
    required_any_params: tuple[str, ...] = ()
    method: str = "POST"
    high_frequency_endpoint: str | None = None
    task_result_endpoint: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回 MCP 可公开的场景说明。"""
        payload = asdict(self)
        payload.pop("payload_builder", None)
        return payload

    def build_payload(self, *, params: dict[str, Any], site: str, period: str, page_size: int) -> dict[str, Any]:
        """合并公共参数并构造 payload。"""
        merged = {
            **params,
            "site": site,
            "market": params.get("market") or site,
            "period": period,
            "month": params.get("month") or period,
            "size": params.get("size") or page_size,
            "pageSize": params.get("pageSize") or page_size,
            "keywordOrAsin": (
                params.get("keywordOrAsin")
                or params.get("keyword")
                or params.get("asin")
                or params.get("asins")
                or params.get("q")
            ),
        }
        self._validate_required(merged)
        return self.payload_builder(merged)

    def build_referer(self, payload: dict[str, Any]) -> str:
        """构造当前场景 referer。"""
        return build_referer(payload, self.scenario_id)

    def endpoint_for(self, payload: dict[str, Any]) -> str:
        """返回主接口地址，支持关键词反查 market query。"""
        if self.scenario_id == "keyword-reverse":
            return f"{self.endpoint}?market={payload.get('market') or 'JP'}"
        return self.endpoint

    def high_frequency_endpoint_for(self, payload: dict[str, Any]) -> str | None:
        """返回高频词接口地址。"""
        if not self.high_frequency_endpoint:
            return None
        return self.high_frequency_endpoint

    def _validate_required(self, payload: dict[str, Any]) -> None:
        missing = [key for key in self.required_params if not payload.get(key)]
        if missing:
            raise SellerSpriteConfigError(f"场景 {self.scenario_id} 缺少参数：{', '.join(missing)}")
        if self.required_any_params and not any(payload.get(key) for key in self.required_any_params):
            raise SellerSpriteConfigError(
                f"场景 {self.scenario_id} 至少需要一个主筛选条件：{', '.join(self.required_any_params)}"
            )


SCENARIOS: dict[str, SellerSpriteScenario] = {
    "competitor-lookup": SellerSpriteScenario(
        scenario_id="competitor-lookup",
        title="选竞品",
        endpoint="/v3/api/competing-lookup",
        required_params=(),
        required_any_params=("keyword", "brand", "sellerName", "asin", "asins"),
        payload_builder=make_competitor_payload,
    ),
    "product-research": SellerSpriteScenario(
        scenario_id="product-research",
        title="选产品",
        endpoint="/v3/api/product-research",
        required_params=(),
        payload_builder=make_product_research_payload,
    ),
    "keyword-miner": SellerSpriteScenario(
        scenario_id="keyword-miner",
        title="关键词挖掘",
        endpoint="/v3/api/keyword-miner",
        high_frequency_endpoint="/v3/api/keyword-miner/high/frequency-new",
        required_params=("keyword",),
        payload_builder=make_keyword_miner_payload,
    ),
    "keyword-reverse": SellerSpriteScenario(
        scenario_id="keyword-reverse",
        title="关键词反查",
        endpoint="/v3/api/relation/reversing",
        required_params=("asin",),
        payload_builder=make_keyword_reverse_payload,
    ),
    "traffic-source": SellerSpriteScenario(
        scenario_id="traffic-source",
        title="查流量来源",
        endpoint="/v3/api/relation/ta/source",
        method="GET",
        required_params=("keywordOrAsin",),
        payload_builder=make_traffic_source_payload,
    ),
    "market-research": SellerSpriteScenario(
        scenario_id="market-research",
        title="选市场",
        endpoint="/v2/market-research",
        method="FORM",
        required_params=(),
        payload_builder=make_market_research_payload,
    ),
    "listing-analysis": SellerSpriteScenario(
        scenario_id="listing-analysis",
        title="Listing Analysis",
        endpoint="/v3/api/ai-analysis/get-submitted",
        method="PAGE_CAPTURE",
        required_params=("asin",),
        payload_builder=make_listing_analysis_payload,
    ),
}


def list_scenarios() -> list[dict[str, Any]]:
    """列出可用场景。"""
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> SellerSpriteScenario:
    """获取场景定义。"""
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        raise SellerSpriteConfigError(f"未知卖家精灵场景：{scenario_id}")
    return scenario
