"""Amazon Listing Intelligence 编排服务。"""

from __future__ import annotations

from typing import Any

from opscli.amazon_listing_intelligence.domain.models import (
    DataSourcePlan,
    ListingIntelligenceRequest,
)


OBJECTIVE_SOURCE_MAP: dict[str, list[str]] = {
    "listing_audit": [
        "amazon_listing",
        "seller_sprite",
        "amazon_review",
        "amazon_qa",
    ],
    "keyword_opportunity": [
        "seller_sprite",
        "amazon_search",
        "google_trends",
    ],
    "buyer_insight": [
        "amazon_review",
        "amazon_qa",
        "reddit",
    ],
    "competitor_positioning": [
        "seller_sprite",
        "amazon_search",
        "amazon_listing",
    ],
    "category_intelligence": [
        "seller_sprite",
        "google_trends",
        "keepa",
        "dataforseo",
    ],
}


class AmazonListingIntelligenceManager:
    """提供 Listing 优化服务的数据源目录和接入计划。"""

    def data_sources(self, *, phase: str | None = None) -> list[dict[str, Any]]:
        """列出数据源接入计划。"""
        items = _DATA_SOURCES
        if phase:
            normalized = phase.strip().lower()
            items = [item for item in items if item.phase == normalized]
        return [item.to_dict() for item in items]

    def objectives(self) -> dict[str, Any]:
        """列出支持的分析目标。"""
        return {
            "default": "listing_audit",
            "items": [
                {
                    "objective": objective,
                    "required_sources": sources,
                }
                for objective, sources in OBJECTIVE_SOURCE_MAP.items()
            ],
        }

    def intake_plan(self, request: ListingIntelligenceRequest) -> dict[str, Any]:
        """根据输入生成数据源接入计划。"""
        objective = (request.objective or "listing_audit").strip().lower()
        source_ids = OBJECTIVE_SOURCE_MAP.get(objective)
        if source_ids is None:
            source_ids = OBJECTIVE_SOURCE_MAP["listing_audit"]
            objective = "listing_audit"

        available = {item.strip().lower() for item in request.available_sources if item.strip()}
        selected = [_SOURCE_BY_ID[source_id] for source_id in source_ids]
        missing_inputs = self._missing_inputs(request, objective)
        missing_sources = [
            item.source_id
            for item in selected
            if item.source_id not in available and item.existing_entry is None
        ]

        return {
            "request": request.to_dict(),
            "normalized_objective": objective,
            "required_sources": [item.to_dict() for item in selected],
            "missing_inputs": missing_inputs,
            "missing_sources": missing_sources,
            "next_actions": self._next_actions(request, selected, missing_inputs),
            "boundaries": [
                "当前服务只生成数据源接入计划，不直接抓取外部页面。",
                "真实取数优先复用 seller_sprite_* MCP tools。",
                "没有证据数据时，不输出确定性 Listing 结论。",
            ],
        }

    def schema(self) -> dict[str, Any]:
        """输出 MCP 参数和返回结构说明。"""
        return {
            "request": {
                "asin": "Amazon ASIN，Listing Audit / 竞品分析建议提供",
                "keyword": "显式关键词，关键词机会和 SellerSprite 采集建议提供",
                "marketplace": "站点代码，默认 US",
                "objective": list(OBJECTIVE_SOURCE_MAP.keys()),
                "available_sources": "已具备的数据源 ID 列表",
            },
            "source_ids": [item.source_id for item in _DATA_SOURCES],
        }

    def _missing_inputs(
        self,
        request: ListingIntelligenceRequest,
        objective: str,
    ) -> list[str]:
        missing: list[str] = []
        if objective in {"listing_audit", "competitor_positioning"} and not request.asin:
            missing.append("asin")
        if objective in {"listing_audit", "keyword_opportunity", "competitor_positioning"} and not request.keyword:
            missing.append("keyword")
        return missing

    def _next_actions(
        self,
        request: ListingIntelligenceRequest,
        selected: list[DataSourcePlan],
        missing_inputs: list[str],
    ) -> list[str]:
        if missing_inputs:
            return [f"补充缺失输入：{', '.join(missing_inputs)}"]

        actions: list[str] = []
        source_ids = {item.source_id for item in selected}
        marketplace = (request.marketplace or "US").upper()
        if "seller_sprite" in source_ids and request.keyword:
            actions.append(
                "调用 seller_sprite_run，优先跑 keyword-miner；如有 ASIN，再跑 keyword-reverse。"
            )
        if "amazon_listing" in source_ids and request.asin:
            actions.append("读取 Amazon Listing 标题、Bullet、A+、图片、价格、评分。")
        if "amazon_search" in source_ids and request.keyword:
            actions.append(f"按 {marketplace} 站关键词搜索，生成竞品 ASIN 池。")
        if "google_trends" in source_ids and request.keyword:
            actions.append("获取关键词趋势，结论必须带时间范围和地区。")
        if "reddit" in source_ids and request.keyword:
            actions.append("搜索 Reddit 用户讨论，区分用户原话和 AI 总结。")
        return actions


