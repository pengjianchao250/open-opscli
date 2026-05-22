"""卖家精灵采集数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SellerSpriteCollectOptions:
    """卖家精灵采集输入参数。"""

    asin: str | None = None
    keyword: str | None = None
    site: str = "us"
    period: str = "30d"
    limit: int = 50
    frequency_phrase_count: int = 1
    trend_limit: int = 0
    trend_tabs: str = "all"
    archive: bool = True
    url: str | None = None
    output_dir: str | None = None
    account: str | None = None

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteFrequencyTerm:
    """高频词条目。"""

    keyword: str
    frequency: int
    percentage: float

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteKeywordItem:
    """关键词挖掘标准化条目。"""

    keyword: str
    keyword_cn: str
    keyword_jp: str
    departments: list[dict[str, Any]]
    trends: list[dict[str, Any]]
    searches: int | None
    purchases: int | None
    purchase_rate: float | None
    impressions: int | None
    clicks: int | None
    cvs_share_rate: float | None
    products: int | None
    ad_products: int | None
    supply_demand_ratio: float | None
    avg_price: float | None
    avg_reviews: int | None
    avg_rating: float | None
    bid: float | None
    phrase_ppc: float | None
    exact_ppc: float | None
    broad_ppc: float | None
    title_density: int | None
    spr: int | None
    relevancy: float | None
    absolute_relevancy: int | None
    amazon_choice: bool | None
    monopoly_asins: list[dict[str, Any]]
    monopoly_click_rate: float | None
    related_products: list[dict[str, Any]]

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteReverseKeywordItem:
    """关键词反查标准化条目。"""

    keyword: str
    keyword_cn: str
    keyword_jp: str
    position: str
    badges: list[Any]
    traffic_percentage: float | None
    searches: int | None
    purchases: int | None
    purchase_rate: float | None
    products: int | None
    impressions: int | None
    clicks: int | None
    spr: int | None
    title_density: int | None
    bid: float | None
    phrase_ppc: float | None
    exact_ppc: float | None
    broad_ppc: float | None
    searches_trend: list[dict[str, Any]]
    related_products: list[dict[str, Any]]

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteArchiveManifest:
    """单次采集归档索引。"""

    run_id: str
    root_dir: Path
    files: dict[str, str] = field(default_factory=dict)
    captcha_required: bool = False
    missing_sections: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为 JSON 友好的字典。"""
        return {
            "run_id": self.run_id,
            "root_dir": str(self.root_dir),
            "files": self.files,
            "captcha_required": self.captcha_required,
            "missing_sections": self.missing_sections,
            "errors": self.errors,
        }


@dataclass
class SellerSpriteCollectResult:
    """卖家精灵采集结果聚合对象。"""

    asin: str | None
    keyword: str | None
    site: str
    period: str
    limit: int
    frequency_phrase_count: int
    trend_limit: int
    trend_tabs: str
    run_id: str
    frequency_terms: list[SellerSpriteFrequencyTerm] = field(default_factory=list)
    keyword_items: list[SellerSpriteKeywordItem] = field(default_factory=list)
    reverse_keyword_items: list[SellerSpriteReverseKeywordItem] = field(default_factory=list)
    keyword_trends: list[dict[str, Any]] = field(default_factory=list)
    trend_details: list[dict[str, Any]] = field(default_factory=list)
    competitor_asins: list[dict[str, Any]] = field(default_factory=list)
    product_info: dict[str, Any] = field(default_factory=dict)
    variation_asins: list[dict[str, Any]] = field(default_factory=list)
    reverse_stats: dict[str, Any] = field(default_factory=dict)
    market_summary: dict[str, Any] = field(default_factory=dict)
    archive_manifest: SellerSpriteArchiveManifest | None = None

    def to_dict(self) -> dict:
        """转换为 CLI 输出结构。"""
        return {
            "asin": self.asin,
            "keyword": self.keyword,
            "site": self.site,
            "period": self.period,
            "limit": self.limit,
            "frequency_phrase_count": self.frequency_phrase_count,
            "trend_limit": self.trend_limit,
            "trend_tabs": self.trend_tabs,
            "run_id": self.run_id,
            "frequency_terms": [item.to_dict() for item in self.frequency_terms],
            "keyword_items": [item.to_dict() for item in self.keyword_items],
            "reverse_keyword_items": [item.to_dict() for item in self.reverse_keyword_items],
            "keyword_trends": self.keyword_trends,
            "trend_details": self.trend_details,
            "competitor_asins": self.competitor_asins,
            "product_info": self.product_info,
            "variation_asins": self.variation_asins,
            "reverse_stats": self.reverse_stats,
            "market_summary": self.market_summary,
            "archive_manifest": self.archive_manifest.to_dict() if self.archive_manifest else None,
        }
