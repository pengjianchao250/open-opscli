"""西柚洞察接口 payload 构造。"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from opscli.xiyou.domain.exceptions import XiyouConfigError


# 西柚洞察支持的站点白名单（依据西柚官网"站点选择"下拉框）
# 单一可信源：opscli/xiyou/services/api_manager.py::scenarios() 也从这里派生
SUPPORTED_SITES: frozenset[str] = frozenset({
    "US", "CA", "MX", "BR",            # 北美及拉美
    "DE", "UK", "FR", "IT", "ES",      # 欧洲
    "JP",                              # 日本
    "AE", "SA",                        # 中东
    "AU",                              # 澳洲
})

# 自然语言别名 → 西柚站点 code 兜底映射
# Agent 通常会自己把中文国家名映射为 code，这里仅作为 CLI 直传中文 / Agent 偶发误传时的兜底
SITE_ALIASES: dict[str, str] = {
    "美国": "US", "美国站": "US",
    "加拿大": "CA", "加拿大站": "CA",
    "墨西哥": "MX", "墨西哥站": "MX",
    "巴西": "BR", "巴西站": "BR",
    "德国": "DE", "德国站": "DE",
    "英国": "UK", "英国站": "UK", "gb": "UK",
    "法国": "FR", "法国站": "FR",
    "意大利": "IT", "意大利站": "IT",
    "西班牙": "ES", "西班牙站": "ES",
    "日本": "JP", "日本站": "JP",
    "阿联酋": "AE", "阿联酋站": "AE",
    "沙特": "SA", "沙特站": "SA", "沙特阿拉伯": "SA",
    "澳大利亚": "AU", "澳大利亚站": "AU", "澳洲": "AU", "澳洲站": "AU",
}


def normalize_site(value: str | None) -> str:
    """归一化站点取值，未支持的站点提前抛错避免到西柚后端才报错。

    支持三种输入：
    - 西柚 code（大小写不敏感，如 ``us``/``US``）
    - 中文国家名（如"美国"、"日本站"）
    - 空值（回退默认 ``US``）
    """
    text = (value or "").strip()
    if not text:
        return "US"
    # 1) 别名表查中文 / 全名（原文 + 小写两次）
    alias = SITE_ALIASES.get(text) or SITE_ALIASES.get(text.lower())
    if alias:
        return alias
    # 2) 大写后查白名单
    code = text.upper()
    if code in SUPPORTED_SITES:
        return code
    # 3) 不支持，提前 fail-fast 并列出允许值
    supported = ", ".join(sorted(SUPPORTED_SITES))
    raise XiyouConfigError(
        f"西柚不支持站点 {value!r}；支持：{supported}（中文名如'美国'、'日本'也可识别）"
    )


def make_ranking_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造排行榜接口 payload。"""
    return {
        "biz": {
            "country": _site(params),
            "filed": params.get("period") or "week",
            "page": int(params.get("page") or 1),
            "pageSize": int(params.get("page_size") or params.get("pageSize") or 50),
            "query": params.get("query") or "",
            "rankPattern": params.get("rank_pattern") or params.get("rankPattern"),
        }
    }


def make_reverse_keyword_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造反查关键词主表 resource payload。"""
    site = _site(params)
    asin = _asin(params.get("asin"))
    view_mode = normalize_reverse_keyword_view(params.get("view_mode"))
    keyword_type = normalize_asin_compare_keyword_type(params.get("keyword_type"))
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "asin": asin,
            "country": site,
            "page": _page(params),
            "pageSize": _page_size(params),
            "query": params.get("query") or "",
            "orders": [{"field": _reverse_keyword_order_field(keyword_type), "order": "desc"}],
            "filters": [{"field": "asinResearchType", "filter": [keyword_type]}],
            "rangeFilters": [],
            "cycleFilter": _keyword_cycle_filter(params),
            "tableType": _reverse_keyword_table_type(view_mode, keyword_type),
        },
    }


def make_asin_compare_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造多 ASIN 对比主表 resource payload。"""
    site = _site(params)
    asins = _asins(params.get("asins"))
    view_mode = normalize_asin_compare_view(params.get("view_mode"))
    keyword_type = normalize_asin_compare_keyword_type(params.get("keyword_type"))
    return {
        "resource": {"country": site, "asins": asins},
        "asins": asins,
        "country": site,
        "query": params.get("query") or "",
        "page": _page(params),
        "pageSize": _page_size(params),
        "orders": [{"field": "follow", "order": "desc", "value": ""}],
        "filters": [{"field": "asinResearchType", "filter": [keyword_type]}],
        "rangeFilters": [],
        "cycleFilter": _keyword_cycle_filter(params),
        "tableType": "multiAsinsComparisonList" if view_mode == "data" else "multiAsinsComparisonOrTop10",
    }


