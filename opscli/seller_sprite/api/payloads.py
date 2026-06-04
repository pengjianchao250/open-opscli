"""卖家精灵场景 payload 构造。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


PRODUCT_RESEARCH_RECOMMENDATION_PRESETS: dict[str, dict[str, Any]] = {
    "低价长尾选品": {
        "minRanking": "10000",
        "maxRanking": "50000",
        "maxSales": "300",
        "maxPrice": "30",
        "maxSellers": "1",
    },
    "研发新品榜": {
        "productTags": ["NewRelease"],
        "sellerTypes": ["FBA", "FBM"],
        "maxSales": "500",
    },
    "潜力单变体": {
        "putawayMonth": "6",
        "minTotalUnitsGrowth": "20",
        "maxVariations": "1",
    },
    "销量飙升": {
        "minSales": "300",
        "minTotalUnitsGrowth": "10",
    },
    "潜力市场": {
        "putawayMonth": "6",
        "minTotalUnitsGrowth": "10",
        "maxSales": "600",
    },
    "未被满足的市场": {
        "sellerTypes": ["FBM"],
        "minSales": "300",
        "putawayMonth": "6",
    },
    "不压库存的市场": {
        "minSales": "600",
        "minSellers": "3",
        "putawayMonth": "6",
    },
    "投机市场": {
        "minSales": "300",
        "maxReviews": "50",
        "putawayMonth": "6",
    },
    "高需求低要求市场": {
        "minRankingCr": "99",
        "maxReviews": "10",
        "putawayMonth": "3",
    },
    "全品类铺货": {
        "minRankingCr": "99",
        "putawayMonth": "3",
    },
    "精品铺货": {
        "minRankingCr": "99",
        "putawayMonth": "3",
    },
    "低价商品": {
        "eligibility": ["Y"],
        "maxPrice": "10",
        "smallAndLight": "lowPrice",
        "lowPrice": "Y",
    },
    "新手推荐": {
        "sellerTypes": ["FBA"],
        "minSales": "300",
        "minTotalUnitsGrowth": "3",
        "minPrice": "15",
        "maxPrice": "60",
        "putawayMonth": "12",
    },
}

PRODUCT_RESEARCH_RECOMMENDATION_ALIASES: dict[str, str] = {
    "low-price-long-tail": "低价长尾选品",
    "new-product-list": "研发新品榜",
    "new-release": "研发新品榜",
    "potential-single-variant": "潜力单变体",
    "rapid-growth": "销量飙升",
    "potential": "潜力市场",
    "improved": "未被满足的市场",
    "fulfilled": "不压库存的市场",
    "speculative": "投机市场",
    "high-demand": "高需求低要求市场",
    "distribution-categories": "全品类铺货",
    "competitive-products": "精品铺货",
    "small-light": "低价商品",
    "low-price": "低价商品",
    "newbie-recommend": "新手推荐",
}

PRODUCT_RESEARCH_OFFICIAL_FIELD_ALIASES: dict[str, str] = {
    "minUnits": "minSales",
    "maxUnits": "maxSales",
    "minRevenue": "minAmount",
    "maxRevenue": "maxAmount",
    "minUnitsCr": "minTotalUnitsGrowth",
    "maxUnitsCr": "maxTotalUnitsGrowth",
    "minRatings": "minReviews",
    "maxRatings": "maxReviews",
    "minRatingsCv": "minReviewsGrouth",
    "maxRatingsCv": "maxReviewsGrouth",
    "minStar": "minReviewRating",
    "maxStar": "maxReviewRating",
    "availableMonth": "putawayMonth",
    "fulfillment": "sellerTypes",
    "dimensionType": "pkgDimensionTypeList",
    "sellerNation": "sellerNationList",
    "minVariations": "minVariations",
    "maxVariations": "maxVariations",
    "variation": "maxVariations",
    "minBsr": "minRanking",
    "maxBsr": "maxRanking",
    "minBsrCv": "minRankingCv",
    "maxBsrCv": "maxRankingCv",
    "minBsrCr": "minRankingCr",
    "maxBsrCr": "maxRankingCr",
    "minLqs": "lqsFrom",
    "maxLqs": "lqsTo",
    "excludeKeywords": "outOfKeywords",
    "minSellers": "minSellers",
    "maxSellers": "maxSellers",
}


def make_competitor_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造竞品查询 payload。"""
    market = _market(input_data)
    month = input_data.get("month") or input_data.get("period") or "202604"
    payload: dict[str, Any] = {
        "market": market,
        "monthName": input_data.get("monthName") or month_name(month),
        "asins": csv(input_data.get("asins")),
        "page": _int(input_data.get("page") or input_data.get("startPage"), 1),
        "nodeIdPaths": csv(input_data.get("node") or input_data.get("nodeIdPaths")),
        "symbolFlag": False,
        "size": _int(input_data.get("size") or input_data.get("pageSize"), 100),
        "order": {
            "field": input_data.get("orderField") or "amz_unit",
            "desc": order_desc(input_data.get("orderDesc")),
        },
        "lowPrice": input_data.get("lowPrice") or "N",
    }
    if input_data.get("keywords") or input_data.get("keyword"):
        payload["keywords"] = input_data.get("keywords") or input_data.get("keyword")
    for key in ["brand", "sellerName"]:
        if input_data.get(key):
            payload[key] = input_data[key]
    return payload


