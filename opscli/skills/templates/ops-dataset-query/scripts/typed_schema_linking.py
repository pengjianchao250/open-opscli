#!/usr/bin/env python3
"""意图规则校验与查询语义抽取（typed schema linking）。

职责：
1. validate_rules —— 对 data/intent_rules.json 做强结构校验，
   防止规则文件漂移导致选表行为静默变化；
2. extract_query_semantics —— 从用户查询中抽取领域（domain）、
   指标词（metric）与槽位（platform/ad_type/grain）；
3. profile_card —— 依据规则为每张数据集卡片生成语义画像，
   供 agent_query_planner 做覆盖判断和打分。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable


RULES_SCHEMA_VERSION = 3
MAX_TEXT_LENGTH = 256
# 领域与槽位是封闭集合：规则文件必须完整覆盖，多键或少键都视为非法
ALLOWED_DOMAINS = frozenset(
    {"sales", "advertising", "inventory", "traffic", "refund", "logistics", "product", "finance"}
)
ALLOWED_SLOTS = frozenset({"platform", "ad_type", "grain"})
# 槽位名 → 用户可见中文标签。槽位取值的中文标签直接复用 intent_rules.json 的
# terms 词表（见 slot_value_label），但槽位名本身在规则文件里没有对应中文，
# 只能在此维护；ALLOWED_SLOTS 是封闭集合，两者必须逐键对齐（有测试守护）。
# 为什么必须有：platform/ad_type/grain 都是内部标识，直接拼进面向用户的中文
# 披露句会泄露技术口径（实测出现过「所选数据集的ad_type粒度…」这种句子）。
SLOT_LABELS_ZH = {
    "platform": "平台",
    "ad_type": "广告类型",
    "grain": "统计粒度",
}
RECORD_KEYS = frozenset({"terms", "description_patterns"})
# 卡片上参与文本匹配的三类词表键
FIELD_TERM_KEYS = ("dimension_terms", "metric_terms", "select_column_terms")
# 内部技术标识（ds_*/f_*）的引用形式，规则词表中禁止出现
ALIAS_REFERENCE_RE = re.compile(
    r"(?<![a-z0-9_])(?:ds|f)_[a-z0-9][a-z0-9_]*(?![a-z0-9_])",
    re.IGNORECASE,
)
SpanFinder = Callable[[str, str], list[tuple[int, int]]]


def normalize(value: object) -> str:
    """NFKC 归一化 + casefold + 去首尾空白；非字符串一律归一为空串。"""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _term_spans(term: str, text: str) -> list[tuple[int, int]]:
    """返回词条在文本中的所有匹配区间。

    ASCII 词条按单词边界匹配（允许空格/引号/下划线/连字符作为词间分隔），
    避免 "sc" 误命中 "scale" 这类子串；中文词条按原样子串匹配。
    """
    term = normalize(term)
    text = normalize(text)
    if not term:
        return []
    if term.isascii():
        words = re.findall(r"[a-z0-9]+", term)
        if not words:
            return []
        expression = r"[\s'_-]+".join(re.escape(word) for word in words)
        return [
            match.span()
            for match in re.finditer(rf"(?<![a-z0-9]){expression}(?![a-z0-9])", text)
        ]
    return [(match.start(), match.end()) for match in re.finditer(re.escape(term), text)]


def term_matches(term: str, text: str) -> bool:
    """判断词条是否命中文本（带边界规则）。"""
    return bool(_term_spans(term, text))


def slot_label(name: str) -> str:
    """槽位名 → 中文标签；未登记时原样返回（规则校验已保证槽位是封闭集合）。"""
    return SLOT_LABELS_ZH.get(name, str(name))


def slot_value_label(rules: dict, slot_name: str, value: str) -> str:
    """槽位取值的内部枚举名 → 用户可见标签。

    不新造词表：直接取 intent_rules.json 里该取值的 terms，优先第一个含中文的
    词条（search_term → 搜索词、amazon_sc → 亚马逊sc）；全英文词条（如 sp、sd）
    没有中文可用，退回枚举名本身。最后统一 upper()——规则词表经 normalize 后
    全小写，「亚马逊sc」必须还原成用户习惯的「亚马逊SC」，sp 也要写成 SP。
    """
    terms = (
        ((rules.get("slots") or {}).get(slot_name) or {}).get(str(value), {}).get("terms")
        or []
    )
    chinese = next((str(term) for term in terms if not str(term).isascii()), "")
    return (chinese or str(value)).upper()


def _pattern_spans(pattern: str, text: str) -> list[tuple[int, int]]:
    """描述模式按原样子串匹配（用于数据集中文说明的画像匹配）。"""
    pattern = normalize(pattern)
    text = normalize(text)
    return [(match.start(), match.end()) for match in re.finditer(re.escape(pattern), text)]


def all_slot_terms(rules: dict) -> frozenset:
    """全部槽位词（跨槽位合并）。

    用于判断复合词里相邻段是否本身就是槽位词——「亚马逊-vc」的 vc 是平台写法变体，
    「亚马逊-运营C组」的「运营C组」不是。词表全部取自现有 slots，不新造。
    """
    return frozenset(
        normalize(term)
        for slot_values in (rules.get("slots") or {}).values()
        for record in slot_values.values()
        for term in record.get("terms") or []
        if normalize(term)
    )


def _is_value_fragment(
    normalized_text: str, start: int, end: int, sibling_terms: frozenset
) -> bool:
    """命中是否只是用户给出的复合字面值中的一段，而非独立的槽位诉求。

    两侧都要判，因为真实授权值里两种形态都存在（均为实测命中的生产值）：
    - 后段：渠道值「傲彼瑞-tiktok」里的 tiktok；
    - 首/中段：销售小组值「亚马逊-运营C组」里的亚马逊、渠道SKU 值「SD-51709」里的 sd、
      产品型号值「SC-BCH-0002」里的 sc。
    首段这一类的后果比后段更重：ad_type 槽位一旦被点亮，即时综合数据集不覆盖该槽位，
    候选直接归零，整条查询死在选表阶段（实测 dataset 未定、无可行下一步）。

    相邻段本身是槽位词时不算片段：「亚马逊-vc」「amazon-sc」是平台的书写变体，
    误剔会把用户真正的平台诉求整条丢掉。
    """
    # 前置分隔符 → 命中是复合值的后段
    if 0 < start <= len(normalized_text) and normalized_text[start - 1] in "-_":
        return True
    # 后置分隔符 → 命中是复合值的首段或中段
    if end < len(normalized_text) and normalized_text[end] in "-_":
        tail = normalized_text[end + 1 :]
        if not any(tail.startswith(term) for term in sibling_terms):
            return True
    return False


def _matched_values(
    text: str,
    values: dict,
    record_key: str,
    span_finder: SpanFinder,
    *,
    drop_value_fragments: bool = False,
    sibling_terms: frozenset = frozenset(),
) -> list[str]:
    """返回命中的槽位取值，命中区间被更长的其他取值完全覆盖时让位。

    例："亚马逊vc" 同时命中 amazon（亚马逊）与 amazon_vc（亚马逊vc），
    amazon 的匹配区间被 amazon_vc 完全包含且更短，因此只保留 amazon_vc。

    drop_value_fragments=True 时额外剔除复合字面值中的片段命中（见
    _is_value_fragment）；sibling_terms 传全部槽位词，用于保住平台的书写变体。
    只对查询原文的槽位读取启用；数据集说明的画像匹配不受影响。
    """
    occurrences = [
        (start, end, value_name)
        for value_name, record in values.items()
        for pattern in record[record_key]
        for start, end in span_finder(pattern, text)
    ]
    if drop_value_fragments:
        normalized_text = normalize(text)
        occurrences = [
            (start, end, value_name)
            for start, end, value_name in occurrences
            if not _is_value_fragment(normalized_text, start, end, sibling_terms)
        ]
    surviving = {
        value_name
        for start, end, value_name in occurrences
        if not any(
            other_value != value_name
            and other_start <= start
            and end <= other_end
            and other_end - other_start > end - start
            for other_start, other_end, other_value in occurrences
        )
    }
    return [value_name for value_name in values if value_name in surviving]


def _validated_list(value: object, label: str) -> list[str]:
    """校验规则词表：非空列表、归一化后非空且不重复、不得包含内部技术标识。"""
    if not isinstance(value, list) or not value:
        raise ValueError(f"invalid_rules:{label}_must_be_non_empty_list")
    result = []
    seen = set()
    for item in value:
        normalized = normalize(item)
        if (
            not normalized
            or len(normalized) > MAX_TEXT_LENGTH
            or normalized in seen
            or ALIAS_REFERENCE_RE.search(normalized)
        ):
            raise ValueError(f"invalid_rules:{label}_contains_invalid_value")
        seen.add(normalized)
        result.append(normalized)
    return result


def _validated_record(value: object, label: str) -> dict[str, list[str]]:
    """校验一条规则记录：必须且只能包含 terms 与 description_patterns 两个词表。"""
    if not isinstance(value, dict) or set(value) != RECORD_KEYS:
        raise ValueError(f"invalid_rules:{label}_bad_record")
    return {
        "terms": _validated_list(value["terms"], f"{label}.terms"),
        "description_patterns": _validated_list(
            value["description_patterns"], f"{label}.description_patterns"
        ),
    }


def validate_rules(rules: object) -> dict:
    """对意图规则做全量结构校验并返回归一化副本。

    校验是封闭式的：根键集合、schema_version、领域全集、槽位全集
    都必须精确匹配，防止规则文件被部分修改后静默生效。
    """
    root_keys = {
        "schema_version",
        "domains",
        "metric_terms",
        "slots",
        "filter_fields",
        "platform_scope",
        "compatibility",
    }
    if not isinstance(rules, dict) or set(rules) != root_keys:
        raise ValueError("invalid_rules:bad_root")
    if rules.get("schema_version") != RULES_SCHEMA_VERSION:
        raise ValueError("invalid_rules:unsupported_schema_version")
    domains = rules.get("domains")
    slots = rules.get("slots")
    if not isinstance(domains, dict) or set(domains) != ALLOWED_DOMAINS:
        raise ValueError("invalid_rules:bad_domains")
    if not isinstance(slots, dict) or set(slots) != ALLOWED_SLOTS:
        raise ValueError("invalid_rules:bad_slots")

    validated_domains = {
        name: _validated_record(record, f"domains.{name}")
        for name, record in domains.items()
    }
    validated_metric_terms = _validated_list(rules.get("metric_terms"), "metric_terms")
    validated_slots = {}
    for slot_name, values in slots.items():
        if not isinstance(values, dict) or not values:
            raise ValueError(f"invalid_rules:slots.{slot_name}_must_be_non_empty_object")
        validated_values = {}
        for value_name, record in values.items():
            # 槽位取值名是技术枚举名，只允许小写字母数字下划线
            if (
                len(str(value_name)) > MAX_TEXT_LENGTH
                or re.fullmatch(r"[a-z0-9_]+", str(value_name)) is None
            ):
                raise ValueError(f"invalid_rules:slots.{slot_name}_bad_value_name")
            validated_values[str(value_name)] = _validated_record(
                record, f"slots.{slot_name}.{value_name}"
            )
        validated_slots[slot_name] = validated_values

    filter_fields = rules.get("filter_fields")
    if not isinstance(filter_fields, dict) or set(filter_fields) != {"platform", "ad_type"}:
        raise ValueError("invalid_rules:bad_filter_fields")
    validated_filters = {
        name: _validated_list(values, f"filter_fields.{name}")
        for name, values in filter_fields.items()
    }
    platform_scope = rules.get("platform_scope")
    if not isinstance(platform_scope, dict) or set(platform_scope) != {"members", "filter_values"}:
        raise ValueError("invalid_rules:bad_platform_scope")
    members = platform_scope["members"]
    filter_values = platform_scope["filter_values"]
    if (
        not isinstance(members, dict)
        or not isinstance(filter_values, dict)
        or not members
        or not set(members).issubset(validated_slots["platform"])
    ):
        raise ValueError("invalid_rules:bad_platform_scope_values")
    validated_members = {
        name: _validated_list(values, f"platform_scope.members.{name}")
        for name, values in members.items()
    }
    member_values = {
        member for values in validated_members.values() for member in values
    }
    if not member_values.issubset(validated_slots["platform"]):
        raise ValueError("invalid_rules:unknown_platform_scope_member")
    # filter_values 的键必须精确覆盖所有语义成员值（枚举别名只对成员值有意义），
    # 键多于或少于成员值集合都说明配置漂移
    if set(filter_values) != member_values:
        raise ValueError("invalid_rules:bad_platform_scope_values")
    validated_filter_values = {
        name: _validated_list(values, f"platform_scope.filter_values.{name}")
        for name, values in filter_values.items()
    }
    compatibility = rules.get("compatibility")
    if not isinstance(compatibility, dict) or set(compatibility) != {"ad_type_platform"}:
        raise ValueError("invalid_rules:bad_compatibility")
    ad_platform = compatibility["ad_type_platform"]
    if not isinstance(ad_platform, dict) or set(ad_platform) != set(validated_slots["ad_type"]):
        raise ValueError("invalid_rules:bad_ad_type_platform")
    validated_compatibility = {}
    for ad_type, platforms in ad_platform.items():
        values = _validated_list(platforms, f"compatibility.ad_type_platform.{ad_type}")
        if not set(values).issubset(validated_slots["platform"]):
            raise ValueError("invalid_rules:unknown_compatible_platform")
        validated_compatibility[ad_type] = values
    return {
        "schema_version": RULES_SCHEMA_VERSION,
        "domains": validated_domains,
        "metric_terms": validated_metric_terms,
        "slots": validated_slots,
        "filter_fields": validated_filters,
        "platform_scope": {
            "members": validated_members,
            "filter_values": validated_filter_values,
        },
        "compatibility": {"ad_type_platform": validated_compatibility},
    }


def extract_query_semantics(query: str, rules: dict) -> dict:
    """从查询文本中抽取领域、指标词与槽位取值（不做数据集选择）。

    领域命中要求存在不被指标词区间完全覆盖的独立证据：
    例如"销售额"只算指标词，不能凭它单独判定 sales 领域。
    """
    if not isinstance(query, str):
        raise TypeError("query_must_be_string")
    metric_spans = [
        span for term in rules["metric_terms"] for span in _term_spans(term, query)
    ]
    metrics = [term for term in rules["metric_terms"] if term_matches(term, query)]
    domains = []
    for name, record in rules["domains"].items():
        matches = [span for term in record["terms"] for span in _term_spans(term, query)]
        if any(
            not any(blocked_start <= start and end <= blocked_end for blocked_start, blocked_end in metric_spans)
            for start, end in matches
        ):
            domains.append(name)
    slots = {}
    sibling_terms = all_slot_terms(rules)
    for slot_name, values in rules["slots"].items():
        # 查询原文里的槽位读取要剔除复合字面值中的片段命中（「傲彼瑞-tiktok」的 tiktok、
        # 「SD-51709」的 sd、「亚马逊-运营C组」的亚马逊），否则用户给出的组件值
        # 会被读成平台/广告类型诉求：轻则凭空多出平台范围，重则选表候选归零
        matched = _matched_values(
            query,
            values,
            "terms",
            _term_spans,
            drop_value_fragments=True,
            sibling_terms=sibling_terms,
        )
        if matched:
            slots[slot_name] = matched
    return {"domains": domains, "metrics": metrics, "slots": slots}


def profile_card(card: dict, rules: dict) -> dict:
    """依据规则为一张数据集卡片生成语义画像。

    画像包含：
    - domains：数据集中文说明命中的业务领域；
    - slots：各槽位的取值覆盖（来自说明文案）；
    - slot_modes：槽位模式——fixed（固定口径）/ filterable（含可筛选字段）
      / unsupported（不覆盖该槽位）；
    - text：参与残差词匹配的说明文本。
    """
    text = " ".join(str(card.get(key, "")) for key in ("description", "remarks"))
    domains = {
        name
        for name, record in rules["domains"].items()
        if any(_pattern_spans(pattern, text) for pattern in record["description_patterns"])
    }
    slots = {
        name: set(_matched_values(text, values, "description_patterns", _pattern_spans))
        for name, values in rules["slots"].items()
    }
    # 说明中出现广告类型即视为广告领域数据集
    if slots["ad_type"]:
        domains.add("advertising")
    field_terms = {normalize(term) for key in FIELD_TERM_KEYS for term in card[key]}
    has_filter_field = {
        name: bool(field_terms.intersection(terms))
        for name, terms in rules["filter_fields"].items()
    }
    slot_modes = {
        name: ("fixed" if values else "unsupported") for name, values in slots.items()
    }
    # 数据集带平台/广告类型筛选字段时，对应槽位从固定口径升级为可筛选
    if slots["platform"] and has_filter_field["platform"]:
        slot_modes["platform"] = "filterable"
    if slots["ad_type"] and has_filter_field["ad_type"]:
        slot_modes["ad_type"] = "filterable"
    # 说明只写了广告类型没写平台时，按广告类型的相容平台推导平台覆盖
    if slots["ad_type"] and not slots["platform"]:
        compatible_platforms = [
            set(rules["compatibility"]["ad_type_platform"][ad_type])
            for ad_type in slots["ad_type"]
        ]
        slots["platform"] = set.intersection(*compatible_platforms)
        slot_modes["platform"] = (
            "filterable" if has_filter_field["platform"] else "fixed"
        )
    return {
        "card": card,
        "domains": domains,
        "slots": slots,
        "slot_modes": slot_modes,
        "text": text,
    }
