"""Scrape.do Amazon Scraper 场景注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError

ScenarioBuilder = Callable[[dict[str, Any], str, str], dict[str, Any]]


@dataclass(frozen=True)
class ScrapeDoScenario:
    """单个 Scrape.do 场景定义。"""

    scenario_id: str
    title: str
    endpoint: str
    required_params: tuple[str, ...]
    param_builder: ScenarioBuilder
    description: str
    sample_params: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("param_builder", None)
        return payload

    def build_params(self, *, params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
        self._validate_required(params)
        return self.param_builder(params, site, token)

    def _validate_required(self, params: dict[str, Any]) -> None:
        missing = [key for key in self.required_params if not _text(params.get(key))]
        if missing:
            raise ScrapeDoConfigError(f"场景 {self.scenario_id} 缺少参数：{', '.join(missing)}")


def list_scenarios() -> list[dict[str, Any]]:
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> ScrapeDoScenario:
    key = str(scenario_id or "").strip()
    scenario = SCENARIOS.get(key)
    if not scenario:
        raise ScrapeDoConfigError(f"未知 Scrape.do 场景：{scenario_id}")
    return scenario


def _pdp_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    payload = _base_params(params, site, token)
    payload["asin"] = _text(params.get("asin")).upper()
    _copy_optional(payload, params, {"language": "language", "device": "device"})
    _copy_super(payload, params)
    return payload


def _offer_listing_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    payload = _base_params(params, site, token)
    payload["asin"] = _text(params.get("asin")).upper()
    _copy_optional(payload, params, {"device": "device"})
    _copy_super(payload, params)
    return payload


def _search_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    payload = _base_params(params, site, token)
    payload["keyword"] = _text(params.get("keyword"))
    payload["page"] = _positive_int(params.get("page"), 1, "page")
    _copy_optional(payload, params, {"language": "language", "device": "device"})
    _copy_super(payload, params)
    return payload


def _base_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    zipcode = _text(params.get("zipcode"))
    country_name = _text(params.get("countryName") or params.get("country_name"))
    if zipcode and country_name:
        raise ScrapeDoConfigError("zipcode 和 countryName 不能同时传")
    payload = {"token": token, "geocode": _normalize_site(site)}
    if zipcode:
        payload["zipcode"] = zipcode
    if country_name:
        payload["countryName"] = country_name
    return payload


def _copy_optional(payload: dict[str, Any], params: dict[str, Any], mapping: dict[str, str]) -> None:
    for source, target in mapping.items():
        value = _text(params.get(source))
        if value:
            payload[target] = value


def _copy_super(payload: dict[str, Any], params: dict[str, Any]) -> None:
    if "super" not in params:
        return
    payload["super"] = "true" if _parse_bool(params.get("super"), "super") else "false"


def _normalize_site(site: Any) -> str:
    text = _text(site or "US").upper()
    if text == "UK":
        return "GB"
    if not text:
        return "US"
    return text


def _positive_int(value: Any, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ScrapeDoConfigError(f"参数 {name} 必须是正整数：{value}") from exc
    if parsed <= 0:
        raise ScrapeDoConfigError(f"参数 {name} 必须是正整数：{value}")
    return parsed


def _parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ScrapeDoConfigError(f"参数 {name} 必须是布尔值：{value}")


def _text(value: Any) -> str:
    return str(value or "").strip()


SCENARIOS: dict[str, ScrapeDoScenario] = {
    "amazon-pdp": ScrapeDoScenario(
        scenario_id="amazon-pdp",
        title="Amazon PDP 商品详情",
        endpoint="/plugin/amazon/pdp",
        required_params=("asin",),
        param_builder=_pdp_params,
        description="按 ASIN 获取 Amazon 商品详情、价格、评分、图片、描述、BSR 和规格。",
        sample_params={"asin": "B0C7BKZ883", "zipcode": "90210", "language": "EN"},
    ),
    "amazon-offer-listing": ScrapeDoScenario(
        scenario_id="amazon-offer-listing",
        title="Amazon 全部卖家报价",
        endpoint="/plugin/amazon/offer-listing",
        required_params=("asin",),
        param_builder=_offer_listing_params,
        description="按 ASIN 获取全部卖家报价、Buy Box、FBA/Prime、运费、配送和库存。",
        sample_params={"asin": "B0DGJ7HYG1", "zipcode": "90210"},
    ),
    "amazon-search": ScrapeDoScenario(
        scenario_id="amazon-search",
        title="Amazon 搜索结果与类目页",
        endpoint="/plugin/amazon/search",
        required_params=("keyword",),
        param_builder=_search_params,
        description="按关键词获取 Amazon 搜索结果、价格、评分、广告标识、Prime 和排名位置。",
        sample_params={"keyword": "laptop stands", "page": 1, "language": "EN"},
    ),
}
