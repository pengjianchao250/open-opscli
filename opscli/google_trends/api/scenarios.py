"""SerpApi Google Trends 场景注册表。

当前仅启用 SerpApi 的 Trends、Autocomplete、Trending Now 三个原始接口。
旧 pytrends 场景已停用，不再进入公开注册表或执行路径。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.google_trends.domain.exceptions import GoogleTrendsConfigError


TRENDS_DATA_TYPES = frozenset(
    {"TIMESERIES", "GEO_MAP", "GEO_MAP_0", "RELATED_TOPICS", "RELATED_QUERIES"}
)
TRENDS_GPROPS = frozenset({"", "images", "news", "froogle", "youtube"})
TRENDS_REGIONS = frozenset({"COUNTRY", "REGION", "DMA", "CITY"})
TRENDING_NOW_HOURS = frozenset({"4", "24", "48", "168"})
FORBIDDEN_PARAMS = frozenset({"engine", "api_key", "output", "async"})

ScenarioBuilder = Callable[[dict[str, Any], str], dict[str, Any]]


@dataclass(frozen=True)
class GoogleTrendsScenario:
    """单个 SerpApi Google Trends 场景定义。"""

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
        """校验并构造 SerpApi 请求参数。"""
        return self.param_builder(dict(params or {}), geo)


def list_scenarios() -> list[dict[str, Any]]:
    """列出当前启用的三个 SerpApi 场景。"""
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> GoogleTrendsScenario:
    """按场景 ID 获取定义；旧 pytrends 场景视为未知。"""
    scenario = SCENARIOS.get(str(scenario_id or "").strip())
    if not scenario:
        raise GoogleTrendsConfigError(f"未知 Google Trends 场景：{scenario_id}")
    return scenario


def _trends_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    """构造 `engine=google_trends` 的业务参数。"""
    _reject_forbidden_params(params)
    _reject_unknown_params(
        params,
        {
            "q",
            "data_type",
            "geo",
            "date",
            "tz",
            "cat",
            "gprop",
            "region",
            "include_low_search_volume",
            "hl",
            "no_cache",
        },
    )
    data_type = str(params.get("data_type") or "TIMESERIES").strip().upper()
    if data_type not in TRENDS_DATA_TYPES:
        raise GoogleTrendsConfigError(f"不支持的 data_type：{data_type}")

    keywords = _query_list(params.get("q"))
    if not keywords and params.get("cat") in {None, ""}:
        raise GoogleTrendsConfigError("trends 场景缺少 q；仅分类趋势查询可只提供 cat")
    _validate_keyword_count(data_type, keywords)

    result: dict[str, Any] = {}
    if keywords:
        result["q"] = ",".join(keywords)
    result["data_type"] = data_type
    _copy_text(result, params, "date")
    _copy_int(result, params, "tz")
    _copy_int(result, params, "cat")
    _copy_text(result, params, "hl")

    gprop = str(params.get("gprop") or "").strip().lower()
    if "gprop" in params:
        if gprop not in TRENDS_GPROPS:
            raise GoogleTrendsConfigError(f"不支持的 gprop：{params.get('gprop')}")
        result["gprop"] = gprop

    if "region" in params:
        region = str(params.get("region") or "").strip().upper()
        if region not in TRENDS_REGIONS:
            raise GoogleTrendsConfigError(f"不支持的 region：{params.get('region')}")
        if data_type not in {"GEO_MAP", "GEO_MAP_0"}:
            raise GoogleTrendsConfigError("region 仅适用于 GEO_MAP 或 GEO_MAP_0")
        result["region"] = region

    if "include_low_search_volume" in params:
        if data_type not in {"GEO_MAP", "GEO_MAP_0"}:
            raise GoogleTrendsConfigError(
                "include_low_search_volume 仅适用于 GEO_MAP 或 GEO_MAP_0"
            )
        result["include_low_search_volume"] = _bool_text(
            params["include_low_search_volume"], "include_low_search_volume"
        )
    if "no_cache" in params:
        result["no_cache"] = _bool_text(params["no_cache"], "no_cache")

    effective_geo = params.get("geo") if "geo" in params else geo
    normalized_geo = _normalize_geo(effective_geo)
    if normalized_geo:
        result["geo"] = normalized_geo
    return result


def _autocomplete_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    """构造 `engine=google_trends_autocomplete` 的业务参数。"""
    del geo
    _reject_forbidden_params(params)
    _reject_unknown_params(params, {"q", "hl", "no_cache"})
    query = str(params.get("q") or "").strip()
    if not query:
        raise GoogleTrendsConfigError("autocomplete 场景缺少 q")
    if len(query) > 100:
        raise GoogleTrendsConfigError("q 最长 100 个字符")
    result = {"q": query}
    _copy_text(result, params, "hl")
    if "no_cache" in params:
        result["no_cache"] = _bool_text(params["no_cache"], "no_cache")
    return result


def _trending_now_params(params: dict[str, Any], geo: str) -> dict[str, Any]:
    """构造 `engine=google_trends_trending_now` 的业务参数。"""
    _reject_forbidden_params(params)
    _reject_unknown_params(
        params,
        {"geo", "category_id", "hours", "only_active", "hl", "no_cache"},
    )
    effective_geo = params.get("geo") if "geo" in params else geo
    result: dict[str, Any] = {"geo": _normalize_geo(effective_geo) or "US"}
    if "hours" in params:
        hours = str(params.get("hours") or "").strip()
        if hours not in TRENDING_NOW_HOURS:
            raise GoogleTrendsConfigError("hours 仅支持 4、24、48、168")
        result["hours"] = hours
    _copy_int(result, params, "category_id")
    if "only_active" in params:
        result["only_active"] = _bool_text(params["only_active"], "only_active")
    _copy_text(result, params, "hl")
    if "no_cache" in params:
        result["no_cache"] = _bool_text(params["no_cache"], "no_cache")
    return result


def _reject_forbidden_params(params: dict[str, Any]) -> None:
    """禁止调用方覆盖认证、引擎及同步执行约束。"""
    normalized = {str(key).replace("-", "_").lower() for key in params}
    forbidden = sorted(FORBIDDEN_PARAMS.intersection(normalized))
    if forbidden:
        raise GoogleTrendsConfigError(f"参数不允许传入：{forbidden[0]}")


def _reject_unknown_params(params: dict[str, Any], allowed: set[str]) -> None:
    """拒绝未声明参数，避免拼写错误消耗第三方额度。"""
    unknown = sorted(str(key) for key in params if str(key) not in allowed)
    if unknown:
        raise GoogleTrendsConfigError(f"不支持的参数：{unknown[0]}")


def _query_list(value: Any) -> list[str]:
    """将 q 规范化为最多五个非空查询词。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = [value]
    queries = [str(item).strip() for item in parts if str(item).strip()]
    if len(queries) > 5:
        raise GoogleTrendsConfigError("Google Trends 单次最多支持 5 个关键词")
    if any(len(query) > 100 for query in queries):
        raise GoogleTrendsConfigError("每个 q 最长 100 个字符")
    return queries


