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
    "price": ("销售额", "销售金额", "收入"),
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
    r"(?!额|金额|量|小组|数据|情况|表现|业绩|概况|趋势|走势|怎么样|如何|好不好|好吗|订单)"
)
_SALES_PERSON_CONTEXT_RE = re.compile(
    rf"(?:按|依|以|各|每(?:个|位)?|所有|全部)\s*{_SALES_PERSON_NOUN}"
    rf"|{_SALES_PERSON_NOUN}\s*(?:为|是|=|＝|：|:|等于|筛选|过滤|分组|维度)"
)
_QUERY_ACTION_TERMS = ("查询", "查看", "分析", "获取", "汇总", "统计", "展示", "列出")


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


def _term_spans(term: str, text: str) -> list[tuple[int, int]]:
    """返回 term 在 text 中的全部重叠命中区间。"""
    spans: list[tuple[int, int]] = []
    start = text.find(term)
    while start >= 0:
        spans.append((start, start + len(term)))
        start = text.find(term, start + 1)
    return spans


def has_standalone_term_occurrence(term: str, query: str) -> bool:
    """字段词至少独立出现一次，不能从查询动作词内部起始后跨出。"""
    text = normalize(query)
    needle = normalize(term)
    if not needle:
        return False
    action_spans = [
        span
        for action in _QUERY_ACTION_TERMS
        for span in _term_spans(normalize(action), text)
    ]
    return any(
        not any(
            action_start < start < action_end and end >= action_end
            for action_start, action_end in action_spans
        )
        for start, end in _term_spans(needle, text)
    )


def _has_uncovered_occurrence(
    term: str, text: str, protected_terms: Iterable[str]
) -> bool:
    """term 是否至少有一次独立出现，而非仅属于更长的精确字段标签。"""
    term_spans = _term_spans(term, text)
    if not term_spans:
        return False
    covering_spans = [
        span
        for raw_protected in protected_terms
        if (protected := normalize(raw_protected))
        and protected != term
        and term in protected
        for span in _term_spans(protected, text)
    ]
    return any(
        not any(start <= term_start and term_end <= end for start, end in covering_spans)
        for term_start, term_end in term_spans
    )


def requested_canonical_fields(
    query: str, *, protected_terms: Iterable[str] = ()
) -> dict[str, str]:
    """返回查询明确命中的规范字段及其首个业务说法。

    返回字典而不是集合，便于后续审计字段为何被选择。只有规范技术字段真实
    存在于当前授权元数据时，调用方才会采用这里的结果。protected_terms 是
    当前数据集在原文中精确出现的完整指标标签；稳定短别名若只出现在这些
    长标签内部，不再被误判为另一个指标诉求。
    """
    text = normalize(query)
    matched: dict[str, str] = {}
    protected = tuple(protected_terms)
    for field_name, terms in FIELD_QUERY_TERMS.items():
        for term in terms:
            if _has_uncovered_occurrence(normalize(term), text, protected):
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
