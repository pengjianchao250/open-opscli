"""卖家精灵字段中文字典。"""

from __future__ import annotations

import re
from pathlib import Path


BUILTIN_FIELD_TITLES: dict[str, str] = {
    "asin": "ASIN",
    "sku": "SKU",
    "brand": "品牌",
    "title": "商品标题",
    "parent": "父ASIN",
    "nodeLabelPath": "类目路径",
    "categoryName": "类目",
    "category1Name": "大类目",
    "bsrRank": "BSR排名",
    "amzUnit": "月销量",
    "totalUnits": "销量",
    "totalAmount": "销售额",
    "price": "价格",
    "coupon": "Coupon",
    "questions": "Q&A",
    "reviews": "评分数",
    "rating": "评分",
    "fba": "FBA",
    "profit": "毛利率",
    "availableDate": "上架时间",
    "fulfillment": "配送方式",
    "lqs": "LQS",
    "sellerName": "卖家",
    "sellerType": "卖家类型",
    "sellerNation": "卖家所属地",
    "bestSeller": "Best Seller标识",
    "amazonChoice": "AC推荐词",
    "newRelease": "New Release标识",
    "keyword": "关键词",
    "keywords": "关键词",
    "keywordCn": "关键词翻译",
    "keywordJp": "关键词日文",
    "searches": "月搜索量",
    "purchases": "购买量",
    "purchaseRate": "购买率",
    "impressions": "展示量",
    "clicks": "点击量",
    "products": "商品数",
    "supplyDemandRatio": "需供比",
    "adProducts": "广告竞品数",
    "bid": "PPC竞价",
    "avgPrice": "均价",
    "avgReviews": "平均评分数",
    "avgRating": "平均评分",
    "titleDensity": "标题密度",
    "spr": "SPR",
    "relevancy": "相关度",
    "trafficPercentage": "流量占比",
}


def load_field_dictionary(reference_root: Path | None = None) -> dict[str, str]:
    """加载字段中文字典，内置字典优先保证可用。"""
    dictionary: dict[str, str] = {}
    root = reference_root or _discover_reference_root()
    if root and root.exists():
        dictionary.update(_load_markdown_tables(root))
    dictionary.update(BUILTIN_FIELD_TITLES)
    return dictionary


def _discover_reference_root() -> Path | None:
    """尝试发现 sellersprite-cli reference 目录。"""
    candidates = [
        Path.cwd() / "tmp" / "sellersprite-cli" / "src" / "sellersprite_cli" / "reference",
        Path.cwd().parent / "tmp" / "sellersprite-cli" / "src" / "sellersprite_cli" / "reference",
        Path("D:/Gitlab/tmp/sellersprite-cli/src/sellersprite_cli/reference"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_markdown_tables(root: Path) -> dict[str, str]:
    """从 Markdown 表格中提取 `字段 -> 说明`。"""
    dictionary: dict[str, str] = {}
    for path in root.rglob("*.md"):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            fields = _parse_markdown_row(line)
            if not fields:
                continue
            field, desc = fields
            for item in _split_field_names(field):
                dictionary.setdefault(item, desc)
    return dictionary


def _parse_markdown_row(line: str) -> tuple[str, str] | None:
    if not line.startswith("|") or "---" in line:
        return None
    parts = [part.strip().strip("`") for part in line.strip().strip("|").split("|")]
    if len(parts) < 2 or parts[0] in {"字段", "参数", "Field"}:
        return None
    field = parts[0]
    desc = parts[-1] if len(parts) >= 3 else parts[1]
    desc = _clean_desc(desc)
    if not field or not desc:
        return None
    return field, desc


def _split_field_names(value: str) -> list[str]:
    normalized = value.replace("items[].", "").replace("badge.{", "").replace("}", "")
    return [item.strip() for item in re.split(r"[/,]", normalized) if _is_field_name(item.strip())]


def _is_field_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", value))


def _clean_desc(value: str) -> str:
    desc = re.sub(r"\s+", " ", value).strip()
    return desc[:40]
