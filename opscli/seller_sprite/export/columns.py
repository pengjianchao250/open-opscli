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
    ExportColumn("大类BSR增长率", "bsrRankCr", transform="percentSuffix"),
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
    ExportColumn("上架时间", "availableDate", transform="dateMillis"),
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
    ExportColumn("购买率", "purchaseRate", transform="percentage"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("SPR", "spr"),
    ExportColumn("标题密度", "titleDensity"),
    ExportColumn("商品数", "products"),
    ExportColumn("需供比", "supplyDemandRatio"),
    ExportColumn("广告竞品数", "adProducts"),
    ExportColumn("点击总占比", "monopolyClickRate", transform="percentage"),
    ExportColumn("转化总占比", "cvsShareRate", transform="percentage"),
    ExportColumn("PPC竞价", "bid", transform="currency"),
    ExportColumn("建议竞价范围", "bidMin", transform="bidRange"),
    ExportColumn("均价", "avgPrice", transform="currency"),
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


# 关键词选品列名和顺序逐列对齐官方 KeywordResearch-US-202606-667951.xlsx。
KEYWORD_RESEARCH_COLUMNS = [
    ExportColumn("关键词", "keyword"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("ABA排名", "searchRank"),
    ExportColumn("月搜索量", "searches"),
    ExportColumn("搜索增长率", "searchesCr"),
    ExportColumn("月购买量", "purchases"),
    ExportColumn("购买率", "purchaseRate"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("商品数", "products"),
    ExportColumn("需供比", "supplyDemandRatio"),
    ExportColumn("SPR", "spr"),
    ExportColumn("标题密度", "titleDensity"),
    ExportColumn("点击总占比", "monopolyClickRate"),
    ExportColumn("转化总占比", "cvsShareRate"),
    ExportColumn("货流值", "goodsValue"),
    ExportColumn("均价", "avgPrice"),
    ExportColumn("评分数", "avgReviews"),
    ExportColumn("评分值", "avgRating"),
    ExportColumn("PPC竞价-最低($)", "bidMin"),
    ExportColumn("PPC竞价-推荐($)", "bid"),
    ExportColumn("PPC竞价-最高($)", "bidMax"),
    ExportColumn("同比增长值", "searchMonthCv"),
    ExportColumn("同比增长率", "searchMonthCr"),
    ExportColumn("近3个月增长值", "searchNearlyCv"),
    ExportColumn("近3个月增长率", "searchNearlyCr"),
    ExportColumn("所属类目", "departments"),
    ExportColumn("前10ASIN", "gkDatas", transform="asinList"),
]


# ABA 数据选品列名和顺序逐列对齐官方 ABAKeywordTrend-US-2026第29周-690875.xlsx。
ABA_RESEARCH_COLUMNS = [
    ExportColumn("关键词", "keyword"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("周搜索量", "searches"),
    ExportColumn("现排名", "searchRank"),
    ExportColumn("历史排名", "w1SearchRank", transform="abaHistoricalRanks"),
    ExportColumn("周变化量", "w1RankGrowthValue", transform="abaRankGrowthValues"),
    ExportColumn("周变化率", "w1RankGrowthRate", transform="abaRankGrowthRates"),
    ExportColumn("PPC价格", "bid", transform="currency"),
    ExportColumn("建议竞价范围", "bidMin", transform="abaBidRange"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("SPR", "cprExact", fallback="spr"),
    ExportColumn("标题密度", "titleDensityExact", fallback="titleDensity"),
    ExportColumn("点击占比", "top3AsinDtoList", transform="abaClickShares"),
    ExportColumn("转化占比", "top3AsinDtoList", transform="abaConversionShares"),
    ExportColumn("点击前三ASIN", "top3AsinDtoList", transform="abaTopAsins"),
    ExportColumn("点击前三品牌", "top3Brands", transform="abaBrands"),
    ExportColumn("所属类目", "departments", transform="abaDepartments"),
    ExportColumn("前10ASIN", "gkDatas", transform="asinList"),
]


# 关联流量列名和顺序逐列对齐官方 RelatedProducts-US-B098T9ZFB5-batch(5)-260723.xlsx。
ASSOCIATION_TRAFFIC_COLUMNS = [
    ExportColumn("ASIN", "asin"),
    ExportColumn("关联ASIN数", "count"),
    ExportColumn("关联ASIN", "relationAsinDtoList", transform="asinList"),
    ExportColumn("关联类型", "relationList", transform="relationLabels"),
    ExportColumn("SKU", "sku"),
    ExportColumn("品牌", "brand"),
    ExportColumn("商品标题", "title"),
    ExportColumn("商品详情链接", None),
    ExportColumn("商品主图", "bigImageUrl", fallback="imageUrl"),
    ExportColumn("父体", "parent"),
    ExportColumn("类目路径", "nodeLabelPath"),
    ExportColumn("大类目", "bsrLabel"),
    ExportColumn("大类BSR", "bsrRank"),
    ExportColumn("大类BSR增长数", "bsrRankCv"),
    ExportColumn("大类BSR增长率", "bsrRankCr", transform="divide100"),
    ExportColumn("小类目", "subcategories.0.label"),
    ExportColumn("小类BSR", "subcategories.0.rank"),
    ExportColumn("月销量", "totalUnits"),
    ExportColumn("月销量增长率", "totalUnitsGrowth", transform="divide100"),
    ExportColumn("__TOTAL_AMOUNT__", "totalAmount"),
    ExportColumn("子体销量", "amzUnit"),
    ExportColumn("__SUB_TOTAL_AMOUNT__", "subTotalAmount"),
    ExportColumn("__PRICE__", "price"),
    ExportColumn("Q&A", "questions"),
    ExportColumn("毛利率", "profit", transform="divide100"),
    ExportColumn("__FBA__", "fba"),
    ExportColumn("评分数", "reviews"),
    ExportColumn("留评率", "reviewsRate", transform="divide100"),
    ExportColumn("评分", "rating"),
    ExportColumn("月新增评分数", "reviewsIncreasement"),
    ExportColumn("上架时间", "availableDate", transform="dateMillis"),
    ExportColumn("配送方式", "sellerType"),
    ExportColumn("__DELIVERY_PRICE__", "deliveryPrice", transform="emptyIfNegative"),
    ExportColumn("LQS", "lqs", transform="divide10Text"),
    ExportColumn("变体数", "variations"),
    ExportColumn("卖家数", "sellers"),
    ExportColumn("BuyBox卖家", "sellerName"),
    ExportColumn("卖家所属地", "sellerNation", transform="sellerNation"),
    ExportColumn("卖家信息", "sellerDto.businessAddress", transform="sellerAddress"),
    ExportColumn("BuyBox类型", "sellerType"),
    ExportColumn("Best Seller标识", "bestSeller", transform="badgeFlag"),
    ExportColumn("Amazon's Choice", "amazonChoice", transform="badgeFlag"),
    ExportColumn("New Release标识", "newRelease", transform="badgeFlag"),
    ExportColumn("A+页面", "ebc"),
    ExportColumn("视频介绍", "video"),
    ExportColumn("AC关键词", "amazonChoiceKeyword"),
    ExportColumn("商品重量", "weight"),
    ExportColumn("商品重量（单位换算）", "weightTag"),
    ExportColumn("商品尺寸", "dimensions"),
    ExportColumn("商品尺寸（单位换算）", "dimensionsTag"),
    ExportColumn("包装重量", "pkgWeight"),
    ExportColumn("包装重量（单位换算）", "pkgWeightTag"),
    ExportColumn("包装尺寸", "pkgDimensions"),
    ExportColumn("包装尺寸（单位换算）", "pkgDimensionsTag"),
    ExportColumn("包装尺寸分段", "pkgDimensionType"),
    ExportColumn("引流时间", "createdTime", transform="dateMillis"),
]


KEYWORD_REVERSE_COLUMNS = [
    ExportColumn("关键词", "keywords"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("流量占比", "trafficPercentage", transform="percentage"),
    ExportColumn("预估周曝光量", "calculatedWeeklySearches"),
    ExportColumn("关键词类型", "trafficKeywordTypes", transform="trafficKeywordTypeLabels"),
    ExportColumn("转化效果", "conversionKeywordTypes", transform="conversionKeywordTypeLabels"),
    ExportColumn("流量词类型", "badges", transform="badgeLabels"),
    ExportColumn("自然流量占比", "naturalRatio", transform="percentage"),
    ExportColumn("广告流量占比", "adRatio", transform="percentage"),
    ExportColumn("自然排名", "rankPosition", transform="rankPosition"),
    ExportColumn("自然排名页码", "rankPosition", transform="rankPage"),
    ExportColumn("更新时间", "rankPosition.updatedTime", transform="keywordReverseUpdatedTime"),
    ExportColumn("广告排名", "adPosition", transform="rankPosition"),
    ExportColumn("广告排名页码", "adPosition", transform="rankPage"),
    ExportColumn("更新时间", "adPosition.updatedTime", transform="keywordReverseUpdatedTime"),
    ExportColumn("ABA周排名", "searchesRank"),
    ExportColumn("月搜索量", "searches"),
    ExportColumn("SPR", "cprExact"),
    ExportColumn("标题密度", "titleDensityExact"),
    ExportColumn("购买量", "purchases"),
    ExportColumn("购买率", "purchaseRate", transform="percentage"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("商品数", "products"),
    ExportColumn("需供比", "supplyDemandRatio"),
    ExportColumn("近7天广告竞品数", "latest7daysAds"),
    ExportColumn("点击总占比", "monopolyClickRate", transform="percentage"),
    ExportColumn("转化总占比", "top3ConversionRate", transform="percentage"),
    ExportColumn("PPC价格", "bid", transform="currency"),
    ExportColumn("建议竞价范围", "bidMin", transform="bidRange"),
    ExportColumn("前十ASIN", "gkDatas", transform="asinList"),
]

# 列顺序来自 2026-07-31 官方拓展流量词工作簿的 33 列主表。
TRAFFIC_EXTEND_COLUMNS = [
    ExportColumn("关键词", "keywords"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("AC推荐词", "ac"),
    ExportColumn("流量占比", "trafficPercentage"),
    ExportColumn("流量词类型", "badges", fallback="trafficKeywordTypes", transform="badgeLabels"),
    ExportColumn("预估周曝光量", "calculatedWeeklySearches"),
    ExportColumn("相关产品", "relationVariationsItems", transform="listLength"),
    ExportColumn("相关ASIN", "relationVariationsItems", transform="asinList"),
    ExportColumn("ABA周排名", "searchesRank"),
    ExportColumn("月搜索量", "searches"),
    ExportColumn("月购买量", "purchases"),
    ExportColumn("购买率", "purchaseRate"),
    ExportColumn("展示量", "impressions"),
    ExportColumn("点击量", "clicks"),
    ExportColumn("SPR", "cprExact"),
    ExportColumn("标题密度", "titleDensityExact"),
    ExportColumn("商品数", "products"),
    ExportColumn("需供比", "supplyDemandRatio"),
    ExportColumn("广告竞品数", "latest7daysAds"),
    ExportColumn("点击总占比", "top3ClickingRate", fallback="monopolyClickRate"),
    ExportColumn("转化总占比", "top3ConversionRate"),
    ExportColumn("PPC竞价", "bid", transform="currency"),
    ExportColumn("建议竞价范围", "bidMin", transform="bidRange"),
    ExportColumn("#1 前三ASIN", "clickTop3s.0.asin"),
    ExportColumn("#1 点击共享", "clickTop3s.0.clickRate"),
    ExportColumn("#1 转化共享", "clickTop3s.0.conversionRate", fallback="clickTop3s.0.conversionShareRate"),
    ExportColumn("#2 前三ASIN", "clickTop3s.1.asin"),
    ExportColumn("#2 点击共享", "clickTop3s.1.clickRate"),
    ExportColumn("#2 转化共享", "clickTop3s.1.conversionRate", fallback="clickTop3s.1.conversionShareRate"),
    ExportColumn("#3 前三ASIN", "clickTop3s.2.asin"),
    ExportColumn("#3 点击共享", "clickTop3s.2.clickRate"),
    ExportColumn("#3 转化共享", "clickTop3s.2.conversionRate", fallback="clickTop3s.2.conversionShareRate"),
    ExportColumn("前十ASIN", "gkDatas", transform="asinList"),
]


TRAFFIC_SOURCE_COLUMNS = [
    ExportColumn("ASIN", "asin"),
    ExportColumn("标题", "title"),
    ExportColumn("价格", "price"),
    ExportColumn("评分", "rating"),
    ExportColumn("评分数", "reviews"),
    ExportColumn("变体数", "variations"),
    ExportColumn("SKU", "sku"),
    ExportColumn("流量来源", "badgeLabels", transform="trafficSourceLabels"),
    ExportColumn("全部流量词", "keywords"),
    ExportColumn("自然搜索词", "counter.NATURAL_SEARCHING"),
    ExportColumn("AC推荐词", "counter.AMAZON_CHOICE"),
    ExportColumn("ER推荐词", "counter.EDITORIAL_RECOMMENDATIONS"),
    ExportColumn("4星推荐词", "counter.FOUR_STAR"),
    ExportColumn("HR推荐词", "counter.HIGHLY_RATED"),
    ExportColumn("SP广告词", "counter.ADS"),
    ExportColumn("视频广告词", "counter.SPONSOR_VIDEO"),
    ExportColumn("品牌广告词", "counter.SPONSOR_BRAND"),
]


MARKET_RESEARCH_COLUMNS = [
    ExportColumn("细分市场", "market"),
    ExportColumn("细分市场(翻译)", "marketCn"),
    ExportColumn("市场路径", "marketPath"),
    ExportColumn("样本数量", "sampleQuantity"),
    ExportColumn("月总销量", "totalSales"),
    ExportColumn("月均销量", "avgSales"),
    ExportColumn("__AVG_REVENUE__", "avgRevenue"),
    ExportColumn("__AVG_PRICE__", "avgPrice"),
    ExportColumn("平均评分数", "avgReviews"),
    ExportColumn("平均星级", "avgRating"),
    ExportColumn("平均BSR", "avgBsr"),
    ExportColumn("平均卖家数", "avgSellers"),
    ExportColumn("卖家类型", "sellerTypes"),
    ExportColumn("商品集中度", "productConcentration", transform="percentSuffix"),
    ExportColumn("品牌集中度", "brandConcentration", transform="percentSuffix"),
    ExportColumn("卖家集中度", "sellerConcentration", transform="percentSuffix"),
    ExportColumn("商品总数", "totalProducts"),
    ExportColumn("平均重量", "avgWeight"),
    ExportColumn("平均体积", "avgVolume"),
    ExportColumn("平均毛利率", "avgProfit", transform="percentSuffix"),
    ExportColumn("A+占比", "ebcRatio", transform="percentSuffix"),
    ExportColumn("卖家所属地", "sellerNation"),
    ExportColumn("头部Listing月均销量", "headListingAvgSales"),
    ExportColumn("垄断度", "monopoly"),
    ExportColumn("__HEAD_AVG_REVENUE__", "headListingAvgRevenue"),
    ExportColumn("头部Listing平均BSR", "headListingAvgBsr"),
    ExportColumn("新品数量", "newCount"),
    ExportColumn("新品占比", "newRatio", transform="percentSuffix"),
    ExportColumn("新品月均销量", "newAvgSales"),
    ExportColumn("__NEW_AVG_REVENUE__", "newAvgRevenue"),
    ExportColumn("__NEW_AVG_PRICE__", "newAvgPrice"),
    ExportColumn("新品平均评分数", "newAvgReviews"),
    ExportColumn("新品平均星级", "newAvgRating"),
    ExportColumn("退货率", "returnRate"),
    ExportColumn("同类目退货率", "categoryReturnRate"),
    ExportColumn("搜索购买比", "searchPurchaseRatio"),
    ExportColumn("同类目搜索购买比", "categorySearchPurchaseRatio"),
]


# 列顺序来自 2026-07-31 官方关键词转化率工作簿的 33 列主表。
KEYWORD_CONVERSION_RATE_COLUMNS = [
    ExportColumn("关键词", "keyword"),
    ExportColumn("关键词翻译", "keywordCn"),
    ExportColumn("时间节点", "weekIndex"),
    ExportColumn("周搜索量", "searches"),
    ExportColumn("周点击量", "clicks"),
    ExportColumn("周购买量", "purchases"),
    ExportColumn("搜索转化率", "searchConvRate"),
    ExportColumn("点击转化率", "clickConvRate"),
    ExportColumn("PPC竞价-最低", "exactPpc.min"),
    ExportColumn("PPC竞价-推荐", "exactPpc.value"),
    ExportColumn("PPC竞价-最高", "exactPpc.max"),
    ExportColumn("CPA-最低", "exactCpa.min"),
    ExportColumn("CPA-推荐", "exactCpa.value"),
    ExportColumn("CPA-最高", "exactCpa.max"),
    ExportColumn("产品均价-最低", "avgProductPrice.min"),
    ExportColumn("产品均价-平均", "avgProductPrice.value"),
    ExportColumn("产品均价-最高", "avgProductPrice.max"),
    ExportColumn("ACOS-最低", "exactAcos.min"),
    ExportColumn("ACOS-推荐", "exactAcos.value"),
    ExportColumn("ACOS-最高", "exactAcos.max"),
    ExportColumn("广告预算", "exactBudget.value"),
    ExportColumn("点击总占比", "clickingRate"),
    ExportColumn("转化总占比", "conversionRate"),
    ExportColumn("#1 前三ASIN", "top3Asins.0.asin"),
    ExportColumn("#1 点击共享", "top3Asins.0.clickRate", fallback="top3Asins.0.clickingRate"),
    ExportColumn("#1 转化共享", "top3Asins.0.conversionRate", fallback="top3Asins.0.conversionShareRate"),
    ExportColumn("#2 前三ASIN", "top3Asins.1.asin"),
    ExportColumn("#2 点击共享", "top3Asins.1.clickRate", fallback="top3Asins.1.clickingRate"),
    ExportColumn("#2 转化共享", "top3Asins.1.conversionRate", fallback="top3Asins.1.conversionShareRate"),
    ExportColumn("#3 前三ASIN", "top3Asins.2.asin"),
    ExportColumn("#3 点击共享", "top3Asins.2.clickRate", fallback="top3Asins.2.clickingRate"),
    ExportColumn("#3 转化共享", "top3Asins.2.conversionRate", fallback="top3Asins.2.conversionShareRate"),
    ExportColumn("搜索结果前10ASIN", "gkDatas", transform="asinList"),
]


def columns_for_scenario(
    scenario: str,
    site: str,
    period: str | None = None,
) -> list[ExportColumn]:
    """返回场景对应官方模板列。"""
    currency = currency_label(site)
    if scenario == "keyword-miner":
        return _columns_with_currency_titles(
            KEYWORD_MINER_COLUMNS,
            currency,
            {"PPC竞价", "建议竞价范围", "均价"},
        )
    if scenario == "keyword-research":
        return KEYWORD_RESEARCH_COLUMNS
    if scenario == "aba-research":
        return ABA_RESEARCH_COLUMNS
    if scenario == "association-traffic":
        return _association_traffic_columns(currency)
    if scenario == "keyword-reverse":
        return _columns_with_currency_titles(
            KEYWORD_REVERSE_COLUMNS,
            currency,
            {"PPC价格", "建议竞价范围"},
        )
    if scenario == "traffic-extend":
        return TRAFFIC_EXTEND_COLUMNS
    if scenario == "keyword-conversion-rate":
        columns = _columns_with_currency_titles(
            KEYWORD_CONVERSION_RATE_COLUMNS,
            currency,
            {
                "PPC竞价-最低",
                "PPC竞价-推荐",
                "PPC竞价-最高",
                "CPA-最低",
                "CPA-推荐",
                "CPA-最高",
                "产品均价-最低",
                "产品均价-平均",
                "产品均价-最高",
                "广告预算",
            },
        )
        if str(period or "").upper() == "90D":
            ninety_day_titles = {
                "周搜索量": "近90天搜索量",
                "周点击量": "近90天点击量",
                "周购买量": "近90天购买量",
            }
            return [
                    ExportColumn(
                        ninety_day_titles.get(column.title, column.title),
                        column.source,
                    fallback=column.fallback,
                    transform=column.transform,
                )
                for column in columns
            ]
        return columns
    if scenario == "traffic-source":
        return _columns_with_currency_titles(TRAFFIC_SOURCE_COLUMNS, currency, {"价格"})
    if scenario == "market-research":
        return _market_research_columns(currency)
    if scenario == "competitor-lookup":
        return _product_columns(
            currency,
            swap_unit_columns=True,
            reviews_delta_source="reviewsIncreasement",
            percent_suffix_titles={"留评率", "毛利率"},
            seller_nation_source="sellerDto.nation",
        )
    if scenario == "product-research":
        return _product_columns(
            currency,
            swap_unit_columns=True,
            reviews_delta_source="reviewsIncreasement",
            percent_suffix_titles={"大类BSR增长率", "月销量增长率", "留评率", "毛利率"},
        )
    return []


def currency_label(site: str) -> str:
    """按站点选择导出表头币种标识。"""
    currencies = {
        "US": "$",
        "UK": "£",
        "DE": "€",
        "FR": "€",
        "JP": "円",
        "CA": "C$",
        "IT": "€",
        "ES": "€",
        "IN": "₹",
        "MX": "MX$",
    }
    return currencies.get(site.upper(), "$")


def _association_traffic_columns(currency: str) -> list[ExportColumn]:
    """替换关联流量官方模板中的币种占位表头。"""
    replacements = {
        "__TOTAL_AMOUNT__": f"月销售额({currency})",
        "__SUB_TOTAL_AMOUNT__": f"子体销售额({currency})",
        "__PRICE__": f"价格({currency})",
        "__FBA__": f"FBA运费({currency})",
        "__DELIVERY_PRICE__": f"买家运费({currency})",
    }
    return [
        ExportColumn(
            replacements.get(column.title, column.title),
            column.source,
            transform=column.transform,
            fallback=column.fallback,
        )
        for column in ASSOCIATION_TRAFFIC_COLUMNS
    ]


def _product_columns(
    currency: str,
    *,
    swap_unit_columns: bool = False,
    reviews_delta_source: str = "reviewsDelta",
    percent_suffix_titles: set[str] | None = None,
    seller_nation_source: str = "sellerNation",
) -> list[ExportColumn]:
    replacements = {
        "__TOTAL_AMOUNT__": f"月销售额({currency})",
        "__SUB_TOTAL_AMOUNT__": f"子体销售额({currency})",
        "__PRICE__": f"价格({currency})",
        "__PRIME_PRICE__": f"prime价格({currency})",
        "__FBA__": f"FBA({currency})",
        "__DELIVERY_PRICE__": f"买家运费({currency})",
    }
    columns: list[ExportColumn] = []
    percent_suffix_titles = percent_suffix_titles or set()
    for column in PRODUCT_COLUMNS_COMMON:
        source = column.source
        transform = column.transform
        if swap_unit_columns:
            if column.title == "月销量":
                source = "totalUnits"
            elif column.title == "子体销量":
                source = "amzUnit"
        if column.title == "LQS":
            transform = "divide10"
        if column.title == "月新增评分数":
            source = reviews_delta_source
        fallback = column.fallback
        if column.title == "卖家所属地":
            source = seller_nation_source
            fallback = "sellerNation" if seller_nation_source != "sellerNation" else column.fallback
            transform = "sellerNation"
        if column.title in percent_suffix_titles:
            transform = "percentSuffix"
        columns.append(ExportColumn(replacements.get(column.title, column.title), source, fallback, transform))
    return columns


def _columns_with_currency_titles(
    columns: list[ExportColumn],
    currency: str,
    titles: set[str],
) -> list[ExportColumn]:
    return [
        ExportColumn(
            f"{column.title}({currency})" if column.title in titles else column.title,
            column.source,
            column.fallback,
            column.transform,
        )
        for column in columns
    ]


def _market_research_columns(currency: str) -> list[ExportColumn]:
    replacements = {
        "__AVG_REVENUE__": f"月均销售额({currency})",
        "__AVG_PRICE__": f"平均价格({currency})",
        "__HEAD_AVG_REVENUE__": f"头部Listing月均销售额({currency})",
        "__NEW_AVG_REVENUE__": f"新品月均销售额({currency})",
        "__NEW_AVG_PRICE__": f"新品平均价格({currency})",
    }
    return [
        ExportColumn(replacements.get(column.title, column.title), column.source, column.fallback, column.transform)
        for column in MARKET_RESEARCH_COLUMNS
    ]
