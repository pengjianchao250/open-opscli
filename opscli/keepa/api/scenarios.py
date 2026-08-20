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
    asins = _alias_csv(params, ("asins", "asin"), "asin/asins")
    codes = _alias_csv(params, ("codes", "code"), "code/codes")
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
    _copy_int(payload, params, "stats", minimum=0)
    _copy_int(payload, params, "offers", minimum=0)
    _copy_int(payload, params, "update", minimum=0)
    _copy_int(payload, params, "days", minimum=1)
    _copy_bool(payload, params, "history")
    for source_key in ("buybox", "rating", "videos", "aplus", "stock"):
        _copy_bool(payload, params, source_key)
    _copy_bool_alias(
        payload,
        params,
        ("only-live-offers", "only_live_offers", "onlyLiveOffers"),
        "only-live-offers",
    )
    _copy_bool_alias(
        payload,
        params,
        ("historical-variations", "historical_variations"),
        "historical-variations",
    )
    _copy_int_alias(payload, params, ("code-limit", "code_limit"), "code-limit", minimum=0)
    return payload


def _product_search_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    term = _alias_text(params, ("term", "keyword"), "term/keyword")
    if not term:
        raise KeepaConfigError("product-search 场景需要 term 或 keyword")
    payload: dict[str, Any] = {
        "domain": normalize_domain(site),
        "type": "product",
        "term": term,
    }
    _copy_int(payload, params, "stats", minimum=0)
    _copy_int(payload, params, "update", minimum=0)
    _copy_bool(payload, params, "history")
    _copy_bool_alias(payload, params, ("asinsOnly", "asins_only"), "asins-only")
    _copy_bool(payload, params, "rating")
    return payload


def _product_finder_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    selection = _selection(params)
    selection.pop("stats", None)
    payload = {
        "domain": normalize_domain(site),
        "selection": json.dumps(selection, ensure_ascii=False, separators=(",", ":")),
    }
    _copy_bool(payload, params, "stats")
    return payload


def _category_search_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    term = _alias_text(params, ("term", "keyword"), "term/keyword")
    if not term:
        raise KeepaConfigError("category-search 场景需要 term 或 keyword")
    payload = {
        "domain": normalize_domain(site),
        "type": "category",
        "term": term,
    }
    return payload


def _category_lookup_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    categories = _alias_csv(params, ("categories", "category"), "category/categories")
    if not categories:
        raise KeepaConfigError("category-lookup 场景需要 category 或 categories")
    if len(_split_csv(categories)) > 10:
        raise KeepaConfigError("category-lookup 场景单次最多 10 个 category id")
    payload = {
        "domain": normalize_domain(site),
        "category": categories,
        "parents": False,
    }
    _copy_bool(payload, params, "parents")
    return payload


def _seller_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    sellers = _alias_csv(params, ("sellers", "seller"), "seller/sellers")
    if not sellers:
        raise KeepaConfigError("seller 场景需要 seller 或 sellers")
    if len(_split_csv(sellers)) > 100:
        raise KeepaConfigError("seller 场景单次最多 100 个 seller id")
    seller_ids = _split_csv(sellers)
    storefront = _as_bool(params.get("storefront", False), field="storefront")
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
    category = _alias_text(params, ("category", "productGroup", "product_group"), "category/productGroup")
    if not category:
        raise KeepaConfigError("bestsellers 场景需要 category、productGroup 或 product_group")
    _validate_bestsellers_options(params)
    payload = {"domain": normalize_domain(site), "category": category}
    _copy_int(payload, params, "range", minimum=0)
    _copy_int(payload, params, "month", minimum=1, maximum=12)
    _copy_int(payload, params, "year", minimum=2000, maximum=9999)
    _copy_bool(payload, params, "variations")
    _copy_bool(payload, params, "sublist")
    return payload


def _deals_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    selection = _selection(params)
    if "domainId" in selection:
        selection["domainId"] = _required_int(selection["domainId"], "selection.domainId", minimum=1)
    selection.setdefault("domainId", int(normalize_domain(site)))
    return {
        "domain": normalize_domain(site),
        "selection": json.dumps(selection, ensure_ascii=False, separators=(",", ":")),
    }


def _lightning_deals_params(params: dict[str, Any], site: str) -> dict[str, Any]:
    payload = {"domain": normalize_domain(site)}
    asin = _alias_csv(params, ("asin",), "asin")
    if asin:
        payload["asin"] = asin
    if params.get("state") is not None:
        state = str(params["state"]).strip()
        if not state:
            raise KeepaConfigError("lightning-deals 场景 state 不能为空")
        payload["state"] = state
    return payload


def _estimate_product(params: dict[str, Any]) -> int:
    items = _alias_csv(params, ("asins", "asin"), "asin/asins")
    if not items:
        items = _alias_csv(params, ("codes", "code"), "code/codes")
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
    if _positive_int(params.get("update"), allow_zero=True) == 0:
        estimate += item_count
    return estimate