_DATA_SOURCES: list[DataSourcePlan] = [
    DataSourcePlan(
        source_id="seller_sprite",
        name="SellerSprite",
        phase="mvp",
        priority="S",
        access_mode="mcp",
        account_required=True,
        paid_required=True,
        value="关键词、竞品、流量来源和市场研究主数据源。",
        fields=["keyword", "searches", "purchases", "ppc", "competitor_asins", "traffic_source"],
        use_cases=["keyword_opportunity", "competitor_positioning", "category_intelligence"],
        onboarding=["确认 OPS 后端集成账号", "确认 seller_sprite_* MCP tools 可用"],
        todo=["映射 keyword-miner", "映射 keyword-reverse", "映射 traffic-source"],
        existing_entry="seller_sprite_* MCP tools",
    ),
    DataSourcePlan(
        source_id="amazon_listing",
        name="Amazon Listing",
        phase="mvp",
        priority="S",
        access_mode="public_scrape",
        account_required=False,
        paid_required=False,
        value="Listing Audit 主体数据。",
        fields=["title", "bullets", "description", "a_plus", "images", "price", "rating"],
        use_cases=["listing_audit", "competitor_positioning"],
        todo=["复用或恢复 amazon_* MCP tools", "标准化 Listing 字段"],
    ),
    DataSourcePlan(
        source_id="amazon_search",
        name="Amazon Search",
        phase="mvp",
        priority="S",
        access_mode="public_scrape",
        account_required=False,
        paid_required=False,
        value="关键词排名、广告位和竞品池。",
        fields=["keyword", "rank", "asin", "price", "rating", "sponsored"],
        use_cases=["keyword_opportunity", "competitor_positioning"],
        todo=["只抓前 1-2 页", "和 SellerSprite 关键词结果交叉验证"],
    ),
    DataSourcePlan(
        source_id="amazon_review",
        name="Amazon Review",
        phase="mvp",
        priority="A",
        access_mode="public_scrape",
        account_required=False,
        paid_required=False,
        value="用户痛点、购买动机和差评聚类。",
        fields=["star", "title", "body", "date", "country", "verified"],
        use_cases=["listing_audit", "buyer_insight"],
        todo=["一期只取前几页", "建立评论聚类输入格式"],
    ),
    DataSourcePlan(
        source_id="amazon_qa",
        name="Amazon Q&A",
        phase="mvp",
        priority="A",
        access_mode="public_scrape",
        account_required=False,
        paid_required=False,
        value="购买前顾虑和 FAQ 缺口。",
        fields=["question", "answer", "answered_by", "date"],
        use_cases=["listing_audit", "buyer_insight"],
        todo=["和 Listing 页面采集一起标准化"],
    ),
    DataSourcePlan(
        source_id="google_trends",
        name="Google Trends",
        phase="mvp",
        priority="S",
        access_mode="api_or_library",
        account_required=False,
        paid_required=False,
        value="关键词趋势、季节性和地区热度。",
        fields=["keyword", "time_range", "region", "interest_over_time"],
        use_cases=["keyword_opportunity", "category_intelligence"],
        todo=["确认 pytrends 或后端接口方案", "输出必须保留时间范围"],
    ),
    DataSourcePlan(
        source_id="reddit",
        name="Reddit",
        phase="mvp",
        priority="A",
        access_mode="api_or_public",
        account_required=True,
        paid_required=False,
        value="真实需求、吐槽和用户语言库。",
        fields=["subreddit", "title", "body", "score", "comments", "created_at"],
        use_cases=["buyer_insight"],
        onboarding=["创建 Reddit developer app", "获取 client_id/client_secret/user_agent"],
        todo=["建立 subreddit 搜索策略", "区分用户原话和 AI 总结"],
    ),
    DataSourcePlan(
        source_id="amazon_pa_api",
        name="Amazon PA API",
        phase="enhanced",
        priority="A",
        access_mode="official_api",
        account_required=True,
        paid_required=False,
        value="官方商品基础信息、图片、品牌和价格校验。",
        fields=["asin", "title", "brand", "images", "price", "offers"],
        use_cases=["listing_audit", "competitor_positioning"],
        onboarding=["申请 Amazon Associate 账号", "满足 PA API 使用门槛", "配置 access key"],
        todo=["确认额度和站点覆盖", "作为官方字段校验源"],
    ),
    DataSourcePlan(
        source_id="tiktok_creative_center",
        name="TikTok Creative Center",
        phase="enhanced",
        priority="A",
        access_mode="account_or_public",
        account_required=True,
        paid_required=False,
        value="热门广告、素材、达人和趋势信号。",
        fields=["keyword", "ad", "creative", "creator", "trend"],
        use_cases=["buyer_insight", "category_intelligence"],
        onboarding=["准备 TikTok 账号", "必要时申请 Business/Ads 权限"],
        todo=["先接趋势和广告素材", "不碰 TikTok Shop 交易数据"],
    ),
    DataSourcePlan(
        source_id="aliexpress",
        name="AliExpress",
        phase="enhanced",
        priority="A",
        access_mode="public_scrape",
        account_required=False,
        paid_required=False,
        value="供应链价格、销量、评论和变体参考。",
        fields=["title", "price", "sales", "rating", "reviews", "shipping"],
        use_cases=["competitor_positioning", "category_intelligence"],
        todo=["建立相似款检索", "标准化供应链价格字段"],
    ),
    DataSourcePlan(
        source_id="ebay",
        name="eBay",
        phase="enhanced",
        priority="B",
        access_mode="api_or_public",
        account_required=True,
        paid_required=False,
        value="历史成交价格和清仓价参考。",
        fields=["title", "sold_price", "sold_at", "condition", "shipping"],
        use_cases=["competitor_positioning"],
        onboarding=["申请 eBay developer account"],
        todo=["优先接 sold/completed 价格信号"],
    ),
    DataSourcePlan(
        source_id="walmart",
        name="Walmart",
        phase="enhanced",
        priority="B",
        access_mode="public_scrape_or_paid_api",
        account_required=False,
        paid_required=False,
        value="美国本土竞品、价格和评论参考。",
        fields=["title", "price", "rating", "reviews", "availability"],
        use_cases=["competitor_positioning"],
        todo=["用于美国市场横向竞品校验"],
    ),
    DataSourcePlan(
        source_id="keepa",
        name="Keepa",
        phase="commercial",
        priority="S",
        access_mode="paid_api",
        account_required=True,
        paid_required=True,
        value="BSR、价格、Review 和 BuyBox 历史。",
        fields=["bsr_history", "price_history", "review_history", "buybox"],
        use_cases=["category_intelligence", "competitor_positioning"],
        onboarding=["采购 Keepa API", "获取 API key", "确认 token 预算"],
        todo=["作为历史趋势主数据源"],
    ),
    DataSourcePlan(
        source_id="rainforest",
        name="Rainforest",
        phase="commercial",
        priority="A",
        access_mode="paid_api",
        account_required=True,
        paid_required=True,
        value="Amazon Search/Product/Review API，降低爬虫维护。",
        fields=["search_results", "product", "reviews", "offers"],
        use_cases=["listing_audit", "competitor_positioning"],
        onboarding=["申请 Rainforest API 账号", "配置 API key"],
        todo=["替换高风险 Amazon 采集链路", "评估字段覆盖和成本"],
    ),
    DataSourcePlan(
        source_id="dataforseo",
        name="DataForSEO",
        phase="commercial",
        priority="A",
        access_mode="paid_api",
        account_required=True,
        paid_required=True,
        value="Amazon/Google 关键词和搜索量。",
        fields=["keyword", "search_volume", "competition", "trend"],
        use_cases=["keyword_opportunity", "category_intelligence"],
        onboarding=["申请 DataForSEO 账号", "配置 API key"],
        todo=["补关键词搜索量和搜索意图"],
    ),
    DataSourcePlan(
        source_id="oxylabs",
        name="Oxylabs",
        phase="commercial",
        priority="B",
        access_mode="enterprise_proxy_or_api",
        account_required=True,
        paid_required=True,
        value="企业级采集代理，覆盖 Amazon、TikTok、Temu、Walmart。",
        fields=["platform_payload", "proxy_session", "scrape_result"],
        use_cases=["listing_audit", "category_intelligence"],
        onboarding=["采购 Oxylabs 企业账号", "确认代理/API 套餐"],
        todo=["只在自建爬虫稳定性不足时采购"],
    ),
    DataSourcePlan(
        source_id="tiktok_shop",
        name="TikTok Shop",
        phase="commercial",
        priority="C",
        access_mode="account_or_paid_api",
        account_required=True,
        paid_required=True,
        value="商品销量、达人、视频和种草数据。",
        fields=["product", "sales", "creator", "video", "engagement"],
        use_cases=["category_intelligence", "buyer_insight"],
        onboarding=["准备 TikTok Shop 相关账号或第三方 API"],
        todo=["商业版再接", "优先第三方 API 或企业采集服务"],
    ),
    DataSourcePlan(
        source_id="temu",
        name="Temu",
        phase="commercial",
        priority="C",
        access_mode="paid_api_or_enterprise_scrape",
        account_required=True,
        paid_required=True,
        value="供应链价格、销量和评论参考。",
        fields=["title", "price", "sales", "reviews", "variants"],
        use_cases=["category_intelligence"],
        onboarding=["优先确认第三方 API 或企业采集服务"],
        todo=["商业版再接", "避免一期消耗研发资源"],
    ),
]

_SOURCE_BY_ID = {item.source_id: item for item in _DATA_SOURCES}