def make_product_research_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造选产品 payload。"""
    input_data = normalize_product_research_input(input_data)
    month = input_data.get("month") or input_data.get("period") or "2026-03"
    preset = product_research_recommendation_preset(input_data)
    payload: dict[str, Any] = {
        "market": _market(input_data, default="JP"),
        "page": _int(input_data.get("page") or input_data.get("startPage"), 1),
        "size": _int(input_data.get("size") or input_data.get("pageSize"), 100),
        "symbolFlag": False,
        "monthName": input_data.get("monthName") or month_name(month),
        "selectType": str(input_data.get("selectType") or "2"),
        "filterSub": truthy(input_data.get("filterSub")) if input_data.get("filterSub") is not None else False,
        "weightUnit": input_data.get("weightUnit") or "g",
        "order": {
            "field": input_data.get("orderField") or "amz_unit",
            "desc": order_desc(input_data.get("orderDesc")),
        },
        "productTags": [],
        "nodeIdPaths": csv(input_data.get("node") or input_data.get("category") or input_data.get("nodeIdPaths")),
        "sellerTypes": [],
        "eligibility": [],
        "pkgDimensionTypeList": csv(input_data.get("pkgDimensionTypeList")),
        "sellerNationList": csv(input_data.get("sellerNationList")),
        "smallAndLight": input_data.get("smallAndLight") or "N",
        "lowPrice": input_data.get("lowPrice") or "N",
    }
    payload.update(preset)
    _append_product_list_filters(payload, input_data)
    _append_product_range_filters(payload, input_data)
    _append_product_extra_filters(payload, input_data)
    for key in [
        "keyword",
        "keywords",
        "includeBrands",
        "excludeBrands",
        "includeSellers",
        "excludeSellers",
        "outOfKeywords",
    ]:
        if input_data.get(key):
            payload[key] = input_data[key]
    return payload


def make_keyword_miner_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造关键词挖掘 payload。"""
    month = input_data.get("historyDate") or input_data.get("month") or input_data.get("monthName") or "nearly"
    return {
        "keyword": input_data.get("keyword") or input_data.get("q") or "flashlight",
        "market": _int(input_data.get("marketId") or market_id(_market(input_data, default="JP")), 6),
        "pageNum": _int(input_data.get("pageNum") or input_data.get("page") or input_data.get("startPage"), 1),
        "pageSize": _int(input_data.get("pageSize") or input_data.get("size"), 100),
        "historyDate": history_date(month),
        "orderBy": _int(input_data.get("orderBy"), 5),
        "desc": order_desc(input_data.get("desc")),
        "filterRootWord": _int(
            input_data.get("filterRootWord")
            if input_data.get("filterRootWord") is not None
            else 1 if truthy(input_data.get("rootWord")) or truthy(input_data.get("filterRootWordEnabled")) else 0,
            0,
        ),
        "matchType": _int(input_data.get("matchType"), 0),
        "amazonChoice": truthy(input_data.get("amazonChoice")),
        "keywordBidMatchType": input_data.get("keywordBidMatchType") or "exact",
        "includeHighFrequency": truthy(input_data.get("includeHighFrequency"), default=True),
        "groupNum": _int(input_data.get("groupNum"), 1),
    }


