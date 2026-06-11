"""Google Trends 场景注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.google_trends.domain.exceptions import GoogleTrendsConfigError


GPROP_VALUES = {"", "images", "news", "youtube", "froogle"}
GPROP_ALIASES = {
    "web": "",
    "search": "",
    "image": "images",
    "images": "images",
    "news": "news",
    "youtube": "youtube",
    "shopping": "froogle",
    "froogle": "froogle",
}

TRENDING_PN_MAP = {
    "US": "united_states",
    "GB": "united_kingdom",
    "UK": "united_kingdom",
    "JP": "japan",
    "CA": "canada",
    "DE": "germany",
    "FR": "france",
    "IT": "italy",
    "ES": "spain",
    "IN": "india",
    "BR": "brazil",
    "MX": "mexico",
    "AU": "australia",
}

REALTIME_PN_MAP = {
    "UNITED_STATES": "US",
    "UNITED_KINGDOM": "GB",
    "JAPAN": "JP",
    "CANADA": "CA",
    "GERMANY": "DE",
    "FRANCE": "FR",
    "ITALY": "IT",
    "SPAIN": "ES",
    "INDIA": "IN",
    "BRAZIL": "BR",
    "MEXICO": "MX",
    "AUSTRALIA": "AU",
}

ScenarioBuilder = Callable[[dict[str, Any], str], dict[str, Any]]


@dataclass(frozen=True)
class GoogleTrendsScenario:
    """单个 Google Trends 场景定义。"""

    scenario_id: str
    title: str
    method: str
    required_params: tuple[str, ...]
    param_builder: ScenarioBuilder
    description: str
    sample_params: dict[str, Any]
    availability: str = "available"
    notes: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回 MCP 可公开的场景说明。"""
        payload = asdict(self)
        payload.pop("param_builder", None)
        return payload

    def build_params(self, *, params: dict[str, Any], geo: str) -> dict[str, Any]:
        """构造 pytrends 场景参数。"""
        return self.param_builder(params, geo)


def list_scenarios() -> list[dict[str, Any]]:
    """列出可用场景。"""
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> GoogleTrendsScenario:
    """获取场景定义。"""
    scenario = SCENARIOS.get(str(scenario_id or "").strip())
    if not scenario:
        raise GoogleTrendsConfigError(f"未知 Google Trends 场景：{scenario_id}")
    return scenario


def _payload_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    geo_value = params["geo"] if "geo" in params else geo
    return {
        "kw_list": _keyword_list(params, max_keywords=5),
        "cat": _parse_int(params.get("cat"), 0),
        "timeframe": str(params.get("timeframe") or "today 12-m").strip(),
        "geo": _normalize_geo(geo_value),
        "gprop": _normalize_gprop(params.get("gprop")),
    }


def _interest_by_region_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    payload = _payload_params(params, geo)
    payload.update(
        {
            "resolution": str(params.get("resolution") or "COUNTRY").strip().upper(),
            "inc_low_vol": _parse_bool(params.get("inc_low_vol"), True),
            "inc_geo_code": _parse_bool(params.get("inc_geo_code"), False),
        }
    )
    return payload


def _suggestions_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    keywords = _keyword_list(params, max_keywords=1)
    return {"keyword": keywords[0]}


def _trending_searches_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    pn = params.get("pn") or params.get("geo") or geo or "US"
    return {"pn": _normalize_trending_pn(pn)}


def _realtime_trending_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    pn = params.get("pn") or params.get("geo") or geo or "US"
    return {"pn": _normalize_realtime_pn(pn)}


def _keyword_list(params: dict[str, Any], *, max_keywords: int) -> list[str]:
    value = params.get("kw_list")
    if value is None:
        value = params.get("keywords")
    if value is None:
        value = params.get("keyword")
    if value is None:
        value = params.get("q")
    keywords = _list_text(value)
    if not keywords:
        raise GoogleTrendsConfigError("缺少关键词参数：keyword、keywords 或 kw_list")
    if len(keywords) > max_keywords:
        raise GoogleTrendsConfigError(f"Google Trends 单次最多支持 {max_keywords} 个关键词")
    return keywords


def _list_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",") if "," in value else [value]
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = [value]
    return [str(item).strip() for item in parts if str(item).strip()]


