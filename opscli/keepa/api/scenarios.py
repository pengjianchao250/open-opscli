"""Keepa API 场景注册表。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.keepa.domain.exceptions import KeepaConfigError


DOMAIN_CODES: dict[str, int] = {
    "US": 1,
    "GB": 2,
    "UK": 2,
    "DE": 3,
    "FR": 4,
    "JP": 5,
    "CA": 6,
    "IT": 8,
    "ES": 9,
    "IN": 10,
    "MX": 11,
    "BR": 12,
}

ScenarioBuilder = Callable[[dict[str, Any], str], dict[str, Any]]
Estimator = Callable[[dict[str, Any]], int | None]


@dataclass(frozen=True)
class KeepaScenario:
    """单个 Keepa 接口场景定义。"""

    scenario_id: str
    title: str
    endpoint: str
    required_params: tuple[str, ...]
    param_builder: ScenarioBuilder
    token_estimator: Estimator
    description: str

    def to_public_dict(self) -> dict[str, Any]:
        """返回 MCP 可公开的场景说明。"""
        payload = asdict(self)
        payload.pop("param_builder", None)
        payload.pop("token_estimator", None)
        return payload

    def build_params(self, *, params: dict[str, Any], site: str) -> dict[str, Any]:
        """构造 Keepa API 请求参数。"""
        self._validate_required(params)
        return self.param_builder(params, site)

    def estimate_tokens(self, params: dict[str, Any]) -> int | None:
        """保守估算 token 消耗，用于运行前提醒。"""
        return self.token_estimator(params)

    def _validate_required(self, params: dict[str, Any]) -> None:
        missing = [key for key in self.required_params if not params.get(key)]
        if missing:
            raise KeepaConfigError(f"场景 {self.scenario_id} 缺少参数：{', '.join(missing)}")


def list_scenarios() -> list[dict[str, Any]]:
    """列出可用场景。"""
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> KeepaScenario:
    """获取场景定义。"""
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        raise KeepaConfigError(f"未知 Keepa 场景：{scenario_id}")
    return scenario


def normalize_domain(site: str) -> str:
    """将站点代码转换为 Keepa domain 数字字符串。"""
    text = str(site or "US").strip().upper()
    if text.isdigit():
        return text
    code = DOMAIN_CODES.get(text)
    if code is None:
        raise KeepaConfigError(f"不支持的 Keepa 站点：{site}")
    return str(code)


def _product_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    asins = _csv(params.get("asins") or params.get("asin"))
    codes = _csv(params.get("codes") or params.get("code"))
    if not asins and not codes:
        raise KeepaConfigError("product 场景需要 asins/asin 或 codes/code")
    if asins and codes:
        raise KeepaConfigError("product 场景不能同时传 asins 和 codes")
    items = asins or codes
    max_items = 20 if params.get("offers") else 100
    if len(_split_csv(items)) > max_items:
        raise KeepaConfigError(f"product 场景单次最多 {max_items} 个 item")

    payload: dict[str, Any] = {
        "domain": normalize_domain(site),
        "asin" if asins else "code": items,
    }
    _copy_optional(
        payload,
        params,
        {
            "stats": "stats",
            "offers": "offers",
            "update": "update",
            "history": "history",
            "buybox": "buybox",
            "rating": "rating",
            "videos": "videos",
            "aplus": "aplus",
            "stock": "stock",
            "days": "days",
            "onlyLiveOffers": "only-live-offers",
            "only_live_offers": "only-live-offers",
        },
    )
    return payload


def _product_search_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    term = params.get("term") or params.get("keyword")
    if not term:
        raise KeepaConfigError("product-search 场景需要 term 或 keyword")
    payload: dict[str, Any] = {
        "domain": normalize_domain(site),
        "type": "product",
        "term": term,
    }
    _copy_optional(
        payload,
        params,
        {
            "stats": "stats",
            "update": "update",
            "history": "history",
            "asinsOnly": "asins-only",
            "asins_only": "asins-only",
            "page": "page",
        },
    )
    return payload


def _product_finder_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    selection = _selection(params)
    return {
        "domain": normalize_domain(site),
        "selection": json.dumps(selection, ensure_ascii=False, separators=(",", ":")),
    }


def _category_search_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    term = params.get("term") or params.get("keyword")
    if not term:
        raise KeepaConfigError("category-search 场景需要 term 或 keyword")
    payload = {
        "domain": normalize_domain(site),
        "type": "category",
        "term": term,
    }
    _copy_optional(payload, params, {"parents": "parents"})
    return payload


def _category_lookup_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    categories = _csv(params.get("categories") or params.get("category"))
    if not categories:
        raise KeepaConfigError("category-lookup 场景需要 category 或 categories")
    if len(_split_csv(categories)) > 10:
        raise KeepaConfigError("category-lookup 场景单次最多 10 个 category id")
    payload = {"domain": normalize_domain(site), "category": categories}
    _copy_optional(payload, params, {"parents": "parents"})
    return payload


def _seller_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    sellers = _csv(params.get("sellers") or params.get("seller"))
    if not sellers:
        raise KeepaConfigError("seller 场景需要 seller 或 sellers")
    if len(_split_csv(sellers)) > 100:
        raise KeepaConfigError("seller 场景单次最多 100 个 seller id")
    payload = {"domain": normalize_domain(site), "seller": sellers}
    _copy_optional(payload, params, {"storefront": "storefront", "update": "update"})
    return payload


def _top_seller_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    return {"domain": normalize_domain(site)}


def _bestsellers_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    category = params.get("category") or params.get("productGroup") or params.get("product_group")
    if not category:
        raise KeepaConfigError("bestsellers 场景需要 category、productGroup 或 product_group")
    return {"domain": normalize_domain(site), "category": category}


def _deals_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    selection = _selection(params)
    selection.setdefault("domainId", int(normalize_domain(site)))
    return {
        "domain": normalize_domain(site),
        "selection": json.dumps(selection, ensure_ascii=False, separators=(",", ":")),
    }


def _lightning_deals_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    payload = {"domain": normalize_domain(site)}
    if params.get("asin"):
        payload["asin"] = params["asin"]
    return payload


def _estimate_product(params: dict[str, Any]) -> int:
    items = _csv(params.get("asins") or params.get("asin") or params.get("codes") or params.get("code"))
    return max(1, len(_split_csv(items)))


def _estimate_one(params: dict[str, Any]) -> int:
    return 1


def _estimate_seller(params: dict[str, Any]) -> int:
    sellers = _csv(params.get("sellers") or params.get("seller"))
    return max(1, len(_split_csv(sellers)))


SCENARIOS: dict[str, KeepaScenario] = {
    "product": KeepaScenario(
        scenario_id="product",
        title="商品详情",
        endpoint="product",
        required_params=(),
        param_builder=_product_params,
        token_estimator=_estimate_product,
        description="按 ASIN 或 UPC/EAN/ISBN-13 code 获取商品对象和价格历史。",
    ),
    "product-search": KeepaScenario(
        scenario_id="product-search",
        title="商品关键词搜索",
        endpoint="search",
        required_params=(),
        param_builder=_product_search_params,
        token_estimator=_estimate_one,
        description="按关键词搜索 Amazon 商品，可返回商品对象或 ASIN 列表。",
    ),
    "product-finder": KeepaScenario(
        scenario_id="product-finder",
        title="Product Finder",
        endpoint="query",
        required_params=(),
        param_builder=_product_finder_params,
        token_estimator=_estimate_one,
        description="按 Keepa Product Finder selection 筛选商品库。",
    ),
    "category-search": KeepaScenario(
        scenario_id="category-search",
        title="类目搜索",
        endpoint="search",
        required_params=(),
        param_builder=_category_search_params,
        token_estimator=_estimate_one,
        description="按类目关键词搜索 Keepa category 对象。",
    ),
    "category-lookup": KeepaScenario(
        scenario_id="category-lookup",
        title="类目详情",
        endpoint="category",
        required_params=(),
        param_builder=_category_lookup_params,
        token_estimator=_estimate_one,
        description="按 category id 查询类目详情，可一次最多 10 个 id。",
    ),
    "seller": KeepaScenario(
        scenario_id="seller",
        title="卖家详情",
        endpoint="seller",
        required_params=(),
        param_builder=_seller_params,
        token_estimator=_estimate_seller,
        description="按 seller id 查询卖家指标，可选 storefront ASIN 列表。",
    ),
    "top-seller": KeepaScenario(
        scenario_id="top-seller",
        title="Top Sellers",
        endpoint="topseller",
        required_params=(),
        param_builder=_top_seller_params,
        token_estimator=_estimate_one,
        description="获取指定站点评分最多的 Amazon marketplace sellers。",
    ),
    "bestsellers": KeepaScenario(
        scenario_id="bestsellers",
        title="Best Sellers",
        endpoint="bestsellers",
        required_params=(),
        param_builder=_bestsellers_params,
        token_estimator=_estimate_one,
        description="按 category node 或 productGroup 获取热销 ASIN 列表。",
    ),
    "deals": KeepaScenario(
        scenario_id="deals",
        title="Deals",
        endpoint="deal",
        required_params=(),
        param_builder=_deals_params,
        token_estimator=_estimate_one,
        description="按 selection 查询最近变动和折扣商品，单次最多约 150 条。",
    ),
    "lightning-deals": KeepaScenario(
        scenario_id="lightning-deals",
        title="Lightning Deals",
        endpoint="lightningdeal",
        required_params=(),
        param_builder=_lightning_deals_params,
        token_estimator=_estimate_one,
        description="查询当前和即将开始的秒杀，可选 ASIN。",
    ),
}


def _selection(params: dict[str, Any]) -> dict[str, Any]:
    selection = params.get("selection")
    if selection is None:
        selection = {key: value for key, value in params.items() if value is not None}
    if not isinstance(selection, dict):
        raise KeepaConfigError("selection 必须是 JSON 对象")
    return dict(selection)


def _csv(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _copy_optional(target: dict[str, Any], source: dict[str, Any], mapping: dict[str, str]) -> None:
    for source_key, target_key in mapping.items():
        if source_key in source and source[source_key] is not None:
            target[target_key] = source[source_key]
