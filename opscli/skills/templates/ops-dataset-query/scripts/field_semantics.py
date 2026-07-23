#!/usr/bin/env python3
"""运营查询字段语义映射。

把稳定的中文业务说法映射到已授权数据集中的规范技术字段名。这里只提供
确定性别名和派生比例所需的基础字段，不读取远端数据，也不扩大权限范围。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable


# 仅收录跨数据集长期稳定、且物理字段身份唯一的业务别名。
FIELD_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "order_qty": ("销量", "单量", "订单量"),
    "price": ("销售额", "销售金额"),
    "advertising_fee": ("广告费", "广告花费"),
    "gross_profit": ("毛利", "毛利额"),
    "purchase_cost": ("采购成本", "采购费用"),
}

# 比例类口径必须由汇总后的分子和分母计算，规划时一次带齐基础字段。
DERIVED_METRIC_COMPONENTS: dict[str, tuple[str, ...]] = {
    "毛利率": ("gross_profit", "price"),
    "广告占比": ("advertising_fee", "price"),
    "采购成本占比": ("purchase_cost", "price"),
}


def normalize(value: object) -> str:
    """对匹配文本执行 NFKC、大小写和首尾空白归一。"""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def requested_canonical_fields(query: str) -> dict[str, str]:
    """返回查询明确命中的规范字段及其首个业务说法。

    返回字典而不是集合，便于后续审计字段为何被选择。只有规范技术字段真实
    存在于当前授权元数据时，调用方才会采用这里的结果。
    """
    text = normalize(query)
    matched: dict[str, str] = {}
    for field_name, terms in FIELD_QUERY_TERMS.items():
        for term in terms:
            if normalize(term) in text:
                matched.setdefault(field_name, term)
                break
    for term, field_names in DERIVED_METRIC_COMPONENTS.items():
        if normalize(term) not in text:
            continue
        for field_name in field_names:
            matched.setdefault(field_name, term)
    return matched


def metric_term_is_covered(requested_term: str, card_terms: Iterable[str]) -> bool:
    """判断数据集卡片是否覆盖一个业务指标词。

    卡片同时携带字段中文名和技术名；先做原词精确覆盖，再按规范技术字段
    别名判断，解决“销量”与 ``order_qty``/“订单量”表达不一致的问题。
    """
    normalized_terms = {normalize(item) for item in card_terms if normalize(item)}
    requested = normalize(requested_term)
    if requested in normalized_terms:
        return True
    for field_name, aliases in FIELD_QUERY_TERMS.items():
        if requested in {normalize(item) for item in aliases}:
            return normalize(field_name) in normalized_terms
    return False
