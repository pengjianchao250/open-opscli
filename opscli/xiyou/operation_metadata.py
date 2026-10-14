"""西柚公开文档的参数说明快照，供 MCP/REST 目录构造请求。

2026-10-10 核对 llms.txt 中全部现行接口；只整理请求合同，不推断数据可用日期。
schema 用于目录说明，不代替供应商校验；文档冲突和未确认约定记录在 constraints。
"""

from copy import deepcopy
from typing import Any


# 页面 ID 是官方接口文档的稳定引用，不采用已归档鉴权或已下线市场洞察接口。
DOCUMENT_PAGES = {
    "asin_traffic": "312439564e0",
    "asin_info_change_daily": "325279983e0",
    "asin_traffic_score_daily": "326002208e0",
    "asin_traffic_score_weekly": "326241285e0",
    "asin_traffic_score_monthly": "326253357e0",
    "asin_advertising_change_daily": "326115660e0",
    "asin_bsr_daily": "327781736e0",
    "asin_orders_trends": "328160994e0",
    "asin_info_trends_daily": "331311535e0",
    "asin_research_period": "331502595e0",
    "asin_research_monthly": "331594504e0",
    "asin_info": "335282030e0",
    "asin_orders": "339953324e0",
    "asin_variations": "370838212e0",
    "asin_search_terms_traffic_daily": "327911125e0",
    "asin_search_terms_rank_daily": "329420765e0",
    "asin_search_terms_rank_hourly": "332071833e0",
    "search_terms_aba_weekly": "333362889e0",
    "search_terms_info": "333379279e0",
    "search_terms_analysis_period": "451262166e0",
    "search_terms_analysis_monthly": "451506681e0",
    "client_quota": "457513504e0",
}
COUNTRIES = ["US", "CA", "MX", "BR", "UK", "DE", "ES", "IT", "FR", "JP", "AU", "SA", "AE"]
TRAFFIC_SORT_FIELDS = [
    "traffic", "organicTraffic", "advertisingTraffic", "trafficAcquisitionRate",
    "organicTrafficAcquisitionRate", "advertisingTrafficAcquisitionRate", "orRank", "spRank",
]
KEYWORD_SORT_FIELDS = [
    "clickConversionRate", "searchTermCompetitiveDifficulty", "organicRotation",
    "searchFrequencyRank", "weeklySearchVolume",
]
DATE_SCHEMA = {"type": "string", "format": "date", "description": "YYYY-MM-DD；共享 Date.pattern 与官方纯日期示例冲突，按纯日期构造"}
MONTH_SCHEMA = {"type": "string", "pattern": r"^(19|20)\d{2}-(0[1-9]|1[0-2])$", "description": "YYYY-MM"}
WEEK_SCHEMA = {
    "type": "object", "properties": {"startDate": DATE_SCHEMA, "endDate": DATE_SCHEMA},
    "required": ["startDate", "endDate"], "description": "完整7天对象；不同接口的周边界见 constraints",
}
PARAMETER_SCHEMAS = {
    "asin": {"type": "string", "description": "单个 ASIN"},
    "country": {"type": "string", "enum": COUNTRIES},
    "entities": {
        "type": "array", "maxItems": 100,
        "items": {"type": "object", "required": ["asin", "country"],
                  "properties": {"asin": {"type": "string"}, "country": {"type": "string", "enum": COUNTRIES}}},
        "description": "ASIN/站点对象数组，最多100个；可在不同对象中传不同站点",
    },
    "asins": {"type": "array", "maxItems": 100, "items": {"type": "string"}},
    "searchTerm": {"type": "string", "description": "单个关键词"},
    "searchTerms": {"type": "array", "maxItems": 100, "items": {"type": "string"}},
    "startDate": DATE_SCHEMA, "endDate": DATE_SCHEMA, "date": DATE_SCHEMA,
    "startMonth": MONTH_SCHEMA, "endMonth": MONTH_SCHEMA,
    "startWeek": WEEK_SCHEMA, "endWeek": WEEK_SCHEMA,
    "page": {"type": "integer", "description": "供应商页码原样透传；反查例子为1，关键词分析起点未明示，不自动转换页码"},
    "pageSize": {"type": "integer", "description": "每页条数；列表接口单次最多10000条，建议先取20条"},
    "period": {"type": "string", "enum": ["last7days"], "description": "仅最近7天，不传任意天数或起止日期"},
    "sort": {
        "type": "object", "required": ["field", "order"],
        "properties": {"field": {"type": "string", "enum": TRAFFIC_SORT_FIELDS},
                       "order": {"type": "string", "enum": ["asc", "desc"]}},
    },
}
# 示例为构造参数的历史样本，不是默认日期，也不保证对应对象存在数据。
EXAMPLE_VALUES = {
    "asin": "B09XS7JWHH", "country": "US",
    "entities": [{"asin": "B09XS7JWHH", "country": "US"}], "asins": ["B09XS7JWHH"],
    "searchTerm": "usb c cable", "searchTerms": ["usb c cable"],
    "startDate": "2025-06-01", "endDate": "2025-06-06", "date": "2025-06-06",
    "startMonth": "2025-05", "endMonth": "2025-06",
    "startWeek": {"startDate": "2025-05-26", "endDate": "2025-06-01"},
    "endWeek": {"startDate": "2025-06-30", "endDate": "2025-07-06"},
    "page": 1, "pageSize": 20, "period": "last7days", "sort": {"field": "traffic", "order": "desc"},
}


