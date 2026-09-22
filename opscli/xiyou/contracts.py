"""西柚 REST 与 MCP 共用的操作名称合同。"""

from typing import Literal


# 保留静态枚举，使 Swagger 和 MCP 工具列表暴露相同的场景集合。
XydcOperation = Literal[
    "asin_traffic",
    "asin_info_change_daily",
    "asin_traffic_score_daily",
    "asin_traffic_score_weekly",
    "asin_traffic_score_monthly",
    "asin_advertising_change_daily",
    "asin_bsr_daily",
    "asin_orders_trends",
    "asin_info_trends_daily",
    "asin_research_period",
    "asin_research_monthly",
    "asin_info",
    "asin_orders",
    "asin_variations",
    "asin_search_terms_traffic_daily",
    "asin_search_terms_rank_daily",
    "asin_search_terms_rank_hourly",
    "search_terms_aba_weekly",
    "search_terms_info",
    "search_terms_analysis_period",
    "search_terms_analysis_monthly",
    "client_quota",
]
