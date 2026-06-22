"""西柚洞察排行榜导出列定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportColumn:
    """单个导出列定义。"""

    title: str
    source: str | None
    fallback: str | None = None


ASIN_COLUMNS = [
    ExportColumn("排名", "flowRank", fallback="rank"),
    ExportColumn("ASIN", "product.asin", fallback="asin"),
    ExportColumn("商品标题", "product.title", fallback="title"),
    ExportColumn("商品主图", "product.picUrl", fallback="imageUrl"),
    ExportColumn("商品链接", "product.amazonUrl", fallback="amazonUrl"),
    ExportColumn("站点", "product.country", fallback="country"),
    ExportColumn("币种", "product.currency", fallback="currency"),
    ExportColumn("价格", "product.price", fallback="price"),
    ExportColumn("评分", "product.stars", fallback="stars"),
    ExportColumn("评论数", "product.ratings", fallback="ratings"),
    ExportColumn("销量", "product.sales", fallback="sales"),
    ExportColumn("ASIN流量得分", "flow.score", fallback="score"),
    ExportColumn("流量增长率", "flow.scoreGrowthRatio", fallback="scoreGrowthRatio"),
    ExportColumn("是否新品", "flow.isNew", fallback="isNew"),
    ExportColumn("增长量", "growth", fallback="growthCount"),
    ExportColumn("自然流量得分", "natureFlowScore", fallback="naturalTrafficScore"),
    ExportColumn("自然流量占比", "natureRatio", fallback="naturalRatio"),
    ExportColumn("广告流量得分", "adFlowScore", fallback="adTrafficScore"),
    ExportColumn("广告流量占比", "adRatio"),
    ExportColumn("流量暴增排名", "surgingFlowRank"),
]


KEYWORD_COLUMNS = [
    ExportColumn("排名", "rank"),
    ExportColumn("关键词", "keyword", fallback="searchTerm"),
    ExportColumn("ABA排名", "abaRank", fallback="searchRank"),
    ExportColumn("搜索量", "searches", fallback="searchVolume"),
    ExportColumn("流量得分", "score", fallback="trafficScore"),
    ExportColumn("增长量", "growth", fallback="growthCount"),
    ExportColumn("商品数", "products", fallback="productCount"),
]


def columns_for_target(target: str) -> list[ExportColumn]:
    """返回排行榜 target 对应导出列。"""
    if target == "asin":
        return ASIN_COLUMNS
    if target == "keyword":
        return KEYWORD_COLUMNS
    return []
