"""卖家精灵场景 payload 构造。"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


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

MARKET_RESEARCH_HIDDEN_FIELDS = [
    "minAvgSales",
    "maxAvgSales",
    "minAvgBsr",
    "maxAvgBsr",
    "minAvgWeight",
    "maxAvgWeight",
    "minHeadListingAvgBsr",
    "maxHeadListingAvgBsr",
    "minTotalProducts",
    "maxTotalProducts",
    "minAvgRevenue",
    "maxAvgRevenue",
    "minAvgPrice",
    "maxAvgPrice",
    "minAvgVolume",
    "maxAvgVolume",
    "minHeadListingAvgSales",
    "maxHeadListingAvgSales",
    "minAvgReviews",
    "maxAvgReviews",
    "minAvgRating",
    "maxAvgRating",
    "minAvgProfit",
    "maxAvgProfit",
    "minHeadListingAvgRevenue",
    "maxHeadListingAvgRevenue",
    "minBrands",
    "maxBrands",
    "minHeadListingProductCrn",
    "maxHeadListingProductCrn",
    "minEbcRatio",
    "maxEbcRatio",
    "minAmzRatio",
    "maxAmzRatio",
    "minSellers",
    "maxSellers",
    "minHeadListingBrandCrn",
    "maxHeadListingBrandCrn",
    "minFbaRatio",
    "maxFbaRatio",
    "sellerNations",
    "minAvgSellers",
    "maxAvgSellers",
    "minHeadListingSellerCrn",
    "maxHeadListingSellerCrn",
    "minFbmRatio",
    "maxFbmRatio",
    "minNewRatio",
    "maxNewRatio",
    "minNewAvgPrice",
    "maxNewAvgPrice",
    "minNewAvgRevenue",
    "maxNewAvgRevenue",
    "minNewCount",
    "maxNewCount",
    "minNewAvgRating",
    "maxNewAvgRating",
    "minNewAvgReviews",
    "maxNewAvgReviews",
    "minNewAvgSales",
    "maxNewAvgSales",
]

# 关键词选品公共字段与页面表单字段的映射，取值来自 2026-07-23 官网页面实测。
KEYWORD_RESEARCH_FIELD_ALIASES: dict[str, str] = {
    "minSearchesCr": "minGrowth",
    "maxSearchesCr": "maxGrowth",
    "minSearchMonthCv": "minYearlyGrowth",
    "maxSearchMonthCv": "maxYearlyGrowth",
    "minSearchMonthCr": "minYearlyGrowthRate",
    "maxSearchMonthCr": "maxYearlyGrowthRate",
    "minSearchNearlyCv": "minGrowthTrendMin",
    "maxSearchNearlyCv": "maxGrowthTrendMin",
    "minSearchNearlyCr": "minGrowthRateTrendMin",
    "maxSearchNearlyCr": "maxGrowthRateTrendMin",
    "minRatings": "minAvgReviews",
    "maxRatings": "maxAvgReviews",
    "minRating": "minAvgRating",
    "maxRating": "maxAvgRating",
    "minAraClickRate": "minMonopolyClickRate",
    "maxAraClickRate": "maxMonopolyClickRate",
}

# 页面允许成对提交的范围字段后缀；构造器据此统一处理最小值、最大值和大小关系。
KEYWORD_RESEARCH_RANGE_FIELDS = (
    "Searches",
    "YearlyGrowth",
    "GrowthTrendMin",
    "Products",
    "Purchases",
    "Impressions",
    "SPR",
    "GoodsValue",
    "AvgPrice",
    "AvgReviews",
    "WordCount",
    "Growth",
    "YearlyGrowthRate",
    "GrowthRateTrendMin",
    "SupplyDemandRatio",
    "PurchaseRate",
    "Clicks",
    "TitleDensity",
    "MonopolyClickRate",
    "CvsShareRate",
    "Bid",
    "AvgRating",
)

# 官网仅接受整数的范围字段，避免把小数静默传给页面后再由页面丢弃。
KEYWORD_RESEARCH_INTEGER_RANGES = {
    "Searches",
    "YearlyGrowth",
    "GrowthTrendMin",
    "Products",
    "Purchases",
    "Impressions",
    "SPR",
    "AvgReviews",
    "WordCount",
    "Clicks",
    "TitleDensity",
}

# 市场周期枚举来自官网下拉框；空字符串表示“不限”。
KEYWORD_RESEARCH_MARKET_PERIODS = {
    "",
    "N",
    "S1,S2,S3",
    "S4,S5,S6",
    "S7,S8,S9",
    "S10,S11,S12",
    "I",
    "D",
}

# 关联类型枚举来自 2026-07-23 官网筛选项；顺序与页面保持一致，便于导出和 Skill 对照。
ASSOCIATION_TRAFFIC_RELATION_TYPES = (
    "VAV",
    "CSI",
    "AVP",
    "BAV",
    "MIB",
    "FBT",
    "MIE",
    "BAB",
    "COB",
    "SP",
    "FSA",
    "BCA",
)

# 关联流量页面使用产品研究体系的 market id，而不是旧版关键词接口的连续编号。
ASSOCIATION_TRAFFIC_MARKET_IDS = {
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


def make_competitor_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造竞品查询 payload。"""
    market = _market(input_data)
    month = input_data.get("month") or input_data.get("period") or "202604"
    asin_values = input_data.get("asins") or input_data.get("asin")
    payload: dict[str, Any] = {
        "market": market,
        "monthName": input_data.get("monthName") or month_name(month),
        "asins": csv(asin_values),
        "page": _int(input_data.get("page") or input_data.get("startPage"), 1),
        "nodeIdPaths": csv(input_data.get("node") or input_data.get("nodeIdPaths") or input_data.get("nodeIdPath")),
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
            "field": input_data.get("orderField") or "total_units",
            "desc": order_desc(input_data.get("orderDesc")),
        },
        "productTags": [],
        "nodeIdPaths": csv(
            input_data.get("node")
            or input_data.get("category")
            or input_data.get("nodeIdPaths")
            or input_data.get("nodeIdPath")
        ),
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


