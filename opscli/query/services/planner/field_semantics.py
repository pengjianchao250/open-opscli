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
    # 初级业务用户不会用元数据里的规范名，用的是自己部门的习惯叫法。
    # 只收录物理字段身份唯一、跨数据集不会指向别的口径的说法：
    # 「流水」（可指流水账明细）、「利润额」（毛利还是净利不确定）、
    # 「推广费」（与促销费口径不同）都因此不收录，保持澄清而不是猜。
    "order_qty": (
        "销量", "销售量", "销售数量", "销售件数", "单量", "订单量", "出单量", "成交量",
    ),
    "price": (
        "销售额", "销售金额", "销售总额", "营业额", "成交额", "收入", "gmv",
    ),
    "advertising_fee": (
        "广告费", "广告花费", "广告支出", "广告成本", "广告投入", "投放费用",
    ),
    "gross_profit": ("毛利", "毛利额", "毛利润"),
    "purchase_cost": ("采购成本", "采购费用", "进货成本"),
    # CTR（click-through rate）即点击率，广告投放通用缩写，口径唯一。
    # 同样常见的 CVR 不收：广告口径的 CVR 是订单/点击（数据集里叫「CPC转化率」），
    # 流量口径的「转化率」是订单/访客，两者都叫转化率，保持澄清而不是猜。
    "clicks_percent": ("ctr",),
    "ads_clicks_percent": ("ctr",),
    "click_rate": ("ctr",),
}

# 维度侧的稳定叫法，与 FIELD_QUERY_TERMS 分开维护：
# _requested_metric_terms 只读 FIELD_QUERY_TERMS，维度别名混进去会被当成"点名指标"，
# 触发"点名了指标却一个也没选上"的门禁并误伤分组维度。
# 数据集自带同名完整标签时（部分数据集的 org_name 就叫「事业部」），
# 精确标签优先规则会让本数据集的真实字段胜出，这里只在没有同名字段时兜底。
DIMENSION_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "dept_name": ("事业部", "集团事业部"),
}

# 初级业务用户的口语量化问法 → 规范字段。
# 这类说法（「卖了多少钱」「有多少单」）不是字段别名，而是整句问法，因此按句式
# 匹配而不是子串登记：裸「多少钱」会被「成本多少钱」「运费多少钱」误命中。
# 缺这一层时「近7天各平台卖了多少钱」会以 planned 下发一份 metrics 为空的模板，
# 查询成功返回一列平台名，用户的核心诉求整个消失且没有任何提示。
COLLOQUIAL_METRIC_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"卖了?多少钱|销售了多少钱|卖了多少金额|营收多少钱", "price", "卖了多少钱"),
    (
        r"卖了?多少(?:个|件|台|只|套|双|盒|箱|支|张)"
        r"|销(?:售|出)了?多少(?:个|件|台|只|套|双|盒|箱|支|张)",
        "order_qty",
        "卖了多少个",
    ),
    (
        r"(?:有|出|接|下)?多少(?:个|笔)?单(?![位价号据元])"
        r"|几单(?![位价号据元])|多少笔订单|多少个订单",
        "order_qty",
        "多少单",
    ),
    # 「广告花了多少」是问广告费的口语说法；必须带「广告/投放/推广」限定，
    # 裸「花了多少钱」指向不明（可能是采购、物流、仓储），不予收录。
    (
        r"(?:广告|投放|推广)\s*(?:一共|总共|大概)?\s*(?:花|用|投|烧)了?多少(?:钱|金额)?"
        r"|(?:广告|投放|推广)\s*(?:花费|支出|投入)了?多少",
        "advertising_fee",
        "广告花了多少",
    ),
)


def colloquial_metric_fields(query: str) -> dict[str, str]:
    """口语量化问法命中的规范字段及其展示说法。

    返回 {字段技术名: 用户说法}，与 requested_canonical_fields 的形状一致，
    调用方仍需确认该字段真实存在于当前授权元数据后才会采用。
    """
    text = normalize(query)
    matched: dict[str, str] = {}
    for pattern, field_name, label in COLLOQUIAL_METRIC_PATTERNS:
        if re.search(pattern, text):
            matched.setdefault(field_name, label)
    return matched


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
    # 「卖得最好的3个平台」是初级业务用户的排序问法，指标本身是模糊的
    # （销售额还是销量并不确定）。归入宽泛销售意图后会带齐三项核心销售指标，
    # 并由多指标排序判定给出"未能唯一确定排序指标"的强制披露，让 Agent 去问；
    # 不归入时整句一个指标都选不上，静默返回一列平台名。
    r"|卖得?\s*(?:最好|最多|最差|最少|最棒|好不好|怎么样|如何)"
    r"|卖的\s*最\s*(?:好|多|差|少)"
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


def _is_ascii_word_char(char: str) -> bool:
    """英文字母或数字：判断英文字段词是否落在单词边界上。"""
    return char.isascii() and char.isalnum()


def has_standalone_term_occurrence(term: str, query: str) -> bool:
    """字段词至少独立出现一次，不能从查询动作词内部起始后跨出。

    以英文字母或数字开头/结尾的字段词还要求落在单词边界上：「TACOS」里的
    「acos」、「SBV」里的「sb」、「近17日」里的「7日」都不是独立出现。
    缺这条时「各平台的TACOS」被静默选成 ACOS——TACOS 按总销售额算、ACOS 按
    广告销售额算，口径不同却没有任何提示。中文字段词不受影响。
    """
    text = normalize(query)
    needle = normalize(term)
    if not needle:
        return False
    action_spans = [
        span
        for action in _QUERY_ACTION_TERMS
        for span in _term_spans(normalize(action), text)
    ]

    def on_word_boundary(start: int, end: int) -> bool:
        if _is_ascii_word_char(needle[0]) and start > 0 and _is_ascii_word_char(text[start - 1]):
            return False
        if _is_ascii_word_char(needle[-1]) and end < len(text) and _is_ascii_word_char(text[end]):
            return False
        return True

    return any(
        on_word_boundary(start, end)
        and not any(
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
        normalized_term = normalize(term)
        if normalized_term not in text:
            continue
        # 数据集自己就有这个口径的完整字段时（「毛利率」「SP广告占比」），
        # 它是权威口径，不能再按分子分母拆成两个基础字段——拆了以后既选不上
        # 那个真实字段，还会被门禁判成"当前数据集没有请求的指标"，
        # 一条完全正常的取数被卡在澄清上（全字段矩阵实测 5 例）。
        if any(normalized_term in normalize(item) for item in protected):
            continue
        for field_name in field_names:
            matched.setdefault(field_name, term)
    if has_broad_sales_metric_intent(text):
        for field_name in BROAD_SALES_METRIC_FIELDS:
            matched.setdefault(field_name, "销售情况")
    # 口语量化问法与上面的稳定别名同级：都只在字段真实存在时由调用方兑现
    for field_name, label in colloquial_metric_fields(text).items():
        matched.setdefault(field_name, label)
    return matched


def dimension_alias_fields(query: str) -> dict[str, str]:
    """维度侧稳定叫法命中的规范字段及其业务说法。

    与 requested_canonical_fields 分开：后者的结果同时用于"点名指标完整性"校验，
    维度别名混进去会被当成缺失指标，把一次正常的按部门分组判成
    「当前数据集没有请求的指标」。
    """
    text = normalize(query)
    matched: dict[str, str] = {}
    for field_name, terms in DIMENSION_QUERY_TERMS.items():
        for term in terms:
            if normalize(term) in text:
                matched.setdefault(field_name, term)
                break
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