def _validate_keyword_count(data_type: str, keywords: list[str]) -> None:
    """按 SerpApi data_type 约束关键词数量。"""
    if data_type == "GEO_MAP" and not 2 <= len(keywords) <= 5:
        raise GoogleTrendsConfigError("GEO_MAP 需要 2 到 5 个关键词")
    if data_type in {"GEO_MAP_0", "RELATED_TOPICS", "RELATED_QUERIES"} and len(keywords) != 1:
        raise GoogleTrendsConfigError(f"{data_type} 仅支持 1 个关键词")


def _copy_text(result: dict[str, Any], params: dict[str, Any], field: str) -> None:
    """复制非空文本参数。"""
    if field not in params:
        return
    value = str(params.get(field) or "").strip()
    if value:
        result[field] = value


def _copy_int(result: dict[str, Any], params: dict[str, Any], field: str) -> None:
    """校验整数参数并以字符串传给 SerpApi。"""
    if field not in params or params.get(field) in {None, ""}:
        return
    try:
        result[field] = str(int(params[field]))
    except (TypeError, ValueError) as exc:
        raise GoogleTrendsConfigError(f"{field} 需要整数") from exc


def _bool_text(value: Any, field: str) -> str:
    """将布尔参数转换为 SerpApi 接受的小写字符串。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return "true"
    if text in {"0", "false", "no", "n", "off"}:
        return "false"
    raise GoogleTrendsConfigError(f"{field} 需要布尔值")


def _normalize_geo(value: Any) -> str:
    """将地区代码规范化为大写；空字符串表示全球。"""
    return str(value or "").strip().upper()


SCENARIOS: dict[str, GoogleTrendsScenario] = {
    "trends": GoogleTrendsScenario(
        scenario_id="trends",
        title="Google Trends 深度趋势分析",
        method="google_trends",
        required_params=("q",),
        param_builder=_trends_params,
        description="查询时间趋势、地域热度、相关主题或相关查询，最多比较 5 个查询词。",
        sample_params={"q": "flashlight", "data_type": "TIMESERIES", "date": "today 12-m"},
    ),
    "autocomplete": GoogleTrendsScenario(
        scenario_id="autocomplete",
        title="Google Trends 主题自动补全",
        method="google_trends_autocomplete",
        required_params=("q",),
        param_builder=_autocomplete_params,
        description="获取普通搜索词和 Google Trends Topic 候选，用于实体消歧。",
        sample_params={"q": "Apple", "hl": "en"},
    ),
    "trending-now": GoogleTrendsScenario(
        scenario_id="trending-now",
        title="Google Trends 当前热点",
        method="google_trends_trending_now",
        required_params=(),
        param_builder=_trending_now_params,
        description="按地区、时间和分类发现当前热门搜索，可只返回仍活跃的趋势。",
        sample_params={"geo": "US", "hours": 24, "only_active": True},
    ),
}
