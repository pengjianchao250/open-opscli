"""卖家精灵场景 payload 构造。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


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
    for key in ["keyword", "brand", "sellerName"]:
        if input_data.get(key):
            payload[key] = input_data[key]
    return payload


def make_product_research_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """构造选竞品 payload。"""
    month = input_data.get("month") or input_data.get("period") or "2026-03"
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
        "productTags": csv(input_data.get("productTags")),
        "nodeIdPaths": csv(input_data.get("node") or input_data.get("nodeIdPaths")),
        "sellerTypes": csv(input_data.get("sellerTypes")),
        "eligibility": csv(input_data.get("eligibility")),
        "pkgDimensionTypeList": csv(input_data.get("pkgDimensionTypeList")),
        "sellerNationList": csv(input_data.get("sellerNationList")),
        "smallAndLight": input_data.get("smallAndLight") or "N",
        "lowPrice": input_data.get("lowPrice") or "N",
    }
    for key in ["keyword", "includeBrands", "excludeBrands", "includeSellers", "excludeSellers"]:
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
        "ac": truthy(input_data.get("ac") or input_data.get("amazonChoice")),
        "keywordBidMatchType": input_data.get("keywordBidMatchType") or "exact",
        "filterDeletedKeywords": truthy(input_data.get("filterDeletedKeywords")),
        "includeHighFrequency": truthy(input_data.get("includeHighFrequency"), default=True),
        "groupNum": _int(input_data.get("groupNum"), 1),
    }


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

    path = "product-research" if scenario == "product-research" else "competitor-lookup"
    query = _flatten_query(payload)
    return f"https://www.sellersprite.com/v3/{path}?{urlencode(query)}"


def month_name(value: Any) -> str:
    """转换竞品类接口月份字段。"""
    text = str(value)
    if text in {"nearly", "latest30", "last30"}:
        return "bsr_sales_nearly"
    if text.startswith("bsr_sales_"):
        return text
    return f"bsr_sales_monthly_{text.replace('-', '')}"


def history_date(value: Any) -> str:
    """转换关键词类接口月份字段。"""
    text = str(value or "")
    if not text or text in {"nearly", "latest30", "last30", "bsr_sales_nearly"}:
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


def csv(value: Any) -> list[str]:
    """逗号分隔参数转列表。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


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


def _market(input_data: dict[str, Any], *, default: str = "DE") -> str:
    return str(input_data.get("market") or input_data.get("site") or default).upper()


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