def make_keyword_reverse_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造关键词反查 payload。"""
    limit = _int(input_data.get("limit") or input_data.get("size") or input_data.get("pageSize"), 100)
    page = _int(input_data.get("page") or input_data.get("pageNum") or input_data.get("startPage"), 1)
    skip = _int(input_data.get("skip"), (page - 1) * limit)
    month = input_data.get("historyDate") or input_data.get("month") or input_data.get("monthName") or "nearly"
    market = _market(input_data, default=station_from_market_id(input_data.get("marketId") or 6))
    return {
        "asin": input_data.get("asin") or input_data.get("q") or "B07YRMT36L",
        "market": market,
        "limit": limit,
        "skip": skip,
        "page": page,
        "month": history_date(month),
        "badges": csv(input_data.get("badges")),
        "conversionKeywordTypes": csv(input_data.get("conversionKeywordTypes")),
        "trafficKeywordTypes": csv(input_data.get("trafficKeywordTypes")),
        "order": _int(input_data.get("order"), 12),
        "desc": order_desc(input_data.get("desc")),
        "exactly": truthy(input_data.get("exactly")),
        "keywordBidMatchType": input_data.get("keywordBidMatchType") or "exact",
        "filterDeletedKeywords": truthy(input_data.get("filterDeletedKeywords")),
    }


def make_traffic_source_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造查流量来源 payload。"""
    month = input_data.get("historyDate") or input_data.get("month") or input_data.get("monthName") or "nearly"
    return {
        "keywordOrAsin": _query_text(
            input_data.get("keywordOrAsin")
            or input_data.get("keyword")
            or input_data.get("asin")
            or input_data.get("asins")
            or input_data.get("q")
        ),
        "market": traffic_source_market(_market(input_data, default="US")),
        "pageNo": _int(input_data.get("pageNo") or input_data.get("page") or input_data.get("startPage"), 1),
        "pageSize": _int(input_data.get("pageSize") or input_data.get("size"), 100),
        "order": _int(input_data.get("order"), 10),
        "desc": order_desc(input_data.get("desc")),
        "month": history_date(month),
    }