def _normalize_geo(value: Any) -> str:
    if value is None:
        return "US"
    text = str(value).strip()
    if not text:
        return ""
    return text.upper()


def _normalize_gprop(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    normalized = GPROP_ALIASES.get(text, text)
    if normalized not in GPROP_VALUES:
        raise GoogleTrendsConfigError(f"不支持的 gprop：{value}")
    return normalized


def _normalize_trending_pn(value: Any) -> str:
    text = str(value or "US").strip()
    if not text:
        return "united_states"
    upper = text.upper().replace("-", "_")
    if upper in TRENDING_PN_MAP:
        return TRENDING_PN_MAP[upper]
    return text.lower().replace(" ", "_").replace("-", "_")


def _normalize_realtime_pn(value: Any) -> str:
    text = str(value or "US").strip()
    if not text:
        return "US"
    upper = text.upper().replace("-", "_").replace(" ", "_")
    return REALTIME_PN_MAP.get(upper, upper)


def _parse_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GoogleTrendsConfigError(f"参数需要整数：{value}") from exc


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise GoogleTrendsConfigError(f"参数需要布尔值：{value}")


SCENARIOS: dict[str, GoogleTrendsScenario] = {
    "interest-over-time": GoogleTrendsScenario(
        scenario_id="interest-over-time",
        title="关键词趋势时间序列",
        method="interest_over_time",
        required_params=("keyword",),
        param_builder=_payload_params,
        description="按关键词、地区、时间范围获取 Google Trends 搜索指数时间序列，最多 5 个关键词。",
        sample_params={"keyword": "flashlight", "timeframe": "today 12-m", "geo": "US"},
    ),
    "interest-by-region": GoogleTrendsScenario(
        scenario_id="interest-by-region",
        title="关键词地区热度",
        method="interest_by_region",
        required_params=("keyword",),
        param_builder=_interest_by_region_params,
        description="按地区拆分关键词搜索热度，支持 resolution、inc_low_vol、inc_geo_code。",
        sample_params={"keyword": "flashlight", "geo": "US", "resolution": "REGION"},
    ),
    "related-queries": GoogleTrendsScenario(
        scenario_id="related-queries",
        title="相关查询",
        method="related_queries",
        required_params=("keyword",),
        param_builder=_payload_params,
        description="获取关键词相关搜索词 top/rising 列表，最多 5 个关键词。",
        sample_params={"keyword": "flashlight", "geo": "US"},
    ),
    "related-topics": GoogleTrendsScenario(
        scenario_id="related-topics",
        title="相关主题",
        method="related_topics",
        required_params=("keyword",),
        param_builder=_payload_params,
        description="已知不可用：pytrends 相关主题解析当前会触发 list index out of range。",
        sample_params={"keyword": "flashlight", "geo": "US"},
        availability="unavailable",
        notes="2026-06-09 自测 flashlight、iphone、taylor swift 均在 pytrends related_topics 内部抛出 list index out of range。",
    ),
    "suggestions": GoogleTrendsScenario(
        scenario_id="suggestions",
        title="关键词建议",
        method="suggestions",
        required_params=("keyword",),
        param_builder=_suggestions_params,
        description="获取单个关键词的 Google Trends 主题建议。",
        sample_params={"keyword": "flashlight"},
    ),
    "trending-searches": GoogleTrendsScenario(
        scenario_id="trending-searches",
        title="每日热搜",
        method="trending_searches",
        required_params=(),
        param_builder=_trending_searches_params,
        description="已知不可用：pytrends 每日热搜端点当前会返回 Google 404。",
        sample_params={"pn": "US"},
        availability="unavailable",
        notes="2026-06-09 自测 pn=US/united_states 均返回 404；不要作为“今日热搜”查询入口。",
    ),
    "realtime-trending": GoogleTrendsScenario(
        scenario_id="realtime-trending",
        title="实时热搜",
        method="realtime_trending_searches",
        required_params=(),
        param_builder=_realtime_trending_params,
        description="已知不可用：pytrends 实时热搜端点当前会返回 Google 404。",
        sample_params={"pn": "US"},
        availability="unavailable",
        notes="2026-06-09 自测 pn=US 返回 404；不要作为 daily 热搜失败后的回退入口。",
    ),
}
