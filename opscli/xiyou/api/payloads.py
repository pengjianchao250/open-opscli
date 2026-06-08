"""西柚洞察接口 payload 构造。"""

from __future__ import annotations

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
    return {
        "resource": {"country": site, "asin": asin},
        "biz": {
            "asin": asin,
            "country": site,
            "page": _page(params),
            "pageSize": _page_size(params),
            "query": params.get("query") or "",
            "orders": [{"field": "follow", "order": "desc"}],
            "filters": [{"field": "asinResearchType", "filter": ["all"]}],
            "rangeFilters": [],
            "cycleFilter": _cycle_filter(params),
            "tableType": "asinResearchTotalList",
        },
    }


def make_asin_compare_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造多 ASIN 对比主表 resource payload。"""
    site = _site(params)
    asins = _asins(params.get("asins"))
    return {
        "resource": {"country": site, "asins": asins},
        "asins": asins,
        "country": site,
        "query": params.get("query") or "",
        "page": _page(params),
        "pageSize": _page_size(params),
        "orders": [{"field": "follow", "order": "desc", "value": ""}],
        "filters": [{"field": "asinResearchType", "filter": ["all"]}],
        "rangeFilters": [],
        "cycleFilter": _cycle_filter(params),
        "tableType": "multiAsinsComparisonList",
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
        "cycleFilter": _cycle_filter(params),
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
        "cycleFilter": _cycle_filter(params),
        "query": params.get("query") or "",
        "rangeFilters": [],
        "correlationTierAsins": [],
        "customCorrelationTier": [],
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


def _cycle_filter(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle": "daily",
        "period": params.get("cycle_period") or "last7days",
        "startCycle": {"startDate": "", "endDate": ""},
        "endCycle": {"startDate": "", "endDate": ""},
    }