def make_market_research_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造选市场表单 payload。"""
    month = input_data.get("month") or input_data.get("period") or "nearly"
    payload: dict[str, Any] = {
        "marketId": str(input_data.get("marketId") or market_research_market_id(_market(input_data, default="US"))),
        "nodeIdPath": _query_text(input_data.get("nodeIdPath") or input_data.get("node") or input_data.get("category")),
        "sampleNumber": str(input_data.get("sampleNumber") or 1),
        "topn": str(input_data.get("topn") or input_data.get("topN") or 10),
        "newReleaseNum": str(new_release_num(input_data)),
        "order.field": input_data.get("orderField") or input_data.get("order.field") or "total_sales",
        "order.desc": str(order_desc(input_data.get("orderDesc") or input_data.get("order.desc"))).lower(),
        "tab": str(input_data.get("tab") or 1),
        "monthName": input_data.get("monthName") or month_name(month),
        "page": str(_int(input_data.get("page") or input_data.get("startPage"), 1)),
        "size": str(_int(input_data.get("size") or input_data.get("pageSize"), 100)),
    }
    if input_data.get("departmentKeyword") or input_data.get("keyword"):
        payload["departmentKeyword"] = _query_text(input_data.get("departmentKeyword") or input_data.get("keyword"))
    return payload


def build_referer(payload: dict[str, Any], scenario: str) -> str:
    """按场景构造 Web referer。"""
    if scenario == "keyword-miner":
        return "https://www.sellersprite.com/v3/keyword-miner/"
    if scenario == "keyword-reverse":
        query = {
            "q": payload.get("asin") or "",
            "marketId": market_id(payload.get("market") or "JP"),
            "date": payload.get("month") or "",
            "badges": ",".join(payload.get("badges") or []),
        }
        return f"https://www.sellersprite.com/v3/keyword-reverse/?{urlencode(query)}"
    if scenario == "traffic-source":
        query = {
            "asin": payload.get("keywordOrAsin") or "",
            "marketId": traffic_source_market_id(payload.get("market")),
            "date": payload.get("month") or "",
        }
        return f"https://www.sellersprite.com/v3/reversing/sources?{urlencode(query)}"
    if scenario == "market-research":
        query = _flatten_query(payload)
        return f"https://www.sellersprite.com/v2/market-research?{urlencode(query)}"

    path = "product-research" if scenario == "product-research" else "competitor-lookup"
    query = _flatten_query(payload)
    return f"https://www.sellersprite.com/v3/{path}?{urlencode(query)}"


def month_name(value: Any) -> str:
    """转换竞品类接口月份字段。"""
    text = str(value)
    if text in {"30d", "nearly", "latest30", "last30"}:
        return "bsr_sales_nearly"
    if text.startswith("bsr_sales_"):
        return text
    return f"bsr_sales_monthly_{text.replace('-', '')}"


def history_date(value: Any) -> str:
    """转换关键词类接口月份字段。"""
    text = str(value or "")
    if not text or text in {"30d", "nearly", "latest30", "last30", "bsr_sales_nearly"}:
        return ""
    if text.startswith("bsr_sales_monthly_"):
        return text.replace("bsr_sales_monthly_", "")
    return text.replace("-", "")


def market_id(value: Any) -> int | Any:
    """站点代码转卖家精灵 market id。"""
    markets = {
        "US": 1,
        "UK": 3,
        "DE": 4,
        "FR": 5,
        "JP": 6,
        "CA": 7,
        "IT": 8,
        "ES": 9,
        "IN": 10,
        "MX": 11,
    }
    return markets.get(str(value or "").upper(), value)


def market_research_market_id(value: Any) -> int | Any:
    """选市场页面站点代码转 market id。"""
    markets = {
        "US": 1,
        "UK": 3,
        "DE": 4,
        "FR": 5,
        "JP": 6,
        "CA": 7,
        "IT": 35691,
        "ES": 44551,
        "IN": 44571,
        "MX": 771770,
    }
    return markets.get(str(value or "").upper(), value)


def station_from_market_id(value: Any) -> str:
    """卖家精灵 market id 转站点代码。"""
    stations = {
        1: "US",
        3: "UK",
        4: "DE",
        5: "FR",
        6: "JP",
        7: "CA",
        8: "IT",
        9: "ES",
        10: "IN",
        11: "MX",
    }
    return stations.get(_int(value, 6), str(value))


def traffic_source_market(value: Any) -> str:
    """站点代码转流量来源接口 market。"""
    markets = {
        "US": "COM",
        "UK": "UK",
        "DE": "DE",
        "FR": "FR",
        "JP": "JP",
        "CA": "CA",
        "IT": "IT",
        "ES": "ES",
        "IN": "IN",
        "MX": "MX",
    }
    return markets.get(str(value or "").upper(), str(value or "COM").upper())


def traffic_source_market_id(value: Any) -> int | Any:
    """流量来源接口 market 转 Web 页面 marketId。"""
    markets = {
        "COM": 1,
        "US": 1,
        "UK": 3,
        "DE": 4,
        "FR": 5,
        "JP": 6,
        "CA": 7,
        "IT": 8,
        "ES": 9,
        "IN": 10,
        "MX": 11,
    }
    return markets.get(str(value or "").upper(), value)


def csv(value: Any) -> list[str]:
    """逗号分隔参数转列表。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _query_text(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def order_desc(value: Any) -> bool:
    """解析排序方向。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).lower() != "false"


def truthy(value: Any, *, default: bool = False) -> bool:
    """解析布尔参数。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y"}


def new_release_num(input_data: dict[str, Any]) -> int:
    """解析新品定义月份数。"""
    value = (
        input_data.get("newReleaseNum")
        or input_data.get("newReleaseMonths")
        or input_data.get("newProductMonths")
        or input_data.get("newRelease")
    )
    if value is None:
        return 6
    text = str(value).strip().lower()
    aliases = {
        "1": 1,
        "1m": 1,
        "one_month": 1,
        "1个月内上架": 1,
        "一个月内上架": 1,
        "3": 3,
        "3m": 3,
        "three_months": 3,
        "3个月内上架": 3,
        "三个月内上架": 3,
        "6": 6,
        "6m": 6,
        "half_year": 6,
        "半年内上架": 6,
    }
    return aliases.get(text, _int(value, 6))


def product_research_recommendation_preset(input_data: dict[str, Any]) -> dict[str, Any]:
    """解析选产品推荐模式并返回对应筛选参数。"""
    value = (
        input_data.get("recommendationMode")
        or input_data.get("recommendMode")
        or input_data.get("presetMode")
        or input_data.get("productMode")
        or input_data.get("mode")
        or input_data.get("推荐模式")
    )
    if not value:
        return {}
    text = str(value).strip()
    mode = PRODUCT_RESEARCH_RECOMMENDATION_ALIASES.get(_preset_key(text), text)
    preset = PRODUCT_RESEARCH_RECOMMENDATION_PRESETS.get(mode)
    return dict(preset or {})


def normalize_product_research_input(input_data: dict[str, Any]) -> dict[str, Any]:
    """兼容 SellerSprite 官方开放 API 的选产品入参命名。"""
    normalized = dict(input_data)
    for source, target in PRODUCT_RESEARCH_OFFICIAL_FIELD_ALIASES.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    badge_nr = normalized.get("badgeNR")
    if badge_nr is not None and "productTags" not in normalized and truthy(badge_nr):
        normalized["productTags"] = ["NewRelease"]
    badge_map = {
        "badgeBS": "BestSeller",
        "badgeAC": "AmazonChoice",
        "badgeNR": "NewRelease",
    }
    tags = csv(normalized.get("productTags"))
    for source, tag in badge_map.items():
        if truthy(normalized.get(source)) and tag not in tags:
            tags.append(tag)
    if tags:
        normalized["productTags"] = tags
    return normalized


def _market(input_data: dict[str, Any], *, default: str = "DE") -> str:
    return str(input_data.get("market") or input_data.get("site") or default).upper()


def _append_product_list_filters(payload: dict[str, Any], input_data: dict[str, Any]) -> None:
    for key in ["productTags", "sellerTypes", "eligibility"]:
        if input_data.get(key) is not None:
            payload[key] = csv(input_data.get(key))


def _append_product_range_filters(payload: dict[str, Any], input_data: dict[str, Any]) -> None:
    field_aliases = {
        "minPrice": ("minPrice", "priceMin"),
        "maxPrice": ("maxPrice", "priceMax"),
        "minSales": ("minSales", "salesMin"),
        "maxSales": ("maxSales", "salesMax"),
        "minAmount": ("minAmount",),
        "maxAmount": ("maxAmount",),
        "minAmzUnit": ("minAmzUnit",),
        "maxAmzUnit": ("maxAmzUnit",),
        "minTotalUnitsGrowth": ("minTotalUnitsGrowth",),
        "maxTotalUnitsGrowth": ("maxTotalUnitsGrowth",),
        "minRanking": ("minRanking",),
        "maxRanking": ("maxRanking",),
        "minSubBsrRank": ("minSubBsrRank",),
        "maxSubBsrRank": ("maxSubBsrRank",),
        "minRankingCv": ("minRankingCv",),
        "maxRankingCv": ("maxRankingCv",),
        "minRankingCr": ("minRankingCr",),
        "maxRankingCr": ("maxRankingCr",),
        "minVariations": ("minVariations",),
        "maxVariations": ("maxVariations",),
        "minQuestions": ("minQuestions",),
        "maxQuestions": ("maxQuestions",),
        "minReviewsGrouth": ("minReviewsGrouth",),
        "maxReviewsGrouth": ("maxReviewsGrouth",),
        "minReviewsRate": ("minReviewsRate",),
        "maxReviewsRate": ("maxReviewsRate",),
        "minProfit": ("minProfit",),
        "maxProfit": ("maxProfit",),
        "lqsFrom": ("lqsFrom",),
        "lqsTo": ("lqsTo",),
        "minReviews": ("minReviews", "reviewsMin"),
        "maxReviews": ("maxReviews", "reviewsMax"),
        "minReviewRating": ("minReviewRating", "ratingMin"),
        "maxReviewRating": ("maxReviewRating", "ratingMax"),
        "minFba": ("minFba",),
        "maxFba": ("maxFba",),
        "minWeights": ("minWeights",),
        "maxWeights": ("maxWeights",),
        "minDeliveryPrice": ("minDeliveryPrice",),
        "maxDeliveryPrice": ("maxDeliveryPrice",),
        "minSellers": ("minSellers",),
        "maxSellers": ("maxSellers",),
    }
    for target, aliases in field_aliases.items():
        for alias in aliases:
            if input_data.get(alias) is not None:
                payload[target] = str(input_data[alias])
                break


def _append_product_extra_filters(payload: dict[str, Any], input_data: dict[str, Any]) -> None:
    for key in [
        "putawayMonth",
        "smallAndLight",
        "lowPrice",
        "video",
        "matchType",
    ]:
        if input_data.get(key) is not None:
            payload[key] = input_data[key]


def _preset_key(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _flatten_query(payload: dict[str, Any]) -> dict[str, str]:
    query: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            query[key] = json_like_list(value)
        elif isinstance(value, dict):
            for child_key, child_value in value.items():
                query[f"{key}[{child_key}]"] = str(child_value)
        elif value is not None:
            query[key] = str(value)
    return query


def json_like_list(values: list[Any]) -> str:
    """生成与 Web query 接近的数组字符串。"""
    return "[" + ",".join(f'"{item}"' for item in values) + "]"