def make_keyword_analysis_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造关键词分析主表 resource payload。"""
    site = _site(params)
    keyword = _keyword(params.get("keyword"))
    return {
        "resource": {"country": site, "searchTerm": keyword},
        "query": params.get("query") or "",
        "searchTerm": keyword,
        "country": site,
        "page": _page(params),
        "pageSize": _page_size(params),
        "orders": [{"field": "traffic", "order": "desc"}],
        "filters": [],
        "rangeFilters": [],
        "cycleFilter": _keyword_cycle_filter(params),
    }


def make_keyword_explorer_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造以词找词主表 resource payload。"""
    site = _site(params)
    keyword = _keyword(params.get("keyword"))
    return {
        "resource": {"country": site, "searchTerm": keyword},
        "searchTerm": keyword,
        "country": site,
        "page": _page(params),
        "pageSize": _page_size(params),
        "orders": [],
        "filters": [],
        "cycleFilter": _keyword_explorer_cycle_filter(params),
        "query": params.get("query") or "",
        "rangeFilters": [],
        "correlationTierAsins": [],
        "customCorrelationTier": [],
    }


def make_keyword_historical_traffic_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    keyword = _keyword(params.get("keyword"))
    return {
        "resource": {"country": site, "searchTerm": keyword},
        "biz": {
            "country": site,
            "searchTerm": keyword,
            "cycleFilter": _date_range_cycle_filter(params),
            "page": _page(params),
            "pageSize": _page_size(params),
            "trafficCampaignType": "organicCampaign",
        },
    }


def make_keyword_ad_replay_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    keyword = _keyword(params.get("keyword"))
    return {
        "resource": {"country": site, "searchTerm": keyword},
        "country": site,
        "searchTerm": keyword,
        "reportDate": _report_date(params),
    }


def make_keyword_organic_replay_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    keyword = _keyword(params.get("keyword"))
    return {
        "resource": {"country": site, "searchTerm": keyword},
        "biz": {
            "country": site,
            "searchTerm": keyword,
            "reportDate": _report_date(params),
        },
    }


def make_keyword_ad_toppers_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    keyword = _keyword(params.get("keyword"))
    return {
        "resource": {"country": site, "searchTerm": keyword},
        "biz": {
            "country": site,
            "searchTerm": keyword,
        },
    }


def _site(params: dict[str, Any]) -> str:
    return normalize_site(params.get("site") or params.get("country"))


def _page(params: dict[str, Any]) -> int:
    return int(params.get("page") or 1)


def _page_size(params: dict[str, Any]) -> int:
    return int(params.get("page_size") or params.get("pageSize") or 50)


def _asin(value: Any) -> str:
    asin = str(value or "").strip().upper()
    if not asin:
        raise XiyouConfigError("缺少参数：asin")
    return asin


