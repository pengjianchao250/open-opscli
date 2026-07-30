#!/usr/bin/env python3
"""在当前账号授权卡片范围内选择数据集（带类型约束的 schema linking）。

选表按三级优先：
1. 显式标识 —— 查询中直接出现 dataset_alias 或英文 dataset_name；
2. 中文说明精确匹配 —— 查询中包含某数据集的完整中文说明；
3. 语义打分 —— 领域/槽位覆盖判断 + 词表打分，分差不足时要求澄清。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import field_semantics
import scoped_metadata_index
import typed_schema_linking as schema


# 选表打分常量：显式标识 > 中文说明 > 领域命中 > 文本命中；
# query_component（权限枚举组件）默认重罚，避免被当成业务数据集选中
EXPLICIT_ALIAS_SCORE = 100
EXPLICIT_NAME_SCORE = 90
EXPLICIT_DESCRIPTION_SCORE = 80
INTENT_PATTERN_SCORE = 40
DATASET_TEXT_SCORE = 15
FIELD_TEXT_SCORE = 8
DEFAULT_AD_REPORT_SCORE = 15
QUERY_COMPONENT_PENALTY = 50
# 前两名分差低于该阈值时不自动定表，转为向用户澄清
CLARIFY_SCORE_GAP = 8

CONTRACT = "planner_contract_v2"
MAX_CANDIDATES = 3
MAX_QUERY_CHARS = 4096
MAX_OUTPUT_BYTES = 6000
MAX_TEXT_LENGTH = schema.MAX_TEXT_LENGTH
FIELD_TERM_KEYS = schema.FIELD_TERM_KEYS
ALIAS_REFERENCE_RE = schema.ALIAS_REFERENCE_RE
DEFAULT_DATASET_DISPLAY_NAME = "即时综合数据集"
TECHNICAL_DATASET_NAME_RE = re.compile(
    r"(?<![a-z0-9_])(?:custom_[a-z0-9_]+|[a-z0-9][a-z0-9_]*_set)(?![a-z0-9_])",
    re.IGNORECASE,
)
_normalize = schema.normalize
_term_matches = schema.term_matches
_validate_rules = schema.validate_rules
extract_query_semantics = schema.extract_query_semantics
_profile_card = schema.profile_card

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+", re.IGNORECASE)
IDENTIFIER_BOUNDARY = r"[a-z0-9_]"
QUERY_PREFIXES = ("请帮我", "帮我", "请", "查询", "查看", "分析", "统计", "查", "看", "按", "用")
QUERY_SUFFIXES = ("是否合理", "数据集", "看数据", "怎么样", "数据", "表现", "情况", "明细", "详细", "详情", "效果", "排行", "趋势", "复盘", "一下")
STOP_TOKENS = frozenset(
    {"and", "by", "data", "dataset", "for", "from", "please", "show", "the", "use", "using", "with"}
)
PERMISSION_ENUM_TERMS = (
    "可用枚举值",
    "枚举值",
    "可选值",
    "合法值",
    "允许值",
    "权限值",
    "enumerate",
    "enum",
)
DEFAULT_DATASET_REJECTION_TERMS = (
    "不使用即时综合数据集",
    "不要使用即时综合数据集",
    "不要用即时综合数据集",
    "不用即时综合数据集",
    "排除即时综合数据集",
)


def _identifier_in_query(query: str, identifier: str) -> bool:
    identifier = _normalize(identifier)
    if not identifier:
        return False
    return re.search(
        rf"(?<!{IDENTIFIER_BOUNDARY}){re.escape(identifier)}(?!{IDENTIFIER_BOUNDARY})",
        query,
        re.IGNORECASE,
    ) is not None


def _validate_string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid_cards:{label}_must_be_string_list")
    return value


def _validate_cards(cards: object) -> list[dict]:
    if not isinstance(cards, list) or not cards:
        raise ValueError("invalid_cards:authorized_cards_must_be_non_empty")
    aliases = set()
    names = set()
    validated = []
    for index, source in enumerate(cards):
        if not isinstance(source, dict):
            raise ValueError(f"invalid_cards:card_{index}_must_be_object")
        alias = source.get("dataset_alias")
        name = source.get("dataset_name")
        category = source.get("dataset_category")
        if (
            not isinstance(alias, str)
            or not alias.strip()
            or alias != alias.strip()
            or len(alias) > MAX_TEXT_LENGTH
        ):
            raise ValueError(f"invalid_cards:card_{index}_bad_alias")
        if (
            not isinstance(name, str)
            or not name.strip()
            or name != name.strip()
            or len(name) > MAX_TEXT_LENGTH
        ):
            raise ValueError(f"invalid_cards:card_{index}_bad_name")
        if category not in {"normal", "query_component"}:
            raise ValueError(f"invalid_cards:card_{index}_bad_category")
        for key in ("description", "remarks"):
            value = source.get(key, "")
            if not isinstance(value, str) or len(value) > MAX_QUERY_CHARS:
                raise ValueError(f"invalid_cards:card_{index}_bad_{key}")
        alias_key = alias.casefold()
        name_key = name.casefold()
        # 别名是唯一技术标识，重复即元数据损坏，必须硬失败；
        # 中文名称重复是真实业务场景（如 QA 账号存在两个同名「用户仪表盘分享明细」，
        # table_id 52/61 别名各异），不能因此拒绝整个账号的规划——
        # 显式点名该名称时会产生多候选，由 plan_query 的多候选分支自然进入澄清
        if alias_key in aliases:
            raise ValueError("invalid_cards:duplicate_identifier")
        aliases.add(alias_key)
        names.add(name_key)
        item = dict(source)
        for key in FIELD_TERM_KEYS:
            item[key] = _validate_string_list(source.get(key), f"card_{index}.{key}")
        validated.append(item)
    # 后置标记同名冲突卡片：仅作信息位供排错/披露，不改变选表打分
    name_counts: dict[str, int] = {}
    for item in validated:
        key = item["dataset_name"].casefold()
        name_counts[key] = name_counts.get(key, 0) + 1
    for item in validated:
        if name_counts[item["dataset_name"].casefold()] > 1:
            item["name_conflict"] = True
    return validated


def _explicit_candidates(query: str, profiles: list[dict]) -> list[dict]:
    matches = []
    for profile in profiles:
        card = profile["card"]
        alias_match = _identifier_in_query(query, card["dataset_alias"])
        name_match = _identifier_in_query(query, card["dataset_name"])
        if not alias_match and not name_match:
            continue
        matches.append(
            {
                "dataset_alias": card["dataset_alias"],
                "dataset_name": card["dataset_name"],
                "dataset_category": card["dataset_category"],
                "score": EXPLICIT_ALIAS_SCORE if alias_match else EXPLICIT_NAME_SCORE,
                "reasons": ["explicit_alias" if alias_match else "explicit_name"],
            }
        )
    return sorted(matches, key=lambda item: (-item["score"], item["dataset_alias"].casefold()))


def _permission_enum_requested(query: str) -> bool:
    return any(_term_matches(term, query) for term in PERMISSION_ENUM_TERMS)


def _description_candidates(query: str, profiles: list[dict]) -> list[dict]:
    """找出中文说明完整出现在查询中的数据集；嵌套命中只保留最长说明。"""
    occurrences = []
    for profile in profiles:
        card = profile["card"]
        description = _normalize(card.get("description"))
        if not description or description.isascii():
            continue
        occurrences.extend(
            (match.start(), match.end(), profile)
            for match in re.finditer(re.escape(description), query)
        )
    surviving_profiles = []
    seen_aliases = set()
    for start, end, profile in occurrences:
        if any(
            other_start <= start
            and end <= other_end
            and other_end - other_start > end - start
            for other_start, other_end, _other_profile in occurrences
        ):
            continue
        alias = profile["card"]["dataset_alias"]
        if alias not in seen_aliases:
            surviving_profiles.append(profile)
            seen_aliases.add(alias)
    matches = [
        {
            "dataset_alias": profile["card"]["dataset_alias"],
            "dataset_name": profile["card"]["dataset_name"],
            "dataset_category": profile["card"]["dataset_category"],
            "score": EXPLICIT_DESCRIPTION_SCORE,
            "reasons": ["explicit_chinese_description"],
        }
        for profile in surviving_profiles
    ]
    return sorted(matches, key=lambda item: item["dataset_alias"].casefold())


def _description_candidate_profiles(
    candidates: list[dict], profiles: list[dict]
) -> list[dict]:
    by_alias = {profile["card"]["dataset_alias"]: profile for profile in profiles}
    return [
        by_alias[candidate["dataset_alias"]]
        for candidate in candidates
        if candidate["dataset_alias"] in by_alias
    ]


def _semantic_query_without_candidate_identity(
    query: str,
    candidates: list[dict],
    profiles: list[dict],
) -> str:
    """遮蔽精确命中的数据集身份与完整字段标签，再抽取业务槽位。

    名称或字段中的 ``VC`` / ``Walmart`` 是身份文本，不等于用户额外提出
    平台筛选。只遮蔽完整片段，因此名称外另写的“只看 Walmart”仍会保留。
    """
    selected = _description_candidate_profiles(candidates, profiles)
    terms = []
    for profile in selected:
        card = profile["card"]
        terms.extend(
            str(card.get(key, ""))
            for key in ("dataset_alias", "dataset_name", "description")
        )
        terms.extend(
            str(term)
            for key in FIELD_TERM_KEYS
            for term in card.get(key, [])
        )
    masked = query
    for term in sorted({_normalize(item) for item in terms if item}, key=len, reverse=True):
        if term:
            masked = masked.replace(term, " " * len(term))
    return masked


def _description_candidates_cover_constraints(
    candidates: list[dict],
    profiles: list[dict],
    domains: set[str],
    slots: dict[str, set[str]],
    rules: dict,
) -> bool:
    return all(
        domains.issubset(profile["domains"])
        and all(
            _slot_is_covered(profile, name, values, rules)
            for name, values in slots.items()
            if name != "platform"
        )
        for profile in _description_candidate_profiles(candidates, profiles)
    )


def _has_chinese_metric_evidence(query: str, profile: dict) -> bool:
    return any(
        len(_normalize(term)) >= 2
        and not _normalize(term).isascii()
        and _term_matches(term, query)
        for term in profile["card"]["metric_terms"]
    )


def _default_ad_report(
    profile: dict, slots: dict[str, set[str]], query: str
) -> bool:
    """判断是否命中"广告类型已指定但粒度未指定"的默认报表：
    仅当请求类型与中文默认广告数据集完全一致且命中真实中文指标时成立。"""
    description = _normalize(profile["card"].get("description"))
    return (
        "ad_type" in slots
        and "grain" not in slots
        and profile["slots"]["ad_type"] == slots["ad_type"]
        and description.endswith("广告数据集")
        and _has_chinese_metric_evidence(query, profile)
    )


def _query_tokens(query: str, matched_terms: set[str]) -> list[str]:
    """提取查询残差词：剥掉常见前后缀、停用词和已被规则命中的词。

    残差词用于卡片文本与字段词表的兜底匹配，避免规则词被重复计分。
    """
    tokens = []
    seen = set()
    for raw in TOKEN_RE.findall(_normalize(query)):
        token = raw
        for prefix in QUERY_PREFIXES:
            if token.startswith(prefix):
                token = token[len(prefix) :]
                break
        for suffix in QUERY_SUFFIXES:
            if token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        # 连续中文不能因包含一个命中词就整段删除：“查即时销售额”扣除
        # “销售额”后仍应保留“即时”，作为即时综合表的独立证据。
        residuals = [token]
        if not token.isascii():
            remainder = token
            for term in sorted({_normalize(item) for item in matched_terms}, key=len, reverse=True):
                if term and not term.isascii():
                    remainder = remainder.replace(term, " ")
            residuals = remainder.split()
        for residual in residuals:
            if (
                len(residual) < 2
                or residual.isdigit()
                or residual in STOP_TOKENS
                or residual in seen
                or (
                    residual.isascii()
                    and any(residual == _normalize(term) for term in matched_terms)
                )
            ):
                continue
            seen.add(residual)
            tokens.append(residual)
    return tokens


def _expanded_values(name: str, values: set[str], rules: dict) -> set[str]:
    if name != "platform":
        return values
    members = rules["platform_scope"]["members"]
    return {member for value in values for member in members.get(value, [value])}


def _slot_is_covered(profile: dict, name: str, requested: set[str], rules: dict) -> bool:
    """判断数据集画像是否覆盖请求的槽位取值。

    只要求数据集覆盖用户请求（requested ⊆ supported）。曾额外要求固定口径
    必须与请求完全相等，导致覆盖粒度更广的数据集被拒——实测「搜索词的点击份额」
    因此零候选，而「搜索词和关键词的点击份额」反而能命中三个正确数据集，
    形成「说得越具体候选越少」的反常行为。按召回优先原则放开，
    多出的粒度改由 _extra_slot_terms 交给合同强制披露。
    """
    raw_supported = profile["slots"][name]
    mode = profile["slot_modes"][name]
    if mode in {"unsupported", "unknown"} or not raw_supported:
        return False
    supported = _expanded_values(name, raw_supported, rules)
    requested = _expanded_values(name, requested, rules)
    return requested.issubset(supported)


def _extra_slot_terms(profile: dict, slots: dict, rules: dict) -> dict:
    """列出数据集比用户请求多覆盖的固定槽位取值，供强制披露。

    放开覆盖判定后，选中的数据集口径可能比用户要的更宽（如用户要搜索词级，
    数据集是关键词×搜索词级；用户只要 SP，数据集是 SP+SD+SB 合计），
    直接汇总会与用户预期的口径不一致。
    风险不靠拒绝候选规避，而是如实告知——这是「放开 + 强制披露」的后半段。

    只收 slot_modes == "fixed" 的槽位：filterable 表示数据集带该槽位的筛选
    字段（rules["filter_fields"] 只有 platform / ad_type 两项），多余取值能被
    筛掉，不构成口径风险；grain 在 filter_fields 里没有对应项，永远不会是
    filterable。这条不变量是下游披露文案分语义的唯一依据，改动 profile_card
    的 slot_modes 推导时必须同步复核 query_plan._slot_surplus_disclosure_zh。

    返回值按槽位名索引（技术名，仅用于下游分语义，不展示给用户），
    值里只放中文标签——披露句必须是纯中文，不能回落到内部枚举名。
    """
    extra: dict = {}
    for name, requested in (slots or {}).items():
        if name not in profile.get("slots", {}):
            continue
        if profile.get("slot_modes", {}).get(name) != "fixed":
            continue
        supported = _expanded_values(name, profile["slots"][name], rules)
        surplus = sorted(supported.difference(_expanded_values(name, requested, rules)))
        if surplus:
            extra[name] = {
                "slot_label_zh": schema.slot_label(name),
                # 请求侧用用户原本说出的取值（不做平台成员展开），
                # 披露句里的「不能当作纯 X」才与用户的问法对得上
                "requested_zh": [
                    schema.slot_value_label(rules, name, value)
                    for value in sorted(requested)
                ],
                "surplus_zh": [
                    schema.slot_value_label(rules, name, value) for value in surplus
                ],
            }
    return extra


def _attach_slot_coverage(
    candidates: list[dict],
    profiles: list[dict],
    slots: dict[str, set[str]],
    rules: dict,
) -> list[dict]:
    """为已构造的候选补齐固定槽位多余覆盖信息（强制披露的唯一数据来源）。

    为什么要后置补齐：显式标识命中与中文说明命中这两条路径在构造候选字典时
    还没抽取槽位——槽位要先遮蔽数据集身份文本才能算准，只能等算完再回填。
    漏补的后果是 query_plan 取到空 grain_coverage → model_view 与
    answer_contract 两处披露一起静默消失，形成「用户报出表名反而丢掉安全披露」
    的反常行为（说得越具体反而越危险）。
    """
    by_alias = {profile["card"]["dataset_alias"]: profile for profile in profiles}
    for candidate in candidates:
        profile = by_alias.get(candidate.get("dataset_alias"))
        if profile is None:
            continue
        candidate["grain_coverage"] = _extra_slot_terms(profile, slots, rules)
    return candidates


def _covers(profile: dict, domains: set[str], slots: dict[str, set[str]], rules: dict) -> bool:
    if not domains.issubset(profile["domains"]):
        return False
    return all(
        _slot_is_covered(profile, name, values, rules) for name, values in slots.items()
    )


def _is_default_dataset_profile(profile: dict) -> bool:
    target = _normalize(DEFAULT_DATASET_DISPLAY_NAME)
    card = profile["card"]
    return card["dataset_category"] == "normal" and target in {
        _normalize(card.get("dataset_name")),
        _normalize(card.get("description")),
    }


def _default_dataset_candidate(
    profiles: list[dict],
    domains: set[str],
    slots: dict[str, set[str]],
    metrics: list[str],
    rules: dict,
) -> dict | None:
    """返回唯一、已授权且覆盖当前明确语义的即时综合数据集候选。"""
    matches = [profile for profile in profiles if _is_default_dataset_profile(profile)]
    if len(matches) != 1:
        return None

    profile = matches[0]
    card = profile["card"]
    # 即时综合的说明通常只写“即时综合数据集”，真实覆盖范围体现在字段卡片。
    # 默认选表仍须逐领域找到字段证据，不能仅因名称是默认表就放宽。
    card_field_terms = {
        _normalize(term)
        for key in FIELD_TERM_KEYS
        for term in card.get(key, [])
    }
    covered_domains = set(profile["domains"])
    for domain in domains - covered_domains:
        record = rules["domains"][domain]
        patterns = [
            _normalize(item)
            for key in ("terms", "description_patterns")
            for item in record[key]
        ]
        if any(
            pattern and any(pattern in field_term for field_term in card_field_terms)
            for pattern in patterns
        ):
            covered_domains.add(domain)
    if not domains.issubset(covered_domains):
        return None

    # 平台可由查询组件承接，实际可用值仍由 query_plan 权限枚举收敛。
    platform_filter_terms = set(rules["filter_fields"]["platform"])
    card_select_terms = {_normalize(item) for item in card["select_column_terms"]}
    for name, values in slots.items():
        if _slot_is_covered(profile, name, values, rules):
            continue
        if name == "platform" and card_select_terms.intersection(platform_filter_terms):
            continue
        return None

    if any(
        not field_semantics.metric_term_is_covered(metric, card["metric_terms"])
        for metric in metrics
    ):
        return None

    return {
        "dataset_alias": card["dataset_alias"],
        "dataset_name": card["dataset_name"],
        "dataset_category": card["dataset_category"],
        "score": EXPLICIT_DESCRIPTION_SCORE,
        "reasons": ["default_instant_comprehensive"],
        # 默认表同样受放开覆盖判定影响（如即时综合表覆盖多个粒度），
        # 少了这一键会让默认推荐路径丢掉强制披露
        "grain_coverage": _extra_slot_terms(profile, slots, rules),
        "_semantic_rank": 0,
    }


def _with_default_dataset_recommendation(result: dict, candidate: dict | None) -> dict:
    """把默认候选标为必须确认的推荐，而不是可直接执行的静默选表。"""
    if candidate is None:
        return result
    recommended = _result(
        "candidate_ready",
        str(result.get("intent", "typed_selection")),
        dict(result.get("slots") or {}),
        [candidate],
        None,
    )
    recommended["default_dataset_recommendation"] = {
        "kind": "instant_comprehensive",
        "confirmation_required": True,
    }
    return recommended


def _slot_extra_count(
    profile: dict,
    slots: dict[str, set[str]],
    rules: dict,
    names: set[str],
) -> int:
    return sum(
        len(
            _expanded_values(name, profile["slots"][name], rules)
            - _expanded_values(name, values, rules)
        )
        for name, values in slots.items()
        if name in names
    )


def _unrequested_specificity(profile: dict, slots: dict[str, set[str]]) -> int:
    return sum(
        len(values)
        for name, values in profile["slots"].items()
        if name not in slots
        and not (
            name == "platform"
            and profile["slot_modes"][name] == "filterable"
            and len(values) > 1
        )
    )


def _unrequested_business_specificity(
    profile: dict, slots: dict[str, set[str]]
) -> int:
    return sum(
        len(profile["slots"][name])
        for name in ("ad_type", "grain")
        if name not in slots
    )


def _semantic_rank(
    profile: dict, domains: set[str], slots: dict[str, set[str]], rules: dict
) -> tuple:
    """语义排序键（越小越优）：偏好口径最贴合、无多余业务特异性的数据集。"""
    filter_penalty = sum(
        len(values)
        for name, values in slots.items()
        if profile["slot_modes"][name] == "filterable"
    )
    return (
        _slot_extra_count(profile, slots, rules, {"ad_type", "grain"}),
        _unrequested_specificity(profile, slots),
        _slot_extra_count(profile, slots, rules, {"platform"}),
        filter_penalty,
        len(profile["domains"] - domains),
    )


def _semantics_are_compatible(slots: dict[str, set[str]], rules: dict) -> bool:
    platforms = _expanded_values("platform", slots.get("platform", set()), rules)
    if not platforms:
        return True
    allowed = rules["compatibility"]["ad_type_platform"]
    return all(platforms.issubset(allowed[ad_type]) for ad_type in slots.get("ad_type", set()))


def _matching_fragments(fragments: list[str], text: str) -> list[str]:
    normalized = _normalize(text)
    return [fragment for fragment in fragments if _term_matches(fragment, normalized)]


def _score_profile(
    profile: dict,
    domains: set[str],
    slots: dict[str, set[str]],
    residual_terms: list[str],
    rules: dict,
    query: str,
) -> dict:
    """对单张卡片打分并记录理由（领域命中、槽位支持、残差词文本/字段命中）。"""
    card = profile["card"]
    score = INTENT_PATTERN_SCORE * len(domains & profile["domains"])
    reasons = [f"domain:{name}" for name in sorted(domains & profile["domains"])]
    for slot_name, requested in slots.items():
        supported = profile["slots"][slot_name]
        for value in sorted(requested):
            value_is_supported = _expanded_values(slot_name, {value}, rules).issubset(
                _expanded_values(slot_name, supported, rules)
            )
            if supported and value_is_supported:
                if profile["slot_modes"][slot_name] == "filterable":
                    score += FIELD_TEXT_SCORE
                    reasons.append(f"filter:{slot_name}:{value}")
                else:
                    score += DATASET_TEXT_SCORE
                    reasons.append(f"{slot_name}:{value}")

    text_matches = _matching_fragments(residual_terms, profile["text"])[:2]
    score += DATASET_TEXT_SCORE * len(text_matches)
    reasons.extend(f"text:{term[:48]}" for term in text_matches)
    field_text = " ".join(item for key in FIELD_TERM_KEYS for item in card[key])
    field_matches = _matching_fragments(residual_terms, field_text)[:2]
    score += FIELD_TEXT_SCORE * len(field_matches)
    reasons.extend(f"field:{term[:48]}" for term in field_matches)
    if card["dataset_category"] == "query_component":
        score -= QUERY_COMPONENT_PENALTY
        reasons.append("component_penalty")
    if _default_ad_report(profile, slots, query):
        score += DEFAULT_AD_REPORT_SCORE
        reasons.append("default_ad_report")

    return {
        "dataset_alias": card["dataset_alias"],
        "dataset_name": card["dataset_name"],
        "dataset_category": card["dataset_category"],
        "score": score,
        "reasons": reasons,
        "grain_coverage": _extra_slot_terms(profile, slots, rules),
        "_semantic_rank": _semantic_rank(profile, domains, slots, rules),
    }


def _result(
    status: str,
    intent: str,
    slots: dict[str, list[str]],
    candidates: list[dict],
    missing: str | None,
) -> dict:
    """组装 planner_contract_v2 输出，剥离内部键并守卫输出体积。"""
    public_candidates = [
        {key: value for key, value in candidate.items() if not key.startswith("_")}
        for candidate in candidates[:MAX_CANDIDATES]
    ]
    result = {
        "contract": CONTRACT,
        "planner_status": status,
        "query_execution_allowed": False,
        "intent": intent,
        "slots": slots,
        "dataset_candidates": public_candidates,
        "missing_information": [missing] if missing else [],
        "next_action": (
            "get_dataset_guidance"
            if status == "candidate_ready"
            else ("clarify_query" if missing == "query" else "clarify_dataset")
        ),
    }
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_OUTPUT_BYTES:
        raise ValueError("planner_output_too_large")
    return result


def plan_query(
    query: str,
    cards: list[dict],
    rules: dict,
    top_n: int = 3,
    *,
    recommend_default_dataset: bool = True,
) -> dict:
    """在当前授权卡片范围内产出紧凑的选表计划。

    返回 planner_contract_v2 合同：candidate_ready（已定表）或
    clarify_required（需要澄清），候选最多 MAX_CANDIDATES 个。
    选表只依据当前账号卡片，绝不引入卡片之外的数据集。
    """
    if not isinstance(query, str):
        raise TypeError("query_must_be_string")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query_too_long")
    if type(top_n) is not int or top_n < 1:
        raise ValueError("invalid_top_n")
    candidate_limit = min(top_n, MAX_CANDIDATES)
    validated_rules = _validate_rules(rules)
    validated_cards = _validate_cards(cards)
    profiles = [_profile_card(card, validated_rules) for card in validated_cards]

    if not query.strip():
        return _result("clarify_required", "unknown", {}, [], "query")
    normalized_query = _normalize(query)
    # 阶段 0：查询中出现了不在授权范围内的技术标识时直接澄清，禁止猜测映射
    authorized_aliases = {card["dataset_alias"].casefold() for card in validated_cards}
    authorized_names = {card["dataset_name"].casefold() for card in validated_cards}
    referenced_aliases = set(ALIAS_REFERENCE_RE.findall(normalized_query))
    referenced_names = set(TECHNICAL_DATASET_NAME_RE.findall(normalized_query))
    if referenced_aliases - authorized_aliases or referenced_names - authorized_names:
        return _result(
            "clarify_required",
            "direct_dataset",
            {},
            [],
            "dataset_not_available_in_current_scope",
        )

    # 阶段 1：显式标识匹配（alias / 英文名），唯一命中即定表
    explicit = _explicit_candidates(normalized_query, profiles)
    if explicit:
        semantic_query = _semantic_query_without_candidate_identity(
            normalized_query, explicit, profiles
        )
        semantics = extract_query_semantics(semantic_query, validated_rules)
        domains = set(semantics["domains"])
        slots = {name: set(values) for name, values in semantics["slots"].items()}
        _attach_slot_coverage(explicit, profiles, slots, validated_rules)
        top = explicit[0]
        component_blocked = top["dataset_category"] == "query_component" and not _permission_enum_requested(query)
        if len(explicit) > 1 or component_blocked:
            return _result(
                "clarify_required",
                "direct_dataset",
                semantics["slots"],
                explicit[:candidate_limit],
                "business_dataset",
            )
        if not _description_candidates_cover_constraints(
            explicit, profiles, domains, slots, validated_rules
        ):
            return _result(
                "clarify_required",
                "direct_dataset",
                semantics["slots"],
                explicit[:candidate_limit],
                "dataset_constraints",
            )
        return _result(
            "candidate_ready",
            "direct_dataset",
            semantics["slots"],
            explicit[:candidate_limit],
            None,
        )

    # 阶段 2：中文说明精确匹配，命中多个或平台约束不覆盖时澄清
    default_dataset_rejected = any(
        term in normalized_query for term in DEFAULT_DATASET_REJECTION_TERMS
    )
    description_matches = _description_candidates(normalized_query, profiles)
    if default_dataset_rejected:
        default_aliases = {
            profile["card"]["dataset_alias"]
            for profile in profiles
            if _is_default_dataset_profile(profile)
        }
        description_matches = [
            candidate
            for candidate in description_matches
            if candidate.get("dataset_alias") not in default_aliases
        ]
    if description_matches:
        semantic_query = _semantic_query_without_candidate_identity(
            normalized_query, description_matches, profiles
        )
        semantics = extract_query_semantics(semantic_query, validated_rules)
        domains = set(semantics["domains"])
        slots = {name: set(values) for name, values in semantics["slots"].items()}
        _attach_slot_coverage(description_matches, profiles, slots, validated_rules)
        top = description_matches[0]
        if len(description_matches) > 1:
            return _result(
                "clarify_required",
                "direct_description",
                semantics["slots"],
                description_matches[:candidate_limit],
                "dataset_selection",
            )
        if not _description_candidates_cover_constraints(
            description_matches, profiles, domains, slots, validated_rules
        ):
            return _result(
                "clarify_required",
                "direct_description",
                semantics["slots"],
                description_matches[:candidate_limit],
                "dataset_constraints",
            )
        component_blocked = top["dataset_category"] == "query_component" and not _permission_enum_requested(query)
        if component_blocked:
            return _result(
                "clarify_required",
                "direct_description",
                semantics["slots"],
                description_matches[:candidate_limit],
                "business_dataset",
            )
        return _result(
            "candidate_ready",
            "direct_description",
            semantics["slots"],
            description_matches[:candidate_limit],
            None,
        )

    semantics = extract_query_semantics(query, validated_rules)
    domains = set(semantics["domains"])
    slots = {name: set(values) for name, values in semantics["slots"].items()}
    default_candidate = None
    if recommend_default_dataset and not default_dataset_rejected:
        default_candidate = _default_dataset_candidate(
            profiles,
            domains,
            slots,
            list(semantics["metrics"]),
            validated_rules,
        )

    # 阶段 3：语义覆盖判断 + 打分。证据不足（无领域无槽位、只有平台词等）先澄清
    intent = next(iter(domains)) if len(domains) == 1 else ("mixed" if domains else "typed_selection")
    has_metric = bool(semantics["metrics"])

    matched_terms = {
        term
        for domain in domains
        for term in validated_rules["domains"][domain]["terms"]
        if _term_matches(term, query)
    }
    matched_terms.update(str(term) for term in semantics["metrics"])
    for slot_name, values in slots.items():
        for value in values:
            matched_terms.update(
                term
                for term in validated_rules["slots"][slot_name][value]["terms"]
                if _term_matches(term, query)
            )
    residual_terms = _query_tokens(query, matched_terms)
    if not domains and not slots:
        residual_scored = [
            _score_profile(profile, set(), {}, residual_terms, validated_rules, query)
            for profile in profiles
            if profile["card"]["dataset_category"] == "normal"
        ]
        residual_scored.sort(
            key=lambda item: (-item["score"], item["dataset_alias"].casefold())
        )
        if residual_scored and residual_scored[0]["score"] > 0:
            gap = (
                residual_scored[0]["score"] - residual_scored[1]["score"]
                if len(residual_scored) > 1
                else residual_scored[0]["score"]
            )
            if gap >= CLARIFY_SCORE_GAP:
                return _with_default_dataset_recommendation(
                    _result(
                        "candidate_ready",
                        intent,
                        semantics["slots"],
                        residual_scored[:candidate_limit],
                        None,
                    ),
                    default_candidate,
                )
            return _with_default_dataset_recommendation(
                _result(
                    "clarify_required",
                    intent,
                    semantics["slots"],
                    residual_scored[:candidate_limit],
                    "dataset_selection",
                ),
                default_candidate,
            )
        return _with_default_dataset_recommendation(
            _result("clarify_required", intent, semantics["slots"], [], "business_scope"),
            default_candidate,
        )
    if not has_metric and not domains and set(slots) == {"platform"}:
        return _with_default_dataset_recommendation(
            _result("clarify_required", intent, semantics["slots"], [], "business_scope"),
            default_candidate,
        )
    if not has_metric and not slots and len(domains) <= 1:
        return _with_default_dataset_recommendation(
            _result("clarify_required", intent, semantics["slots"], [], "business_scope"),
            default_candidate,
        )
    if not _semantics_are_compatible(slots, validated_rules):
        return _result("clarify_required", intent, semantics["slots"], [], "incompatible_scope")
    eligible = [
        profile
        for profile in profiles
        if profile["card"]["dataset_category"] == "normal"
        and _covers(profile, domains, slots, validated_rules)
    ]
    if not eligible:
        return _with_default_dataset_recommendation(
            _result("clarify_required", intent, semantics["slots"], [], "dataset_constraints"),
            default_candidate,
        )
    if not set(slots).intersection({"ad_type", "grain"}) and all(
        _unrequested_business_specificity(profile, slots) for profile in eligible
    ):
        return _with_default_dataset_recommendation(
            _result("clarify_required", intent, semantics["slots"], [], "dataset_constraints"),
            default_candidate,
        )

    scored = [
        _score_profile(
            profile, domains, slots, residual_terms, validated_rules, query
        )
        for profile in eligible
    ]
    best_rank = min(candidate["_semantic_rank"] for candidate in scored)
    contenders = [candidate for candidate in scored if candidate["_semantic_rank"] == best_rank]
    contenders.sort(key=lambda item: (-item["score"], item["dataset_alias"].casefold()))

    if len(contenders) == 1:
        return _with_default_dataset_recommendation(
            _result("candidate_ready", intent, semantics["slots"], contenders, None),
            default_candidate,
        )
    gap = contenders[0]["score"] - contenders[1]["score"]
    status = "candidate_ready" if gap >= CLARIFY_SCORE_GAP else "clarify_required"
    return _with_default_dataset_recommendation(
        _result(
            status,
            intent,
            semantics["slots"],
            contenders[:candidate_limit],
            None if status == "candidate_ready" else "dataset_selection",
        ),
        default_candidate,
    )


def load_authorized_cards(data_dir: Path) -> list[dict]:
    """从当前账号元数据 CSV 构建并校验选表决策卡片。

    卡片在进程内即时构建（不落盘），构建后再过一遍卡片结构校验，
    保证进入规划器的数据满足选表所需的完整约束。
    """
    return _validate_cards(scoped_metadata_index.build_cards(Path(data_dir)))