def get_operation_metadata(operation: str, required_fields: tuple[str, ...]) -> dict[str, Any]:
    """返回独立目录副本，避免调用方修改共享参数枚举或示例。"""
    fields = list(required_fields)
    if operation in {"asin_research_period", "asin_research_monthly"}:
        fields.append("sort")
    properties = {name: deepcopy(PARAMETER_SCHEMAS[name]) for name in fields}
    example = {name: deepcopy(EXAMPLE_VALUES[name]) for name in fields}
    notes = ["payload_schema 是请求构造指引；本地仅校验必填字段，供应商仍校验字段类型、范围与数据可用性。"]
    if "pageSize" in properties:
        properties["pageSize"]["maximum"] = 10000
        notes.append("单次最多10000条；按返回条数计费，先用较小 pageSize，再按任务需要翻页。关键词分析分页起点文档未明示。")
    if operation.startswith("search_terms_analysis_"):
        properties["sort"]["properties"]["field"]["enum"].append("trafficRatio")
    if operation == "search_terms_info":
        properties["sort"]["properties"]["field"]["enum"] = list(KEYWORD_SORT_FIELDS)
        example["sort"]["field"] = "weeklySearchVolume"
    if operation in {"asin_research_period", "asin_research_monthly"}:
        notes.append("sort 可选，供应商默认按流量降序；page/pageSize 必填。")
    if operation == "asin_research_monthly":
        notes.append("查询周期最长一年；此限制仅适用于本接口，不推广到其他月趋势。")
    if operation == "asin_bsr_daily":
        properties["country"]["enum"] = [country for country in COUNTRIES if country not in {"AU", "SA", "AE"}]
        notes.append("Keepa 数据，暂不支持 AU、SA、AE。")
    if operation == "asin_search_terms_rank_hourly":
        properties["country"]["enum"] = ["US", "UK", "DE"]
        notes.append("仅 US、UK、DE，一次一天，固定3 Credit；属性说明比通用国家枚举更具体。")
    if operation == "asin_info_trends_daily":
        notes.append("coupon/promotion/subscription/other 仅支持 US、UK、CA、AE、AU；请求体为单个 asin，勿因描述中的100个ASIN自行改为数组。")
    if operation == "search_terms_aba_weekly":
        example["startWeek"] = {"startDate": "2025-07-06", "endDate": "2025-07-12"}
        example["endWeek"] = {"startDate": "2025-07-13", "endDate": "2025-07-19"}
        notes.append("最多100词、最长52周；示例为周日至周六，描述中的周日到周一有冲突，按完整7天例子构造。")
    if operation == "asin_traffic_score_weekly":
        notes.append("官方请求示例为周一至周日的7天对象；返回 week/dateRange 有混用，保留实际响应字段。")
    if operation in {"asin_traffic", "asin_traffic_score_daily"}:
        notes.append("流量不含最新一天；客户端昨日不保证数据可用，截止时区/发布时间未确认。")
    if operation == "client_quota":
        notes.append("仅适用于 v1；不作为 v2 公共额度查询入口。")
    return {
        "documentation_url": f"https://openapi-doc.xiyouzhaoci.com/{DOCUMENT_PAGES[operation]}.md",
        "payload_schema": {"type": "object", "properties": properties, "required": list(required_fields)},
        "example_payload": example,
        "constraints": notes,
    }