def _asins(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        asin = str(raw_value or "").strip().upper()
        if asin and asin not in seen:
            seen.add(asin)
            normalized.append(asin)
    if len(normalized) < 2:
        raise XiyouConfigError("asin-compare 至少需要 2 个 ASIN")
    return normalized


def _keyword(value: Any) -> str:
    keyword = str(value or "").strip()
    if not keyword:
        raise XiyouConfigError("缺少参数：keyword")
    return keyword


def _default_cycle_filter() -> dict[str, Any]:
    return {
        "cycle": "daily",
        "period": "last7days",
        "startCycle": {"startDate": "", "endDate": ""},
        "endCycle": {"startDate": "", "endDate": ""},
    }


def normalize_view_mode(value: Any) -> str:
    """归一化关键词分析视图模式。"""
    text = _optional_text(value)
    if not text:
        return "data"
    normalized = text.lower().replace("-", "_")
    aliases = {
        "data": "data",
        "datalist": "data",
        "data_list": "data",
        "数据": "data",
        "数据视图": "data",
        "trends": "trends",
        "trend": "trends",
        "trendsview": "trends",
        "trends_view": "trends",
        "趋势": "trends",
        "趋势视图": "trends",
    }
    mapped = aliases.get(normalized)
    if mapped:
        return mapped
    raise XiyouConfigError("view_mode 仅支持：data, trends")


def normalize_reverse_keyword_view(value: Any) -> str:
    text = _optional_text(value)
    if not text:
        return "data"
    normalized = text.lower().replace("-", "_")
    aliases = {
        "data": "data",
        "datalist": "data",
        "data_list": "data",
        "数据": "data",
        "数据视图": "data",
        "trends": "trends",
        "trend": "trends",
        "trendsview": "trends",
        "trends_view": "trends",
        "趋势": "trends",
        "趋势视图": "trends",
        "top10": "top10",
        "top_10": "top10",
        "naturaltop10": "top10",
        "natural_top10": "top10",
        "自然top10": "top10",
        "自然top_10": "top10",
        "自然top10视图": "top10",
    }
    mapped = aliases.get(normalized)
    if mapped:
        return mapped
    raise XiyouConfigError("reverse-keyword view_mode 仅支持：data, trends, top10")


def normalize_replay_type(value: Any) -> str:
    text = _optional_text(value)
    if not text:
        return "oor"
    normalized = text.lower().replace("-", "_")
    aliases = {
        "ac": "ac",
        "oor": "oor",
        "natural_ac": "ac",
        "natural_oor": "oor",
        "ac_rank": "ac",
        "oor_rank": "oor",
        "自然_ac": "ac",
        "自然_oor": "oor",
        "自然排名_ac": "ac",
        "自然排名_oor": "oor",
    }
    mapped = aliases.get(normalized)
    if mapped:
        return mapped
    raise XiyouConfigError("replay_type 仅支持：ac, oor")


def normalize_asin_compare_view(value: Any) -> str:
    text = _optional_text(value)
    if not text:
        return "data"
    normalized = text.lower().replace("-", "_")
    aliases = {
        "data": "data",
        "datalist": "data",
        "data_list": "data",
        "数据": "data",
        "数据视图": "data",
        "top10": "top10",
        "top_10": "top10",
        "naturaltop10": "top10",
        "natural_top10": "top10",
        "自然top10": "top10",
        "自然top_10": "top10",
        "自然top10视图": "top10",
    }
    mapped = aliases.get(normalized)
    if mapped:
        return mapped
    raise XiyouConfigError("asin-compare view_mode 仅支持：data, top10")


def normalize_asin_compare_keyword_type(value: Any) -> str:
    text = _optional_text(value)
    if not text:
        return "all"
    normalized = text.lower().replace("-", "_")
    aliases = {
        "all": "all",
        "all_keywords": "all",
        "所有关键词": "all",
        "organic": "organic",
        "organic_keywords": "organic",
        "自然关键词": "organic",
        "advertising": "advertising",
        "ad": "advertising",
        "ad_keywords": "advertising",
        "advertising_keywords": "advertising",
        "广告关键词": "advertising",
    }
    mapped = aliases.get(normalized)
    if mapped:
        return mapped
    raise XiyouConfigError("keyword_type 仅支持：all, organic, advertising")


def _reverse_keyword_order_field(keyword_type: str) -> str:
    return {
        "all": "follow",
        "organic": "organicTraffic",
        "advertising": "adTraffic",
    }[keyword_type]


def _reverse_keyword_table_type(view_mode: str, keyword_type: str) -> str:
    if view_mode == "data":
        return "asinResearchTotalList"
    if view_mode == "top10":
        return "asinResearchOrganicTop10"
    return {
        "all": "asinResearchTrendsViewSearchTerm",
        "organic": "asinResearchTrendsViewOrganicSearchTerm",
        "advertising": "asinResearchTrendsViewAdvertisingSearchTerm",
    }[keyword_type]


def _keyword_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    cycle_period = _optional_text(params.get("cycle_period"))
    start_month = _optional_text(params.get("start_month"))
    end_month = _optional_text(params.get("end_month"))

    if not cycle_period and not start_month and not end_month:
        return _default_cycle_filter()

    if not cycle_period and start_month and end_month:
        cycle_period = "custom_month_range"

    if cycle_period in (None, "", "last7days"):
        return _default_cycle_filter()

    monthly_presets = {
        "last1month": 1,
        "last3months": 3,
        "last6months": 6,
        "last12months": 12,
        "1m": 1,
        "1month": 1,
        "1_month": 1,
        "一个月": 1,
        "1个月": 1,
        "近1个月": 1,
        "3m": 3,
        "3months": 3,
        "3_months": 3,
        "3个月": 3,
        "近3个月": 3,
        "6m": 6,
        "6months": 6,
        "6_months": 6,
        "6个月": 6,
        "近6个月": 6,
        "半年": 6,
        "halfyear": 6,
        "half_year": 6,
        "12m": 12,
        "12months": 12,
        "12_months": 12,
        "12个月": 12,
        "近12个月": 12,
        "1y": 12,
        "1year": 12,
        "1_year": 12,
        "一年": 12,
        "1年": 12,
        "近1年": 12,
    }
    if cycle_period in monthly_presets:
        months_back = monthly_presets[cycle_period]
        end_anchor = _first_day_of_month(_today())
        start_anchor = _shift_month(end_anchor, -months_back)
        return _monthly_cycle_filter(start_anchor, end_anchor)

    if cycle_period in {"custom_month_range", "custom"}:
        if not start_month or not end_month:
            raise XiyouConfigError("自定义月区间需要同时提供 start_month 和 end_month，格式 YYYY-MM")
        start_anchor = _parse_month(start_month)
        end_anchor = _parse_month(end_month)
        if start_anchor > end_anchor:
            raise XiyouConfigError("start_month 不能晚于 end_month")
        return _monthly_cycle_filter(start_anchor, end_anchor)

    raise XiyouConfigError(
        "cycle_period 仅支持：last7days, last1month, last3months, last6months, last12months, custom_month_range"
    )


def _keyword_explorer_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    return _keyword_cycle_filter(params)


def _date_range_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    start_date = _optional_text(params.get("start_date"))
    end_date = _optional_text(params.get("end_date"))
    if not start_date and not end_date:
        end_anchor = _today() - timedelta(days=1)
        start_anchor = end_anchor - timedelta(days=29)
    elif start_date and end_date:
        start_anchor = _parse_day(start_date)
        end_anchor = _parse_day(end_date)
    else:
        raise XiyouConfigError("start_date 和 end_date 需要同时提供，格式 YYYY-MM-DD")
    if start_anchor > end_anchor:
        raise XiyouConfigError("start_date 不能晚于 end_date")
    return {
        "cycle": "daily",
        "period": "",
        "startCycle": {
            "startDate": start_anchor.isoformat(),
            "endDate": start_anchor.isoformat(),
        },
        "endCycle": {
            "startDate": end_anchor.isoformat(),
            "endDate": end_anchor.isoformat(),
        },
    }


def _report_date(params: dict[str, Any]) -> str:
    report_date = _optional_text(params.get("report_date"))
    if not report_date:
        return _today().isoformat()
    return _parse_day(report_date).isoformat()


def _monthly_cycle_filter(start_anchor: date, end_anchor: date) -> dict[str, Any]:
    return {
        "cycle": "monthly",
        "period": "",
        "startCycle": _month_range(start_anchor),
        "endCycle": _month_range(end_anchor),
    }


def _month_range(anchor: date) -> dict[str, str]:
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    start = date(anchor.year, anchor.month, 1)
    end = date(anchor.year, anchor.month, last_day)
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    }


def _parse_month(value: str) -> date:
    text = value.strip()
    parts = text.split("-")
    if len(parts) != 2:
        raise XiyouConfigError(f"月份格式错误：{value}，应为 YYYY-MM")
    try:
        year = int(parts[0])
        month = int(parts[1])
        return date(year, month, 1)
    except ValueError as exc:
        raise XiyouConfigError(f"月份格式错误：{value}，应为 YYYY-MM") from exc


def _parse_day(value: str) -> date:
    text = value.strip()
    parts = text.split("-")
    if len(parts) != 3:
        raise XiyouConfigError(f"日期格式错误：{value}，应为 YYYY-MM-DD")
    try:
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])
        return date(year, month, day)
    except ValueError as exc:
        raise XiyouConfigError(f"日期格式错误：{value}，应为 YYYY-MM-DD") from exc


def _shift_month(anchor: date, offset: int) -> date:
    month_index = anchor.year * 12 + (anchor.month - 1) + offset
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _first_day_of_month(value: date) -> date:
    return date(value.year, value.month, 1)


def _today() -> date:
    return date.today()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