def _estimate_seller(params: dict[str, Any]) -> int:
    sellers = _alias_csv(params, ("sellers", "seller"), "seller/sellers")
    estimate = max(1, len(_split_csv(sellers)))
    if _as_bool(params.get("storefront")):
        estimate += 9
    return estimate


def _estimate_product_search(params: dict[str, Any]) -> int:
    estimate = 10
    if _positive_int(params.get("update"), allow_zero=True) == 0:
        estimate += 20
    if _as_bool(params.get("rating")):
        estimate += 5
    return estimate


def _estimate_finder(params: dict[str, Any]) -> int:
    selection = _selection(params)
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
    return 1 if _csv(params.get("asin")) else 500


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
    elif isinstance(selection, str):
        try:
            selection = json.loads(selection)
        except json.JSONDecodeError as exc:
            raise KeepaConfigError("selection 必须是合法 JSON 对象") from exc
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
        return ",".join(str(item).strip() for item in value if item is not None and str(item).strip())
    return str(value).strip()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_bool(value: Any, *, field: str = "参数") -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise KeepaConfigError(f"{field} 必须是布尔值")
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if value is None:
        return False
    raise KeepaConfigError(f"{field} 必须是布尔值")


def _positive_int(value: Any, *, allow_zero: bool = False) -> int | None:
    if isinstance(value, bool):
        return int(value) if allow_zero else None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    minimum = 0 if allow_zero else 1
    return number if number >= minimum else None


def _required_int(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    """将用户输入转换为整数，并在边界外给出可读配置错误。"""
    if isinstance(value, bool):
        raise KeepaConfigError(f"{field} 必须是整数")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise KeepaConfigError(f"{field} 必须是整数") from exc
    if number < minimum or (maximum is not None and number > maximum):
        bound = f"{minimum}-{maximum}" if maximum is not None else f">={minimum}"
        raise KeepaConfigError(f"{field} 必须满足 {bound}")
    return number


def _alias_text(params: dict[str, Any], keys: tuple[str, ...], label: str) -> str:
    """读取一组别名，多个别名同时出现且值不同则拒绝请求。"""
    values = [(key, str(params[key]).strip()) for key in keys if params.get(key) is not None]
    values = [(key, value) for key, value in values if value]
    if not values:
        return ""
    distinct = {value for _, value in values}
    if len(distinct) > 1:
        raise KeepaConfigError(f"不能同时传入不同的 {label}")
    return values[0][1]


def _alias_csv(params: dict[str, Any], keys: tuple[str, ...], label: str) -> str:
    """读取 CSV/列表别名，并按逗号分隔值比较别名是否一致。"""
    values = [(_csv(params[key]), key) for key in keys if params.get(key) is not None]
    values = [(value, key) for value, key in values if value]
    if not values:
        return ""
    distinct = {tuple(_split_csv(value)) for value, _ in values}
    if len(distinct) > 1:
        raise KeepaConfigError(f"不能同时传入不同的 {label}")
    return values[0][0]


def _copy_bool(
    target: dict[str, Any],
    source: dict[str, Any],
    source_key: str,
    *,
    target_key: str | None = None,
) -> None:
    if source_key in source and source[source_key] is not None:
        target[target_key or source_key] = _as_bool(source[source_key], field=source_key)


def _copy_bool_alias(
    target: dict[str, Any], source: dict[str, Any], keys: tuple[str, ...], target_key: str
) -> None:
    values = [(key, source[key]) for key in keys if key in source and source[key] is not None]
    if not values:
        return
    normalized = {_as_bool(value, field=key) for key, value in values}
    if len(normalized) > 1:
        raise KeepaConfigError(f"不能同时传入不同的 {keys[0]}/{keys[1]}")
    target[target_key] = normalized.pop()


def _copy_int(
    target: dict[str, Any],
    source: dict[str, Any],
    source_key: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> None:
    if source_key in source and source[source_key] is not None:
        target[source_key] = _required_int(
            source[source_key], source_key, minimum=minimum, maximum=maximum
        )


def _copy_int_alias(
    target: dict[str, Any],
    source: dict[str, Any],
    keys: tuple[str, ...],
    target_key: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> None:
    values = [(key, source[key]) for key in keys if key in source and source[key] is not None]
    if not values:
        return
    normalized = {
        _required_int(value, key, minimum=minimum, maximum=maximum) for key, value in values
    }
    if len(normalized) > 1:
        raise KeepaConfigError(f"不能同时传入不同的 {keys[0]}/{keys[1]}")
    target[target_key] = normalized.pop()


def _copy_optional(target: dict[str, Any], source: dict[str, Any], mapping: dict[str, str]) -> None:
    for source_key, target_key in mapping.items():
        if source_key in source and source[source_key] is not None:
            target[target_key] = source[source_key]
