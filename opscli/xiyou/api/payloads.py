"""西柚洞察接口 payload 构造。"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from opscli.xiyou.domain.exceptions import XiyouConfigError


SUPPORTED_SITES: frozenset[str] = frozenset({
    "US", "CA", "MX", "BR",
    "DE", "UK", "FR", "IT", "ES",
    "JP",
    "AE", "SA",
    "AU",
})

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
    text = (value or "").strip()
    if not text:
        return "US"
    alias = SITE_ALIASES.get(text) or SITE_ALIASES.get(text.lower())
    if alias:
        return alias
    code = text.upper()
    if code in SUPPORTED_SITES:
        return code
    supported = ", ".join(sorted(SUPPORTED_SITES))
    raise XiyouConfigError(
        f"西柚不支持站点 {value!r}；支持：{supported}（中文名如 '美国'、'日本' 也可识别）"
    )


def make_ranking_payload(params: dict[str, Any]) -> dict[str, Any]:
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
    site = _site(params)
    asins = _asins(params.get("asins"))
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
        # Xiyou 下载接口对多 ASIN 对比统一导出列表形态，view_mode 仅影响前端预览样式。
        "tableType": "multiAsinsComparisonList",
    }


def make_keyword_analysis_payload(params: dict[str, Any]) -> dict[str, Any]:
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
            "cycleFilter": _historical_traffic_cycle_filter(params),
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


def make_ad_analysis_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    asin = _asin(params.get("asin"))
    parent_asin = _parent_asin(params)
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "country": site,
            "parentAsin": parent_asin,
            "asins": _related_asins(params, asin),
            "page": _page(params),
            "pageSize": _page_size(params),
            "filters": {
                "searchTerms": _search_terms(params),
                "asins": [],
                "campaignTypes": [],
                "campaignTrafficRange": [None, None],
                "campaignTrafficRatioRange": [None, None],
                "campaignTrafficAcquisitionRateRange": [None, None],
                "spCampaignTrafficRange": [None, None],
                "sbCampaignTrafficRange": [None, None],
                "sbvCampaignTrafficRange": [None, None],
                "includeWords": {"mode": "oneOf", "words": []},
                "excludeWords": {"words": []},
                "searchTerm": [],
            },
            "cycleFilter": _ad_analysis_cycle_filter(params),
        },
    }


def make_parent_analysis_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    parent_asin = _parent_asin(params)
    keyword_type = normalize_asin_compare_keyword_type(params.get("keyword_type"))
    return {
        "resource": {"country": site, "parentAsin": parent_asin},
        "parentAsin": parent_asin,
        "query": params.get("query") or "",
        "page": _page(params),
        "pageSize": _page_size(params),
        "orders": [{"field": _reverse_keyword_order_field(keyword_type), "order": "desc"}],
        "filters": [{"field": "asinResearchType", "filter": [keyword_type]}],
        "rangeFilters": [],
        "cycleFilter": _keyword_cycle_filter(params),
        "country": site,
        "asins": _related_asins(params, None),
        "tableType": "variationCompareList",
        "asinsDisplayOrder": [],
    }


def make_sales_analysis_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    asin = _asin(params.get("asin"))
    parent_asin = _parent_asin(params)
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "parentAsin": parent_asin,
            "asin": asin,
            "country": site,
            "query": params.get("query") or asin,
            "parameterFilters": [],
            "rangeFilters": [],
            "cycleFilter": _sales_cycle_filter(params),
        },
    }


def make_flow_insight_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    asin = _asin(params.get("asin"))
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "asin": asin,
            "country": site,
            **_date_range_payload(params),
        },
    }


def make_flow_diagnosis_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    asin = _asin(params.get("asin"))
    keyword_type = normalize_asin_compare_keyword_type(params.get("keyword_type"))
    traffic_type = {
        "all": "total",
        "organic": "organic",
        "advertising": "advertising",
    }[keyword_type]
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "asin": asin,
            "country": site,
            "date": _flow_diagnosis_report_date(params),
            "trafficType": traffic_type,
        },
    }


def make_ad_insight_payload(params: dict[str, Any]) -> dict[str, Any]:
    return make_flow_insight_payload(params)


def make_flow_weekly_payload(params: dict[str, Any]) -> dict[str, Any]:
    site = _site(params)
    asin = _asin(params.get("asin"))
    date_range = _date_range_payload(params)
    date_range["endOfWeek"] = str(params.get("end_of_week") or "")
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "asin": asin,
            "country": site,
            **date_range,
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
    normalized = _optional_asins(value)
    if len(normalized) < 2:
        raise XiyouConfigError("asin-compare 至少需要 2 个 ASIN")
    return normalized


def _optional_asins(value: Any) -> list[str]:
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
    return normalized


def _keyword(value: Any) -> str:
    keyword = str(value or "").strip()
    if not keyword:
        raise XiyouConfigError("缺少参数：keyword")
    return keyword


def _parent_asin(params: dict[str, Any]) -> str:
    value = params.get("parent_asin") or params.get("parentAsin")
    asin = str(value or "").strip().upper()
    if not asin:
        raise XiyouConfigError("缺少参数：parent_asin")
    return asin


def _related_asins(params: dict[str, Any], primary_asin: str | None) -> list[str]:
    asins = _optional_asins(params.get("asins"))
    if primary_asin and primary_asin not in asins:
        asins.append(primary_asin)
    if not asins:
        raise XiyouConfigError("缺少参数：asins")
    return asins


def _search_terms(params: dict[str, Any]) -> list[str]:
    value = params.get("search_terms")
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        items = [str(part or "").strip() for part in value]
    else:
        items = []
    normalized = [item for item in items if item]
    if normalized:
        return normalized
    keyword = _optional_text(params.get("keyword"))
    query = _optional_text(params.get("query"))
    if keyword:
        return [keyword]
    if query:
        return [query]
    function = _optional_text(params.get("function"))
    if function and function.lower() == "ad-analysis":
        return []
    raise XiyouConfigError("缺少参数：search_terms 或 keyword/query")


def _default_cycle_filter() -> dict[str, Any]:
    return _daily_cycle_filter("last7days")


def _daily_cycle_filter(period: str) -> dict[str, Any]:
    return {
        "cycle": "daily",
        "period": period,
        "startCycle": {"startDate": "", "endDate": ""},
        "endCycle": {"startDate": "", "endDate": ""},
    }


def _date_range_payload(params: dict[str, Any]) -> dict[str, str]:
    start_date = _optional_text(params.get("start_date"))
    end_date = _optional_text(params.get("end_date"))
    if not start_date or not end_date:
        raise XiyouConfigError("缺少参数：start_date 和 end_date")
    return {
        "startDate": _parse_day(start_date).isoformat(),
        "endDate": _parse_day(end_date).isoformat(),
    }


def normalize_view_mode(value: Any) -> str:
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
        return {
            "all": "asinResearchTotalList",
            "organic": "asinResearchOrganicList",
            "advertising": "asinResearchAdvertisingList",
        }[keyword_type]
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
        "近一个月": 1,
        "3m": 3,
        "3months": 3,
        "3_months": 3,
        "3个月": 3,
        "近三个月": 3,
        "6m": 6,
        "6months": 6,
        "6_months": 6,
        "6个月": 6,
        "近六个月": 6,
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
        "近一年": 12,
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


def _ad_analysis_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    cycle_period = _optional_text(params.get("cycle_period"))
    start_month = _optional_text(params.get("start_month"))
    end_month = _optional_text(params.get("end_month"))

    if not cycle_period and not start_month and not end_month:
        return _default_cycle_filter()

    daily_presets = {
        "last7days": "last7days",
        "7d": "last7days",
        "7days": "last7days",
        "last_7_days": "last7days",
        "近7天": "last7days",
        "最近7天": "last7days",
        "last14days": "last14days",
        "14d": "last14days",
        "14days": "last14days",
        "last_14_days": "last14days",
        "近14天": "last14days",
        "最近14天": "last14days",
        "last30days": "last30days",
        "30d": "last30days",
        "30days": "last30days",
        "last_30_days": "last30days",
        "近30天": "last30days",
        "最近30天": "last30days",
    }
    normalized_daily_period = daily_presets.get(cycle_period or "")
    if normalized_daily_period:
        return _daily_cycle_filter(normalized_daily_period)

    return _keyword_cycle_filter(params)


def _sales_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    cycle_filter = _keyword_cycle_filter(params)
    if cycle_filter["cycle"] != "monthly":
        raise XiyouConfigError(
            "sales-analysis 仅支持月度区间，请使用 cycle_period=last1month/last3months/... 或 custom_month_range"
        )
    return cycle_filter


def _keyword_explorer_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    return _keyword_cycle_filter(params)


def _historical_traffic_cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    start_date = _optional_text(params.get("start_date"))
    end_date = _optional_text(params.get("end_date"))
    if start_date or end_date:
        raise XiyouConfigError(
            "keyword-historical-traffic 不支持用户自定义时间范围；固定导出最近一个月（不包含今天和昨天）"
        )

    cycle_period = _optional_text(params.get("cycle_period"))
    start_month = _optional_text(params.get("start_month"))
    end_month = _optional_text(params.get("end_month"))
    if cycle_period or start_month or end_month:
        raise XiyouConfigError(
            "keyword-historical-traffic 不支持用户自定义时间范围；固定导出最近一个月（不包含今天和昨天）"
        )

    latest_allowed = _today() - timedelta(days=2)
    start_anchor = latest_allowed - timedelta(days=29)
    return {
        "cycle": "daily",
        "period": "",
        "startCycle": {
            "startDate": start_anchor.isoformat(),
            "endDate": start_anchor.isoformat(),
        },
        "endCycle": {
            "startDate": latest_allowed.isoformat(),
            "endDate": latest_allowed.isoformat(),
        },
    }


def _report_date(params: dict[str, Any]) -> str:
    report_date = _optional_text(params.get("report_date"))
    if not report_date:
        return _today().isoformat()
    return _parse_day(report_date).isoformat()


def _flow_diagnosis_report_date(params: dict[str, Any]) -> str:
    report_date = _optional_text(params.get("report_date"))
    latest_allowed = _today() - timedelta(days=2)
    if not report_date:
        return latest_allowed.isoformat()
    parsed = _parse_day(report_date)
    if parsed > latest_allowed:
        raise XiyouConfigError("flow-diagnosis 诊断日期只能输入昨天之前的日期；对比日期固定为前一天")
    return parsed.isoformat()


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