def make_keyword_research_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造关键词选品页面 GET 查询参数。

    参数：
        input_data: 公共场景参数，兼容已记录的页面字段别名。

    返回：
        可直接用于官网关键词选品页面 GET 请求的查询参数。

    异常：
        SellerSpriteConfigError: 范围、分页或市场周期参数不符合页面约束时抛出。
    """
    # 先归一化公共字段，确保校验和最终页面参数只处理一套名称。
    normalized = dict(input_data)
    for source, target in KEYWORD_RESEARCH_FIELD_ALIASES.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    _validate_keyword_research_ranges(normalized)

    page = _positive_int(normalized.get("page") or normalized.get("startPage"), default=1, field="page")
    requested_size = _positive_int(
        normalized.get("size") or normalized.get("pageSize"),
        default=100,
        field="size",
    )
    # 关键词选品与其他普通场景统一默认每页 100 条，Manager 只执行当前页一次查询。
    size = requested_size
    site = _market(normalized, default="US")
    month = history_date(normalized.get("month") or normalized.get("period"))
    market_period = str(normalized.get("marketPeriod") or "").strip()
    if market_period not in KEYWORD_RESEARCH_MARKET_PERIODS:
        raise SellerSpriteConfigError(f"keyword-research marketPeriod 不支持：{market_period}")
    order_desc_value = normalized["orderDesc"] if "orderDesc" in normalized else normalized.get("order.desc")

    payload: dict[str, Any] = {
        "station": site,
        "order.field": str(normalized.get("orderField") or normalized.get("order.field") or "searches"),
        "order.desc": str(order_desc(order_desc_value)).lower(),
        "supplement": str(normalized.get("supplement") or "N"),
        "usestatic": str(normalized.get("usestatic") or "R"),
        "exportGkImages": str(truthy(normalized.get("exportGkImages"))).lower(),
        "marketId": str(normalized.get("marketId") or market_id(site)),
        "limitUserStatic": str(truthy(normalized.get("limitUserStatic"), default=True)).lower(),
        "adminDes": str(normalized.get("adminDes") or "S"),
        "presetMode": str(normalized.get("presetMode") or ""),
        "itemImageRange": str(normalized.get("itemImageRange") or 2),
        "keywordBidMatchType": str(normalized.get("keywordBidMatchType") or "exact"),
        "marketPeriod": market_period,
        "page": str(page),
        "size": str(size),
    }
    if month:
        payload["month"] = month
    departments = csv(normalized.get("departments") or normalized.get("department"))
    for index, department in enumerate(departments):
        payload[f"departments[{index}]"] = department

    keyword = normalized.get("keywords") or normalized.get("includeKeywords") or normalized.get("keyword")
    if keyword:
        payload["includeKeywords"] = _query_text(keyword)
    if normalized.get("excludeKeywords"):
        payload["excludeKeywords"] = _query_text(normalized.get("excludeKeywords"))
    if normalized.get("withYearlyGrowth") is not None:
        payload["withYearlyGrowth"] = str(truthy(normalized.get("withYearlyGrowth"))).lower()
    for suffix in KEYWORD_RESEARCH_RANGE_FIELDS:
        for prefix in ("min", "max"):
            field = f"{prefix}{suffix}"
            if normalized.get(field) is not None and str(normalized[field]).strip() != "":
                payload[field] = _number_text(normalized[field])
    return payload


def make_association_traffic_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造关联流量全部变体查询 payload。

    参数：
        input_data: 公共场景参数，``asins`` 支持列表、逗号或换行分隔文本。

    返回：
        可提交至官网关联流量查询接口的 JSON payload。

    异常：
        SellerSpriteConfigError: ASIN、站点、关联类型或分页参数不符合页面约束时抛出。
    """
    asins = _association_traffic_asins(input_data.get("asins") or input_data.get("asin"))
    relations = [value.upper() for value in csv(input_data.get("relations"))]
    invalid_relations = [value for value in relations if value not in ASSOCIATION_TRAFFIC_RELATION_TYPES]
    if invalid_relations:
        raise SellerSpriteConfigError(
            f"association-traffic 不支持关联类型：{', '.join(invalid_relations)}"
        )
    site = _market(input_data, default="US")
    market = input_data.get("marketId") or ASSOCIATION_TRAFFIC_MARKET_IDS.get(site)
    if market is None:
        raise SellerSpriteConfigError(f"association-traffic 暂不支持站点：{site}")
    requested_size = _positive_int(
        input_data.get("pageSize") or input_data.get("size"),
        default=100,
        field="pageSize",
    )
    # 关联流量与其他普通场景统一每页 100 条；全部变体是本场景固定业务语义。
    return {
        "market": _int(market, 1),
        # 业务任务始终从第一页开始，Manager 只解析该页后完成任务。
        "pageNum": 1,
        "pageSize": requested_size,
        "desc": order_desc(input_data.get("desc")),
        "orderField": str(input_data.get("orderField") or "createdTime"),
        "relations": relations,
        "queryVariations": True,
        "asinList": asins,
    }


