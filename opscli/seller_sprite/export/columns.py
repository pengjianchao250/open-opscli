"""卖家精灵官方导出模板列定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportColumn:
    """单个导出列定义。"""

    title: str
    source: str | None
    fallback: str | None = None
    transform: str | None = None


PRODUCT_COLUMNS_COMMON = [
    ExportColumn("ASIN", "asin"),
    ExportColumn("SKU", "sku"),
    ExportColumn("详细参数", "overviews", transform="jsonObjectLines"),
    ExportColumn("品牌", "brand"),
    ExportColumn("品牌链接", "brandUrl"),
    ExportColumn("商品标题", "title"),
    ExportColumn("商品详情页链接", "asinUrl", fallback="asin", transform="amazonProductUrl"),
    ExportColumn("商品主图", "imageUrl"),
    ExportColumn("父ASIN", "parent"),
    ExportColumn("类目路径", "nodeLabelPath"),
    ExportColumn("大类目", "category1Name", fallback="categoryName"),
    ExportColumn("大类BSR", "bsrRank"),
    ExportColumn("大类BSR增长数", "bsrRankCv"),
    ExportColumn("大类BSR增长率", "bsrRankCr"),
    ExportColumn("小类目", "subcategories.0.label"),
    ExportColumn("小类BSR", "subcategories.0.rank"),
    ExportColumn("月销量", "amzUnit"),
    ExportColumn("月销量增长率", "totalUnitsGrowth"),
    ExportColumn("__TOTAL_AMOUNT__", "totalAmount"),
    ExportColumn("子体销量", "totalUnits"),
    ExportColumn("__SUB_TOTAL_AMOUNT__", "subTotalAmount"),
    ExportColumn("变体数", "variations"),
    ExportColumn("__PRICE__", "price"),
    ExportColumn("__PRIME_PRICE__", "primeExclusivePrice", transform="emptyIfNegative"),
    ExportColumn("Coupon", "coupon"),
    ExportColumn("Q&A", "questions"),
    ExportColumn("评分数", "reviews"),
    ExportColumn("月新增评分数", "reviewsDelta"),
    ExportColumn("评分", "rating"),
    ExportColumn("留评率", "reviewsRate"),
    ExportColumn("__FBA__", "fba"),
    ExportColumn("毛利率", "profit"),
    ExportColumn("评级", "ratingDelta"),
    ExportColumn("上架时间", "availableDate"),
    ExportColumn("上架天数", "availableDays"),
    ExportColumn("配送方式", "fulfillment", fallback="sellerType"),
    ExportColumn("__DELIVERY_PRICE__", "deliveryPrice", transform="emptyIfNegative"),
    ExportColumn("LQS", "lqs"),
    ExportColumn("卖家数", "sellers"),
    ExportColumn("BuyBox卖家", "sellerName"),
    ExportColumn("BuyBox类型", "sellerType"),
    ExportColumn("卖家所属地", "sellerNation"),
    ExportColumn("卖家信息", "sellerDto"),
    ExportColumn("卖家首页", "sellerId", transform="amazonSellerUrl"),
    ExportColumn("Best Seller标识", "bestSeller", transform="badgeFlag"),
    ExportColumn("Amazon's Choice", "amazonChoice", transform="badgeFlag"),
    ExportColumn("New Release标识", "newRelease", transform="badgeFlag"),
    ExportColumn("A+页面", "ebc"),
    ExportColumn("视频介绍", "video"),
    ExportColumn("SP广告", None),
    ExportColumn("品牌故事", None),
    ExportColumn("品牌广告", None),
    ExportColumn("7天促销", None),
    ExportColumn("AC关键词", "amazonChoice", transform="amazonChoiceKeyword"),
    ExportColumn("商品重量", "weight"),
    ExportColumn("商品重量（单位换算）", "weightTag"),
    ExportColumn("商品尺寸", "dimensions"),
    ExportColumn("商品尺寸（单位换算）", "dimensionsTag"),
    ExportColumn("包装重量", "pkgWeight"),
    ExportColumn("包装重量（单位换算）", "pkgWeightTag"),
    ExportColumn("包装尺寸", "pkgDimensions"),
    ExportColumn("包装尺寸（单位换算）", "pkgDimensionsTag"),
    ExportColumn("包装尺寸分段", "pkgDimensionType"),
    ExportColumn("标签", None),
]


KEYWORD_MINER_COLUMNS = [
    ExportColumn("关键词", "keyword"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("AC推荐词", "amazonChoice", transform="booleanY"),
    ExportColumn("相关度", "relevancy"),
    ExportColumn("ABA月排名", "searchRank"),
    ExportColumn("ABA周排名", "searchWeeklyRank"),
    ExportColumn("月搜索量", "searches"),
    ExportColumn("月购买量", "purchases"),
    ExportColumn("购买率", "purchaseRate"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("SPR", "spr"),
    ExportColumn("标题密度", "titleDensity"),
    ExportColumn("商品数", "products"),
    ExportColumn("需供比", "supplyDemandRatio"),
    ExportColumn("广告竞品数", "adProducts"),
    ExportColumn("点击总占比", "monopolyClickRate"),
    ExportColumn("转化总占比", "cvsShareRate"),
    ExportColumn("PPC竞价", "bid", transform="yen"),
    ExportColumn("建议竞价范围", "bidMin", transform="bidRange"),
    ExportColumn("均价", "avgPrice", transform="yen"),
    ExportColumn("评分数", "avgReviews"),
    ExportColumn("评分值", "avgRating"),
    ExportColumn("所属类目", "departments", transform="departmentsJoin"),
    ExportColumn("#1 前三ASIN", "monopolyAsinDtos.0.asin"),
    ExportColumn("#1 点击共享", "monopolyAsinDtos.0.clickRate"),
    ExportColumn("#1转化共享", "monopolyAsinDtos.0.conversionShareRate"),
    ExportColumn("#2 前三ASIN", "monopolyAsinDtos.1.asin"),
    ExportColumn("#2 点击共享", "monopolyAsinDtos.1.clickRate"),
    ExportColumn("#2 转化共享", "monopolyAsinDtos.1.conversionShareRate"),
    ExportColumn("#3 前三ASIN", "monopolyAsinDtos.2.asin"),
    ExportColumn("#3 点击共享", "monopolyAsinDtos.2.clickRate"),
    ExportColumn("#3 转化共享", "monopolyAsinDtos.2.conversionShareRate"),
    ExportColumn("前十ASIN", "gkDatas", transform="asinList"),
]


KEYWORD_REVERSE_COLUMNS = [
    ExportColumn("关键词", "keywords"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("流量占比", "trafficPercentage"),
    ExportColumn("预估周曝光量", "calculatedWeeklySearches"),
    ExportColumn("关键词类型", "badges", transform="listJoin"),
    ExportColumn("转化效果", "conversionKeywordTypes", transform="listJoin"),
    ExportColumn("流量词类型", "trafficKeywordTypes", transform="listJoin"),
    ExportColumn("自然流量占比", "naturalRatio"),
    ExportColumn("广告流量占比", "adRatio"),
    ExportColumn("自然排名", "rankPosition.position"),
    ExportColumn("自然排名页码", "rankPosition.page"),
    ExportColumn("更新时间", "rankPosition.updatedTime"),
    ExportColumn("广告排名", "adPosition.position"),
    ExportColumn("广告排名页码", "adPosition.page"),
    ExportColumn("更新时间", "adPosition.updatedTime"),
    ExportColumn("ABA周排名", "searchesRank"),
    ExportColumn("月搜索量", "searches"),
    ExportColumn("SPR", "cprExact"),
    ExportColumn("标题密度", "titleDensityExact"),
    ExportColumn("购买量", "purchases"),
    ExportColumn("购买率", "purchaseRate"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("商品数", "products"),
    ExportColumn("需供比", "supplyDemandRatio"),
    ExportColumn("近7天广告竞品数", "latest7daysAds"),
    ExportColumn("点击总占比", "monopolyClickRate"),
    ExportColumn("转化总占比", "top3ConversionRate"),
    ExportColumn("PPC价格", "bid", transform="yen"),
    ExportColumn("建议竞价范围", "bidMin", transform="bidRange"),
    ExportColumn("前十ASIN", "gkDatas", transform="asinList"),
]


def columns_for_scenario(scenario: str, site: str) -> list[ExportColumn]:
    """返回场景对应官方模板列。"""
    if scenario == "keyword-miner":
        return KEYWORD_MINER_COLUMNS
    if scenario == "keyword-reverse":
        return KEYWORD_REVERSE_COLUMNS
    if scenario in {"competitor-lookup", "product-research"}:
        return _product_columns(currency_label(site))
    return []


def currency_label(site: str) -> str:
    """按站点选择导出表头币种标识。"""
    return "円" if site.upper() == "JP" else "$"


def _product_columns(currency: str) -> list[ExportColumn]:
    replacements = {
        "__TOTAL_AMOUNT__": f"月销售额({currency})",
        "__SUB_TOTAL_AMOUNT__": f"子体销售额({currency})",
        "__PRICE__": f"价格({currency})",
        "__PRIME_PRICE__": f"prime价格({currency})",
        "__FBA__": f"FBA({currency})",
        "__DELIVERY_PRICE__": f"买家运费({currency})",
    }
    return [
        ExportColumn(replacements.get(column.title, column.title), column.source, column.fallback, column.transform)
        for column in PRODUCT_COLUMNS_COMMON
    ]
