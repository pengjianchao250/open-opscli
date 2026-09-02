#!/usr/bin/env python3
"""运营查询字段语义映射。

把稳定的中文业务说法映射到已授权数据集中的规范技术字段名。这里只提供
确定性别名和派生比例所需的基础字段，不读取远端数据，也不扩大权限范围。
"""

from __future__ import annotations

import re
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

# “销售情况”是业务指标集合，不是元数据中展示名为“销售”的人员维度。
# 仅映射跨即时销售数据集稳定存在的三项核心指标；字段不存在时由调用方忽略，
# 不会凭语义映射创造未授权字段。
BROAD_SALES_METRIC_FIELDS = ("price", "order_qty", "orders")
_BROAD_SALES_METRIC_RE = re.compile(
    r"销售\s*(?:情况|表现|业绩|概况|趋势|走势|怎么样|如何|好不好|好吗|数据(?!集))"
)
_SALES_PERSON_NOUN = (
    r"(?:销售负责人|销售人员|销售员|销售)"
    r"(?!额|金额|量|数据|情况|表现|业绩|概况|趋势|走势|怎么样|如何|好不好|好吗|订单)"
)
_SALES_PERSON_CONTEXT_RE = re.compile(
    rf"(?:按|依|以|各|每(?:个|位)?|所有|全部)\s*{_SALES_PERSON_NOUN}"
    rf"|{_SALES_PERSON_NOUN}\s*(?:为|是|=|＝|：|:|等于|筛选|过滤|分组|维度)"
)


def normalize(value: object) -> str:
    """对匹配文本执行 NFKC、大小写和首尾空白归一。"""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def has_broad_sales_metric_intent(query: str) -> bool:
    """判断是否明确表达宽泛销售经营指标意图。

    “销售数据集”中的“销售数据”属于数据集名称，负向前瞻会将其排除，
    避免用户只选表时被静默追加指标。
    """
    return bool(_BROAD_SALES_METRIC_RE.search(normalize(query)))


def sales_person_dimension_requested(query: str) -> bool:
    """判断“销售”是否明确指向销售人员维度、分组或筛选。"""
    text = normalize(query)
    if "team_username" in text or any(
        term in text for term in ("销售负责人", "销售人员", "销售员")
    ):
        return True
    return bool(_SALES_PERSON_CONTEXT_RE.search(text))


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
    if has_broad_sales_metric_intent(text):
        for field_name in BROAD_SALES_METRIC_FIELDS:
            matched.setdefault(field_name, "销售情况")
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
