"""Keepa API 场景注册表。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

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
    if len(_split_csv(items)) > 100:
        raise KeepaConfigError("product 场景单次最多 100 个 item")

    payload: dict[str, Any] = {
        "domain": normalize_domain(site),
        "asin" if asins else "code": items,
        "history": True,
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
            "code-limit": "code-limit",
            "code_limit": "code-limit",
            "historical-variations": "historical-variations",
            "historical_variations": "historical-variations",
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
            "rating": "rating",
        },
    )
    return payload


def _product_finder_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    selection = _selection(params)
    selection.pop("stats", None)
    payload = {
        "domain": normalize_domain(site),
        "selection": json.dumps(selection, ensure_ascii=False, separators=(",", ":")),
    }
    _copy_optional(payload, params, {"stats": "stats"})
    return payload


def _category_search_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    term = params.get("term") or params.get("keyword")
    if not term:
        raise KeepaConfigError("category-search 场景需要 term 或 keyword")
    payload = {
        "domain": normalize_domain(site),
        "type": "category",
        "term": term,
    }
    return payload


def _category_lookup_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    categories = _csv(params.get("categories") or params.get("category"))
    if not categories:
        raise KeepaConfigError("category-lookup 场景需要 category 或 categories")
    if len(_split_csv(categories)) > 10:
        raise KeepaConfigError("category-lookup 场景单次最多 10 个 category id")
    payload = {
        "domain": normalize_domain(site),
        "category": categories,
        "parents": False,
    }
    _copy_optional(payload, params, {"parents": "parents"})
    return payload


def _seller_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    sellers = _csv(params.get("sellers") or params.get("seller"))
    if not sellers:
        raise KeepaConfigError("seller 场景需要 seller 或 sellers")
    if len(_split_csv(sellers)) > 100:
        raise KeepaConfigError("seller 场景单次最多 100 个 seller id")
    seller_ids = _split_csv(sellers)
    storefront = _as_bool(params.get("storefront", False))
    if storefront and len(seller_ids) > 1:
        raise KeepaConfigError("seller 场景 storefront=true 时只能查询单个 seller")
    payload = {
        "domain": normalize_domain(site),
        "seller": sellers,
        "storefront": storefront,
    }
    return payload


def _seller_finder_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    selection = _selection(params)
    if not selection:
        raise KeepaConfigError("seller-finder 场景需要 selection 或筛选字段")
    return {
        "domain": normalize_domain(site),
        "selection": json.dumps(selection, ensure_ascii=False, separators=(",", ":")),
    }


def _top_seller_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    return {"domain": normalize_domain(site)}


def _bestsellers_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    category = params.get("category") or params.get("productGroup") or params.get("product_group")
    if not category:
        raise KeepaConfigError("bestsellers 场景需要 category、productGroup 或 product_group")
    _validate_bestsellers_options(params)
    payload = {"domain": normalize_domain(site), "category": category}
    _copy_optional(
        payload,
        params,
        {
            "range": "range",
            "month": "month",
            "year": "year",
            "variations": "variations",
            "sublist": "sublist",
        },
    )
    return payload


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
    _copy_optional(payload, params, {"state": "state"})
    return payload


def _estimate_product(params: dict[str, Any]) -> int:
    items = _csv(params.get("asins") or params.get("asin") or params.get("codes") or params.get("code"))
    item_count = max(1, len(_split_csv(items)))
    offers = _positive_int(params.get("offers"))
    if offers:
        # Keepa 每 10 个 Offer 为一页，每页每商品最多消耗 6 token。
        estimate = item_count * 6 * math.ceil(offers / 10)
    else:
        estimate = item_count
    if _as_bool(params.get("buybox")):
        estimate += item_count * 2
    if _as_bool(params.get("stock")) and offers:
        estimate += item_count * 2
    if _as_bool(params.get("rating")):
        estimate += item_count
    if _as_bool(params.get("historical-variations") or params.get("historical_variations")):
        estimate += item_count
    if params.get("update") == 0:
        estimate += item_count
    return estimate


def _estimate_seller(params: dict[str, Any]) -> int:
    sellers = _csv(params.get("sellers") or params.get("seller"))
    estimate = max(1, len(_split_csv(sellers)))
    if _as_bool(params.get("storefront")):
        estimate += 9
    return estimate


def _estimate_product_search(params: dict[str, Any]) -> int:
    estimate = 10
    if params.get("update") == 0:
        estimate += 20
    if _as_bool(params.get("rating")):
        estimate += 5
    return estimate


def _estimate_finder(params: dict[str, Any]) -> int:
    selection = params.get("selection") if isinstance(params.get("selection"), dict) else params
    per_page = _positive_int(selection.get("perPage")) if isinstance(selection, dict) else None
    estimate = 10 + math.ceil((per_page or 50) / 100)
    if _as_bool(params.get("stats")):
        estimate += 30
    return estimate


def _estimate_constant(value: int) -> Estimator:
    def estimator(params: dict[str, Any]) -> int:
        return value

    return estimator


def _estimate_lightning_deals(params: dict[str, Any]) -> int:
    return 1 if params.get("asin") else 500


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
        token_estimator=_estimate_product_search,
        description="按关键词搜索 Amazon 商品，可返回商品对象或 ASIN 列表。",
    ),
    "product-finder": KeepaScenario(
        scenario_id="product-finder",
        title="Product Finder",
        endpoint="query",
        required_params=(),
        param_builder=_product_finder_params,
        token_estimator=_estimate_finder,
        description="按 Keepa Product Finder selection 筛选商品库。",
    ),
    "category-search": KeepaScenario(
        scenario_id="category-search",
        title="类目搜索",
        endpoint="search",
        required_params=(),
        param_builder=_category_search_params,
        token_estimator=_estimate_constant(1),
        description="按类目关键词搜索 Keepa category 对象。",
    ),
    "category-lookup": KeepaScenario(
        scenario_id="category-lookup",
        title="类目详情",
        endpoint="category",
        required_params=(),
        param_builder=_category_lookup_params,
        token_estimator=_estimate_constant(1),
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
    "seller-finder": KeepaScenario(
        scenario_id="seller-finder",
        title="Seller Finder",
        endpoint="sellerquery",
        required_params=(),
        param_builder=_seller_finder_params,
        token_estimator=_estimate_finder,
        description="按 Seller Finder selection 筛选卖家，返回 sellerIdList。",
    ),
    "top-seller": KeepaScenario(
        scenario_id="top-seller",
        title="Top Sellers",
        endpoint="topseller",
        required_params=(),
        param_builder=_top_seller_params,
        token_estimator=_estimate_constant(50),
        description="获取指定站点评分最多的 Amazon marketplace sellers。",
    ),
    "bestsellers": KeepaScenario(
        scenario_id="bestsellers",
        title="Best Sellers",
        endpoint="bestsellers",
        required_params=(),
        param_builder=_bestsellers_params,
        token_estimator=_estimate_constant(50),
        description="按 category node 或 productGroup 获取热销 ASIN 列表。",
    ),
    "deals": KeepaScenario(
        scenario_id="deals",
        title="Deals",
        endpoint="deal",
        required_params=(),
        param_builder=_deals_params,
        token_estimator=_estimate_constant(5),
        description="按 selection 查询最近变动和折扣商品，单次最多约 150 条。",
    ),
    "lightning-deals": KeepaScenario(
        scenario_id="lightning-deals",
        title="Lightning Deals",
        endpoint="lightningdeal",
        required_params=(),
        param_builder=_lightning_deals_params,
        token_estimator=_estimate_lightning_deals,
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


def _validate_bestsellers_options(params: dict[str, Any]) -> None:
    """校验 Best Sellers 的历史、区间和子类目模式组合。"""
    month = params.get("month")
    year = params.get("year")
    if (month is None) != (year is None):
        raise KeepaConfigError("bestsellers 场景 month 与 year 必须同时提供")
    range_value = params.get("range")
    if range_value is not None and _positive_int(range_value, allow_zero=True) not in {0, 30, 90, 180}:
        raise KeepaConfigError("bestsellers 场景 range 仅支持 0、30、90、180")
    if month is not None:
        if range_value is not None or _as_bool(params.get("sublist")):
            raise KeepaConfigError("bestsellers 历史 month/year 不能与 range 或 sublist 同时使用")
        try:
            requested = date(int(year), int(month), 1)
        except (TypeError, ValueError) as exc:
            raise KeepaConfigError("bestsellers 场景 month 必须为 1-12，year 必须为四位年份") from exc
        current = datetime.now(timezone.utc).date().replace(day=1)
        months_ago = (current.year - requested.year) * 12 + current.month - requested.month
        if months_ago < 1 or months_ago > 36:
            raise KeepaConfigError("bestsellers 历史月份必须是过去 36 个完整自然月之一")
    if _as_bool(params.get("sublist")) and range_value is not None:
        raise KeepaConfigError("bestsellers 场景 sublist 不能与 range 同时使用")


def _csv(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _positive_int(value: Any, *, allow_zero: bool = False) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    minimum = 0 if allow_zero else 1
    return number if number >= minimum else None


def _copy_optional(target: dict[str, Any], source: dict[str, Any], mapping: dict[str, str]) -> None:
    for source_key, target_key in mapping.items():
        if source_key in source and source[source_key] is not None:
            target[target_key] = source[source_key]