def make_aba_reverse_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造出单词反查官方 Excel 导出参数。"""
    asins = _aba_reverse_asins(
        input_data.get("asins")
        or input_data.get("asin")
        or input_data.get("textareaValue")
        or input_data.get("keywordOrAsin")
        or input_data.get("q")
    )
    reverse_type = _aba_reverse_type(input_data)
    if reverse_type == "W":
        period = input_data.get("table") or input_data.get("period") or input_data.get("month")
        if _is_default_aba_period(period):
            period = _latest_completed_aba_week()
        table = _aba_week_table(period)
        monthly_table = _aba_month_table(
            input_data.get("monthlyTable") or _previous_complete_month(table)
        )
    else:
        period = input_data.get("monthlyTable") or input_data.get("period") or input_data.get("month")
        monthly_table = _aba_month_table(period)
        table = monthly_table
    order_desc_value = (
        input_data["orderDesc"]
        if "orderDesc" in input_data
        else input_data.get("order.desc", False)
    )
    textarea_value = ",".join(asins)
    return {
        "station": _market(input_data, default="US"),
        "table": table,
        "asin": asins[0],
        "order.field": str(
            input_data.get("orderField")
            or input_data.get("order.field")
            or "searchRank"
        ),
        "order.desc": str(order_desc(order_desc_value)).lower(),
        "conversionType": str(input_data.get("conversionType") or ""),
        "loadVariations": str(
            truthy(input_data.get("loadVariations"), default=False)
        ).lower(),
        "reverseType": reverse_type,
        "monthlyTable": monthly_table,
        "textareaValue": textarea_value,
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
    topn = input_data.get("topn") or input_data.get("topN") or 10
    new_release = new_release_num(input_data)
    payload: dict[str, Any] = {
        "marketId": str(input_data.get("marketId") or market_research_market_id(_market(input_data, default="US"))),
        "nodeIdPath": _query_text(input_data.get("nodeIdPath") or input_data.get("node")),
        "sampleNumber": str(input_data.get("sampleNumber") or 1),
        "topn": str(topn),
        "newReleaseNum": str(new_release),
        "order.field": input_data.get("orderField") or input_data.get("order.field") or "total_sales",
        "order.desc": str(order_desc(input_data.get("orderDesc") or input_data.get("order.desc"))).lower(),
        "tab": str(input_data.get("tab") or 1),
        "monthName": input_data.get("monthName") or month_name(month),
        "newReleaseNumSelect": str(input_data.get("newReleaseNumSelect") or new_release),
        "topNSelect": str(input_data.get("topNSelect") or topn),
        "page": str(_int(input_data.get("page") or input_data.get("startPage"), 1)),
        "size": str(_int(input_data.get("size") or input_data.get("pageSize"), 100)),
    }
    if input_data.get("departmentKeyword") or input_data.get("keyword") or input_data.get("category"):
        payload["departmentKeyword"] = _query_text(
            input_data.get("departmentKeyword") or input_data.get("keyword") or input_data.get("category")
        )
    for field in MARKET_RESEARCH_HIDDEN_FIELDS:
        payload[field] = "" if input_data.get(field) is None else str(input_data[field])
    return payload


def make_listing_analysis_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "asin": str(input_data.get("asin") or input_data.get("q") or "").strip().upper(),
        "station": str(input_data.get("station") or "GLOBAL").strip().upper(),
    }


def build_referer(payload: dict[str, Any], scenario: str) -> str:
    """按场景构造 Web referer。"""
    if scenario == "listing-analysis":
        return "https://www.sellersprite.com/v3/ai-history?module=LA"
    if scenario == "keyword-miner":
        return "https://www.sellersprite.com/v3/keyword-miner/"
    if scenario == "keyword-research":
        return f"https://www.sellersprite.com/v2/keyword-research?{urlencode(_flatten_query(payload))}"
    if scenario == "aba-reverse":
        query = dict(payload)
        query["asin"] = ""
        return f"https://www.sellersprite.com/v2/aba/reverse/search?{urlencode(_flatten_query(query))}"
    if scenario == "association-traffic":
        return f"https://www.sellersprite.com/v3/relation-keyword?{urlencode(_flatten_query(payload))}"
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


def _association_traffic_asins(value: Any) -> list[str]:
    """归一化页面支持的 ASIN 列表、TXT 和 Excel 按列粘贴文本。"""
    asins = split_association_traffic_asins(value)
    if not asins:
        raise SellerSpriteConfigError("association-traffic 至少需要 1 个 ASIN")
    if len(asins) > 20:
        raise SellerSpriteConfigError("association-traffic 最多支持 20 个 ASIN")
    invalid_asins = [asin for asin in asins if not re.fullmatch(r"[A-Z0-9]{10}", asin)]
    if invalid_asins:
        raise SellerSpriteConfigError(
            f"association-traffic ASIN 格式无效：{', '.join(invalid_asins)}"
        )
    return asins


def split_association_traffic_asins(value: Any) -> list[str]:
    """拆分并去重关联流量页面支持的 ASIN 文本。

    参数：
        value: ASIN 列表，或来自 TXT、Excel 单列和分隔文本的原始值。

    返回：
        已去空白、转大写并保持首次出现顺序的 ASIN 列表；本函数不做数量和格式校验。
    """
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    asins: list[str] = []
    for raw_value in raw_values:
        # 页面允许逗号、空白、换行和 Excel 制表符输入，MCP 统一在请求前拆分并去重。
        for part in re.split(r"[\s,，;；]+", str(raw_value or "")):
            asin = part.strip().upper()
            if asin and asin not in asins:
                asins.append(asin)
    return asins


def _aba_reverse_asins(value: Any) -> list[str]:
    """从 ASIN 或 Amazon 产品链接中提取并去重 ASIN。"""
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    asins: list[str] = []
    invalid_values: list[str] = []
    for raw_value in raw_values:
        for part in re.split(r"[\s,，;；]+", str(raw_value or "")):
            text = part.strip()
            if not text:
                continue
            asin = _asin_from_product_input(text)
            if not asin:
                invalid_values.append(text)
                continue
            if asin not in asins:
                asins.append(asin)
    if invalid_values:
        raise SellerSpriteConfigError(
            f"aba-reverse ASIN 或产品链接格式无效：{', '.join(invalid_values)}"
        )
    if not asins:
        raise SellerSpriteConfigError("aba-reverse 至少需要 1 个 ASIN 或 Amazon 产品链接")
    if len(asins) > 20:
        raise SellerSpriteConfigError("aba-reverse 最多支持 20 个 ASIN")
    return asins


def _asin_from_product_input(value: str) -> str:
    text = value.strip()
    upper = text.upper()
    if re.fullmatch(r"[A-Z0-9]{10}", upper):
        return upper
    candidate = text if "://" in text else f"https://{text}"
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower()
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)*amazon\.[a-z.]+", hostname):
        return ""
    match = re.search(r"/(?:dp|gp/product|product)/([A-Z0-9]{10})(?:[/?]|$)", parsed.path, re.I)
    return match.group(1).upper() if match else ""


def _aba_reverse_type(input_data: dict[str, Any]) -> str:
    value = str(
        input_data.get("reverseType")
        or input_data.get("periodType")
        or input_data.get("cycle")
        or ""
    ).strip().lower()
    aliases = {
        "w": "W",
        "week": "W",
        "weekly": "W",
        "每周": "W",
        "m": "M",
        "month": "M",
        "monthly": "M",
        "每月": "M",
    }
    if value:
        reverse_type = aliases.get(value)
        if not reverse_type:
            raise SellerSpriteConfigError(f"aba-reverse 不支持周期类型：{value}")
        return reverse_type
    period = str(input_data.get("period") or input_data.get("month") or "").strip()
    return "M" if re.fullmatch(r"(?:ara_)?\d{4}-?\d{2}", period) else "W"


def _is_default_aba_period(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "",
        "30d",
        "nearly",
        "latest30",
        "last30",
    }


def _latest_completed_aba_week(today: date | None = None) -> str:
    """返回最近一个完整 ABA 周的周六日期。"""
    current_date = today or date.today()
    days_since_saturday = (current_date.weekday() - 5) % 7
    if days_since_saturday == 0:
        days_since_saturday = 7
    return (current_date - timedelta(days=days_since_saturday)).strftime("%Y%m%d")


def _aba_week_table(value: Any) -> str:
    text = str(value or "").strip()
    normalized = text.removeprefix("ara_").replace("-", "")
    if re.fullmatch(r"\d{8}", normalized):
        return f"ara_{normalized}"
    label = re.fullmatch(r"(\d{4})第\d+周\([^~]*~(\d{2})/(\d{2})\)", text)
    if label:
        return f"ara_{label.group(1)}{label.group(2)}{label.group(3)}"
    raise SellerSpriteConfigError(
        "aba-reverse 每周周期必须为 YYYY-MM-DD、YYYYMMDD、ara_YYYYMMDD 或官网周标签"
    )


def _aba_month_table(value: Any) -> str:
    text = str(value or "").strip()
    normalized = text.removeprefix("ara_").replace("-", "")
    if re.fullmatch(r"\d{6}", normalized):
        return f"ara_{normalized}"
    raise SellerSpriteConfigError(
        "aba-reverse 每月周期必须为 YYYY-MM、YYYYMM 或 ara_YYYYMM"
    )


def _previous_complete_month(week_table: str) -> str:
    week_end = datetime.strptime(week_table.removeprefix("ara_"), "%Y%m%d")
    previous_month = week_end.replace(day=1) - timedelta(days=1)
    return previous_month.strftime("%Y%m")


def _query_text(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _validate_keyword_research_ranges(input_data: dict[str, Any]) -> None:
    # 通用范围先检查数值类型和左右边界，再补充页面对词数、评分值的特殊限制。
    for suffix in KEYWORD_RESEARCH_RANGE_FIELDS:
        minimum = _keyword_research_number(input_data.get(f"min{suffix}"), suffix=suffix, side="min")
        maximum = _keyword_research_number(input_data.get(f"max{suffix}"), suffix=suffix, side="max")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise SellerSpriteConfigError(
                f"keyword-research min{suffix} 不能大于 max{suffix}"
            )
    _validate_bounded_number(input_data.get("minWordCount"), "minWordCount", 1, 5, integer=True)
    _validate_bounded_number(input_data.get("maxWordCount"), "maxWordCount", 1, 9, integer=True)
    _validate_bounded_number(input_data.get("minAvgRating"), "minRating", 0, 5)
    _validate_bounded_number(input_data.get("maxAvgRating"), "maxRating", 0, 5)


def _keyword_research_number(value: Any, *, suffix: str, side: str) -> float | int | None:
    if value is None or str(value).strip() == "":
        return None
    field = f"{side}{suffix}"
    if isinstance(value, bool):
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是数值") from exc
    if not math.isfinite(number):
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是有限数值")
    if suffix in KEYWORD_RESEARCH_INTEGER_RANGES and not number.is_integer():
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是整数")
    return int(number) if number.is_integer() else number


def _validate_bounded_number(
    value: Any,
    field: str,
    minimum: float,
    maximum: float,
    *,
    integer: bool = False,
) -> None:
    if value is None or str(value).strip() == "":
        return
    if isinstance(value, bool):
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是数值") from exc
    if not math.isfinite(number):
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是有限数值")
    if integer and not number.is_integer():
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是整数")
    if number < minimum or number > maximum:
        raise SellerSpriteConfigError(
            f"keyword-research {field} 必须在 {minimum:g}—{maximum:g} 之间"
        )


def _positive_int(value: Any, *, default: int, field: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    if isinstance(value, bool):
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是正整数") from exc
    if str(value).strip() not in {str(parsed), f"{parsed}.0"} or parsed <= 0:
        raise SellerSpriteConfigError(f"keyword-research {field} 必须是正整数")
    return parsed


def _number_text(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


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
            if key == "putawayMonth":
                payload[key] = _validate_putaway_month(input_data[key])
            else:
                payload[key] = input_data[key]


def _validate_putaway_month(value: Any) -> Any:
    """校验选产品上架月数，避免误把数据月份传给 putawayMonth。"""
    text = str(value).strip()
    if _looks_like_data_month(text):
        raise SellerSpriteConfigError(
            "product-research 的 putawayMonth/availableMonth 表示上架月数，不是数据月份；"
            "数据月份请传顶层 period，例如 period=2026-04。"
        )
    return value


def _looks_like_data_month(value: str) -> bool:
    if value.startswith("bsr_sales_"):
        return True
    normalized = value.replace("-", "").replace("/", "").replace(".", "")
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    year = _int(normalized[:4], 0)
    month = _int(normalized[4:], 0)
    return 1900 <= year <= 2100 and 1 <= month <= 12


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
