"""amazon 模块数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class AmazonProductSnapshot:
    """单个 Amazon 商品抓取快照。"""

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
