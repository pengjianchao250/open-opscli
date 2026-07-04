"""amazon 模块数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AmazonProductSnapshot:
    """单个 Amazon 商品抓取快照。

    基础字段（标题/价格/评分/评论数/位置）为一期采集口径；
    自 v0.0.108 起新增品牌、库存、五点描述、商品描述、图片、BSR 排名、
    类目、配送、卖家等扩展字段，全部带默认值以保持向后兼容。
    """

    asin: str
    zip_code: str
    marketplace: str
    page_url: str
    page_title: str
    product_name: str
    price_text: str
    price_amount: float | None
    currency: str | None
    rating_text: str
    rating_value: float | None
    review_count_text: str
    review_count_value: int | None
    location: str
    collected_at: str
    valid: bool
    error: str | None = None
    raw: dict[str, Any] | None = None
    # --- 扩展字段（v0.0.108+，用于更完整的商品信息采集）---
    brand: str = ""  # 品牌（bylineInfo）
    availability: str = ""  # 库存状态（如 In Stock / Only 3 left）
    bullet_points: list[str] = field(default_factory=list)  # 五点描述（feature bullets）
    description: str = ""  # 商品文字描述（productDescription）
    images: list[str] = field(default_factory=list)  # 商品图片 URL 列表（主图+缩略图）
    best_sellers_rank: str = ""  # Best Sellers Rank 原始文本
    categories: list[str] = field(default_factory=list)  # 面包屑类目路径
    delivery_info: str = ""  # 配送信息（Delivery 区块）
    ships_from: str = ""  # 发货方（Ships from）
    sold_by: str = ""  # 卖家（Sold by）
    coupon: str = ""  # 优惠券文案（如有）

    def to_dict(self, *, include_raw: bool = False) -> dict:
        data = asdict(self)
        if not include_raw:
            data.pop("raw", None)
        return data


@dataclass
class AmazonSearchResult:
    """Amazon 搜索结果条目。"""

    asin: str
    keyword: str
    zip_code: str
    rank: int
    title: str
    price_text: str
    price_amount: float | None
    rating_text: str
    rating_value: float | None
    review_count_text: str
    review_count_value: int | None
    is_best_seller: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AmazonCollectResult:
    """采集结果聚合对象。"""

    snapshot: AmazonProductSnapshot
    history_path: Path | None = None
    submit_result: dict | None = None

    def to_dict(self, *, include_raw: bool = False) -> dict:
        return {
            "snapshot": self.snapshot.to_dict(include_raw=include_raw),
            "history_path": str(self.history_path) if self.history_path else None,
            "submit_result": self.submit_result,
        }
