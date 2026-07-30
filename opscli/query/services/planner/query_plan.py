#!/usr/bin/env python3
"""查询规划器：一次调用产出选表、字段与权限规划结果。

流程：版本检查 → 规则校验 → 构建授权卡片 → 选表 → 字段指导
→ 平台权限枚举解析 → 投影为模型可见规划器（model contract）。

输出两层规划器：
- 内部规划器 query_plan_contract_v1（--output-mode internal，仅维护者排错用）；
- 模型规划器 query_plan_model_contract_v2（默认输出，Agent 只消费这一层）。
"""

from __future__ import annotations

import json
import re
import unicodedata
from importlib.resources import files
from typing import Any, Iterable, Sequence

from opscli.query.services.planner import agent_query_planner as planner
from opscli.query.services.planner import dataset_guidance
from opscli.query.services.planner import plan_integrity
from opscli.query.services.planner import time_scope
from opscli.query.services.planner import typed_schema_linking as schema
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


INTERNAL_CONTRACT = "query_plan_contract_v1"
MODEL_CONTRACT = "query_plan_model_contract_v2"
MAX_OUTPUT_BYTES = 24000


def _load_rules_resource() -> dict:
    """从内核静态资源读取领域意图规则（intent_rules.json）。

    内核化后规则不再从 data/ 目录读取，改为随包分发的静态资源，
    经 importlib.resources 定位，避免依赖运行时工作目录。
    """
    raw = (
        files("opscli.query.services.planner.resources") / "intent_rules.json"
    ).read_text("utf-8")
    return json.loads(raw)

# 澄清原因代码 → 面向用户的中文澄清话术
CLARIFICATION_MESSAGES = {
    # 文案须说明「缺什么 + 下一步做什么」：缺配文案的 code 会退化为兜底提示，
    # 调用方无从判断该补哪一项，只能反复改写请求盲重试（生产实测的高频形态）。
    "dataset_constraints": "需要先澄清并确认满足所需业务范围、维度和指标的数据集。",
    "query": "查询内容为空，请补充要查询的业务数据、时间范围与筛选条件。",
    "business_scope": "未能识别出明确的业务范围与指标，请补充要查的数据主题"
                      "（如销售、广告、库存、物流）以及具体指标名称。",
    "dataset_selection": "多个数据集与当前请求同等匹配，请在给出的候选数据集中"
                         "确认使用哪一个（可直接在请求中写明数据集名称）。",
    "business_dataset": "当前命中的是权限枚举组件或多个同名数据集，无法唯一确定"
                        "业务数据集，请确认要使用的具体业务数据集。",
    "dataset_not_available_in_current_scope": "请求中提到的数据集标识不在当前账号的"
                                              "授权范围内，请改用当前账号已授权的数据集。",
    "incompatible_scope": "请求中的广告类型与平台组合互不兼容，请确认要查询的"
                          "广告类型或平台范围。",
    "dataset_identity": "需要先确认要查询的数据集。",
    "platform_scope": "需要先确认平台范围。",
    "ad_type": "需要先确认广告类型。",
    "grain": "需要先确认查询粒度。",
    "field_identity": "点名字段对应多个同名物理字段，当前中文标签无法唯一绑定。",
    "time_scope_confirmation": "未识别到明确时间范围，需要确认是否使用默认近30天。",
    "recommended_fields_confirmation": "用户未点名完整字段，需要确认是否采用系统推荐字段。",
    "default_dataset_confirmation": "未明确指定数据集，建议使用已授权且兼容的即时综合数据集，需要确认是否采用。",
}
# 披露代码 → 最终回答中必须覆盖的中文披露内容
DISCLOSURE_MESSAGES = {
    "permission_enum_required": "正式查询前需要按当前账号权限枚举确认平台筛选值。",
    "dataset_confirmation_required": "需要先确认满足本次业务范围和字段要求的数据集。",
    "field_confirmation_required": "需要先确认所需维度和指标。",
    "blocked_reason_required": "需要说明当前查询被阻断的原因。",
}
# 最终回答中禁止出现的输出形式
FORBIDDEN_OUTPUT_MESSAGES = [
    "不得向用户展示英文数据集标识或内部技术标识。",
    "不得把内部技术标识作为业务判断理由。",
    "未完成当前账号权限枚举校验时，不得声称正式平台筛选范围已确定。",
    "筛选组件存在唯一精确或规范化等值命中时，不得把仅因名称包含该文本的其他枚举成员一并查询。",
    "不得自行心算、猜测或替换相对时间及年份；只能使用规划器由 Python 生成的绝对日期窗口。",
]

# 元数据刷新命令原文：blocked 规划器与错误指引统一引用，避免 Agent 需要翻参考文档才能自救
METADATA_UPGRADE_COMMAND = "opscli skills upgrade ops-dataset-query"

# 平台语义成员内部枚举名 → 用户可见中文标签（model_view 只允许中文，
# 内部枚举名保留在 execution_ref.platform_semantic_keys 供构造引用）
PLATFORM_MEMBER_LABELS = {
    "amazon_sc": "亚马逊SC",
    "amazon_vc": "亚马逊VC",
}

# 选表候选 reasons 前缀 → 中文短语（澄清话术展示用）
CANDIDATE_REASON_LABELS = [
    ("default_instant_comprehensive", "未指定数据集时的兼容优先推荐"),
    ("explicit_alias", "技术标识精确命中"),
    ("explicit_name", "数据集英文名精确命中"),
    ("explicit_chinese_description", "中文名称命中"),
    ("domain:", "业务域相关"),
    ("filter:", "筛选条件相关"),
]

# 推荐字段（无点名字段时的兜底提议）上限
MAX_RECOMMENDED_FIELDS = 3
# 澄清候选卡片上限
MAX_CANDIDATE_CARDS = 3
# 筛选组件引用上限（execution_ref.filter_components）
MAX_FILTER_COMPONENTS = 6
# 普通筛选组件枚举值的统一消歧合同。部门数字允许阿拉伯数字与中文数字等价，
# 但等价后仍必须完整相等，不能把“九部”扩展为“项目九部”。
FILTER_VALUE_MATCH_POLICY = {
    "strategy": "exact_normalized_then_clarify",
    "normalizations": [
        "NFKC",
        "trim",
        "casefold",
        "department_arabic_chinese_numeral_equivalence",
    ],
    "exact_match_is_exclusive": True,
    "exact_match_confirmation_required": False,
    "substring_match_allowed": False,
    "no_exact_match_action": "clarify_required",
    "rule_zh": (
        "先对用户筛选值与当前账号组件枚举原值做规范化完整等值比较；"
        "部门名称额外允许阿拉伯数字与中文数字等价。唯一等值命中时只使用该枚举原值并直接执行，"
        "不得再次向用户确认，也不得加入仅包含请求文本的其他成员；无唯一等值命中时必须让用户澄清。"
        "例如“9部”只匹配“九部”，不匹配“项目九部”；"
        "“范泰克”不匹配“范泰克体系外”。"
    ),
}

_DEPARTMENT_NUMBER_RE = re.compile(r"(?:项目)?[零〇一二三四五六七八九十百\d]+部")
_DEPARTMENT_LABEL_RE = re.compile(
    r"部门\s*(?:为|是|=|：|:)?\s*([\u4e00-\u9fffA-Za-z0-9_-]{2,30})"
)
_DEPARTMENT_ANALYSIS_RE = re.compile(
    r"(?:分析|查询|获取|查看)\s*([\u4e00-\u9fffA-Za-z0-9_-]{2,30}?)的(?:数据|情况)"
)
_CHINESE_DIGITS = {
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}

# 图表 UUID 既可能是标准 UUID，也可能是平台生成的短标识。只有请求中明确出现
# “图表/chart”语义时才启用该路由，避免把工单、任务等其他 UUID 误判为图表。
CHART_REFERENCE_PATTERN = re.compile(
    r"(?:图表|chart)\s*(?:uuid|id|编号)?\s*(?:为|是|[:：=#])?\s*"
    r"([A-Za-z0-9][A-Za-z0-9_-]{5,127})",
    re.IGNORECASE,
)
STANDARD_UUID_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f])"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"(?![0-9A-Fa-f])"
)


def _deduplicate(values: Iterable[str]) -> list[str]:
    """按出现顺序去重并剔除空值。"""
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize(value: object) -> str:
    """NFKC 归一化 + casefold + 去首尾空白，用于中文标签匹配。"""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _normalize_enum(value: str) -> str:
    """枚举值归一化：额外去除全部内部空白（"Amazon SC" 与 "amazonsc" 视为等价）。"""
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalize_department_value(value: str) -> str:
    """部门值规范化：只做空白/NFKC/大小写与部门数字等价，不做子串扩展。"""
    normalized = _normalize_enum(value)
    match = re.fullmatch(r"(项目)?([零〇一二三四五六七八九十百\d]+)部", normalized)
    if not match:
        return normalized
    prefix, number = match.groups()
    if number in _CHINESE_DIGITS:
        number = _CHINESE_DIGITS[number]
    elif number == "十":
        number = "10"
    elif len(number) == 2 and number.startswith("十") and number[1] in _CHINESE_DIGITS:
        number = "1" + _CHINESE_DIGITS[number[1]]
    elif len(number) == 2 and number.endswith("十") and number[0] in _CHINESE_DIGITS:
        number = _CHINESE_DIGITS[number[0]] + "0"
    return f"{prefix or ''}{number}部"


def _extract_requested_department_value(query: str) -> str:
    """从明确部门表达或“分析某组织的数据”中提取单个部门筛选值。"""
    number_match = _DEPARTMENT_NUMBER_RE.search(query)
    if number_match:
        return number_match.group(0)
    label_match = _DEPARTMENT_LABEL_RE.search(query)
    if label_match:
        return label_match.group(1)
    analysis_match = _DEPARTMENT_ANALYSIS_RE.search(query)
    if not analysis_match:
        return ""
    candidate = analysis_match.group(1)
    if re.fullmatch(r"(?:本|上|下)?(?:月|周|季度|年)|近\d+(?:天|日)", candidate):
        return ""
    return candidate


def _extract_chart_uuids(query: str) -> list[str]:
    """从显式图表语义中提取 UUID，保持原文顺序并去重。"""
    normalized = unicodedata.normalize("NFKC", query)
    has_chart_intent = "图表" in normalized or "chart" in normalized.casefold()
    if not has_chart_intent:
        return []

    candidates = [match.group(1) for match in CHART_REFERENCE_PATTERN.finditer(normalized)]
    # 标准 UUID 允许出现在“图表的数据，UUID 为 xxx”这类非相邻表达中。
    candidates.extend(match.group(0) for match in STANDARD_UUID_PATTERN.finditer(normalized))
    return _deduplicate(candidates)


def _chart_action(query: str) -> str:
    """根据用户原文选择图表查询动作；未点名执行时默认只取结构。"""
    normalized = unicodedata.normalize("NFKC", query).casefold()
    if "chart-doc" in normalized or any(
        marker in normalized for marker in ("api文档", "调用文档", "查询文档")
    ):
        return "document"
    if "dry-run" in normalized or "dry run" in normalized or any(
        marker in normalized for marker in ("生成sql", "只生成sql", "仅生成sql")
    ):
        return "dry_run"
    if any(
        marker in normalized
        for marker in ("查询结构", "获取结构", "只看结构", "仅看结构", "不执行")
    ):
        return "structure"
    if any(
        marker in normalized
        for marker in ("数据", "结果", "执行", "分析", "导出", "落盘", "保存")
    ):
        return "run"
    return "structure"


def _build_chart_query_contract(query: str, chart_uuids: Sequence[str]) -> dict:
    """构建图表 UUID 专用模型合同，不依赖本地数据集元数据。"""
    base_model_view = {
        "dataset_name_zh": "图表保存查询",
        "dimensions": [],
        "metrics": [],
        "platform_semantic_members": [],
        "platform_filter_state": "not_requested",
        "clarification_reason_codes": [],
        "clarification_messages_zh": [],
        "next_action": "run_chart_query",
    }
    execution_ref: dict[str, Any] = {"user_visible": False}

    if len(chart_uuids) != 1:
        base_model_view["clarification_reason_codes"] = ["chart_uuid_identity"]
        base_model_view["clarification_messages_zh"] = [
            "检测到多个图表 UUID，需要确认本次只查询其中一个。"
        ]
        base_model_view["next_action"] = "clarify_chart_uuid"
        execution_ref["chart_uuid_candidates"] = list(chart_uuids)
        return {
            "contract": MODEL_CONTRACT,
            "query_mode": "chart_uuid",
            "data_state": "not_required",
            "metadata_source": "",
            "metadata_version": "",
            "status": "clarify_required",
            "model_view": base_model_view,
            "answer_contract": {
                "required_disclosures_zh": ["需要说明检测到多个图表 UUID。"],
                "forbidden_outputs_zh": ["不得静默选择其中一个图表 UUID 执行。"],
                "technical_identifiers_user_visible": False,
                "user_visible_language": "zh-CN",
            },
            "execution_ref": execution_ref,
        }

    chart_uuid = chart_uuids[0]
    action = _chart_action(query)
    command_parts = ["opscli", "query", "chart", "--uuid", chart_uuid]
    if action == "run":
        command_parts.append("--run")
    elif action == "dry_run":
        command_parts.append("--dry-run")
    elif action == "document":
        command_parts[2] = "chart-doc"
    command_parts.append("--pretty")

    execution_ref.update(
        {
            "chart_uuid": chart_uuid,
            "chart_action": action,
            "query_command": " ".join(command_parts),
            "run": action == "run",
            "dry_run": action == "dry_run",
        }
    )
    action_disclosure = {
        "structure": "本次只获取图表保存的查询结构，不执行数据查询。",
        "run": "本次执行图表保存的全部查询，并合并返回结果。",
        "dry_run": "本次只生成图表查询 SQL，不执行数据查询。",
        "document": "本次生成图表查询 API 调用文档，不执行数据查询。",
    }[action]
    return {
        "contract": MODEL_CONTRACT,
        "query_mode": "chart_uuid",
        "data_state": "not_required",
        "metadata_source": "",
        "metadata_version": "",
        "status": "planned",
        "model_view": base_model_view,
        "answer_contract": {
            "required_disclosures_zh": [
                action_disclosure,
                "图表包含多条查询时必须遍历全部查询，并按 _query_index 区分来源。",
                "查询范围受当前认证账号权限约束。",
            ],
            "forbidden_outputs_zh": [
                "不得把图表 UUID 查询改写为普通数据集查询。",
                "不得只读取第一条查询后把局部结果表述为完整图表结果。",
                "不得在本地累加明细行替代服务端返回的小计或总计。",
            ],
            "technical_identifiers_user_visible": False,
            "user_visible_language": "zh-CN",
        },
        "execution_ref": execution_ref,
    }


# ---------------------------------------------------------------------------
# 内部规划器：平台权限枚举解析
# ---------------------------------------------------------------------------


def _resolve_platform_enum(
    semantic_members: Sequence[str],
    authorized_values: Sequence[str] | None,
    rules: dict,
) -> dict:
    """把服务端实际返回的权限枚举值解析到请求的平台语义成员上。

    状态含义：
    - not_applicable：请求中没有可解析的平台语义成员（含不支持的平台）；
    - required：需要先查询当前账号权限枚举再回传；
    - resolved：全部按别名规则确定性解析成功；
    - no_authorized_overlap：当前账号枚举与请求平台无交集；
    - ambiguous：某个枚举值同时命中多个语义成员，禁止猜测。
    """
    if not semantic_members:
        return {
            "status": "not_applicable",
            "resolved_filter_values": [],
            "resolved_values_are_authorized": False,
            "resolved_semantic_members": [],
            "missing_semantic_members": [],
        }
    if authorized_values is None:
        return {
            "status": "required",
            "resolved_filter_values": [],
            "resolved_values_are_authorized": False,
            "resolved_semantic_members": [],
            "missing_semantic_members": list(semantic_members),
        }
    if isinstance(authorized_values, (str, bytes)) or any(
        not isinstance(value, str) or not value.strip() for value in authorized_values
    ):
        raise TypeError("authorized_platform_values_must_be_strings")
    aliases = rules["platform_scope"]["filter_values"]
    normalized_aliases = {
        member: {_normalize_enum(alias) for alias in aliases.get(member, [])}
        for member in semantic_members
    }
    resolved = []
    resolved_members = set()
    ambiguous_values = []
    for value in _deduplicate([item.strip() for item in authorized_values]):
        normalized = _normalize_enum(value)
        matches = [
            member
            for member in semantic_members
            if normalized in normalized_aliases.get(member, set())
        ]
        if len(matches) > 1:
            ambiguous_values.append(value)
        elif len(matches) == 1:
            resolved.append(value)
            resolved_members.add(matches[0])
    missing = [member for member in semantic_members if member not in resolved_members]
    status = (
        "ambiguous"
        if ambiguous_values
        else ("resolved" if resolved else "no_authorized_overlap")
    )
    return {
        "status": status,
        "resolved_filter_values": [] if ambiguous_values else resolved,
        "resolved_values_are_authorized": bool(resolved and not ambiguous_values),
        "resolved_semantic_members": (
            []
            if ambiguous_values
            else [member for member in semantic_members if member in resolved_members]
        ),
        "missing_semantic_members": missing,
        "ambiguous_values": ambiguous_values,
    }


def _platform_scope(
    selection: dict,
    rules: dict,
    authorized_platform_values: Sequence[str] | None,
) -> dict:
    """构建请求的平台范围规划器。

    平台槽位值先经 platform_scope.members 展开为语义成员
    （例如 amazon → amazon_sc + amazon_vc）；不在 members 中的
    平台（如 walmart）展开为空，最终由 _next_action 判定为不支持。
    """
    slots = selection.get("slots", {}).get("platform", [])
    if not isinstance(slots, list):
        slots = []
    members = rules["platform_scope"]["members"]
    semantic_members = _deduplicate(
        [member for slot in slots for member in members.get(slot, [])]
    )
    return {
        "requested_slots": slots,
        "semantic_members": semantic_members,
        "requires_permission_enum_validation": bool(slots),
        "permission_field": "platform_name" if slots else "",
        "component_lookup": None,
        "enum_resolution": _resolve_platform_enum(
            semantic_members, authorized_platform_values, rules
        ),
        "authorization_rule": (
            "resolve_only_from_current_account_component_enum"
            if slots
            else "not_applicable"
        ),
    }


def _platform_component_lookup(adapter: MetadataAdapter, dataset_alias: str, query: str) -> dict:
    """定位平台筛选字段对应的权限枚举组件数据集（alias 与 table_id）。

    任何一步不满足（无 platform_name 筛选字段、组件未授权等）
    都归一为 guidance_status=unavailable，由上层阻断该筛选。
    """
    try:
        full = dataset_guidance.build_guidance(
            adapter,
            dataset_alias,
            query=query,
            output_mode="full",
            max_dimensions=1,
            max_metrics=1,
        )
        relationship = next(
            item
            for item in full["permission_scope"]["filter_fields"]
            if item["field_name"] == "platform_name"
        )
        component_alias = relationship.get("component_dataset_alias")
        if not relationship.get("explicit_filter_allowed") or not component_alias:
            raise LookupError("platform_component_unavailable")
        component = dataset_guidance.build_guidance(
            adapter,
            component_alias,
            query="平台",
            requested_fields=("platform_name",),
            output_mode="full",
            max_dimensions=1,
            max_metrics=1,
        )
    except (KeyError, LookupError, StopIteration, TypeError, ValueError):
        return {
            "guidance_status": "unavailable",
            "field_name": "platform_name",
        }
    return {
        "guidance_status": component["guidance_status"],
        "field_name": "platform_name",
        "component_dataset_alias": component["dataset"]["dataset_alias"],
        "component_table_id": component["dataset"]["table_id"],
    }


def _ensure_ready_adapter(
    adapter: MetadataAdapter, refresh_fn
) -> tuple[MetadataAdapter, bool, bool]:
    """确保元数据就绪：datasets 与 fields 均非空。

    未就绪且注入了 refresh_fn 时触发一次刷新（失效缓存并重取全量元数据），
    用刷新后的 payload 重建适配器。替代旧 subprocess skills upgrade 的
    「就绪判定 + 自动升级」控制流（内核化后刷新为同步内部调用，无后台三态）。

    Returns:
        (可能被替换的 adapter, 是否就绪, 本次是否执行过刷新)
    """
    def _ready(a: MetadataAdapter) -> bool:
        return bool(a.datasets_rows()) and bool(a.fields_rows())

    if _ready(adapter):
        return adapter, True, False
    if refresh_fn is None:
        return adapter, False, False
    new_payload = refresh_fn()
    if new_payload is not None:
        adapter = MetadataAdapter(new_payload)
    return adapter, _ready(adapter), True


# recovery_state → (面向模型的中文恢复指引, 恢复命令)。
# in_progress/started 场景的恢复命令就是「等待后原样重跑」——用 sleep 前缀把
# 等待与重跑合并进一条命令，恰好贴着 30 秒窗口用满等待时间
_REFRESH_RECOVERY = {
    "refresh_in_progress": (
        "元数据刷新已在后台进行（无需任何升级动作）：等待约 25 秒后原样重跑本规划命令即可，"
        "可直接执行 recovery_command 一步完成等待与重跑；连续 3 次仍未就绪才按 "
        "references/feedback-guide.md 提交反馈并停止。",
        'sleep 25 && opscli query plan "<原查询原文>"',
    ),
    "refresh_failed": (
        "自动刷新失败：手动执行 recovery_command 刷新后重跑本规划命令；"
        "仍失败时向用户如实说明元数据异常，并按 references/feedback-guide.md 提交一次反馈。",
        METADATA_UPGRADE_COMMAND,
    ),
}


def _refresh_contract(recovery_state: str = "refresh_failed") -> dict:
    """元数据未就绪时的刷新规划器输出：自带恢复状态与可执行恢复命令。

    规划器必须自带恢复命令原文：e2e 实测打回输出只有状态码时，
    Agent 无一按指引升级、全部弃管线退回旧探查流程。
    内核化后元数据来源为后端全量元数据，未就绪即返回本合同交调用方按
    recovery_command 重跑（内核入口 opscli query plan / MCP query_plan）。
    """
    hint, command = _REFRESH_RECOVERY.get(recovery_state, _REFRESH_RECOVERY["refresh_failed"])
    return {
        "contract": INTERNAL_CONTRACT,
        "query_execution_allowed": False,
        "data_state": "missing",
        "metadata_version": "",
        "selection": None,
        "selected_dataset_guidance": None,
        "requested_platform_scope": None,
        "next_action": "refresh_authorized_metadata",
        "recovery_state": recovery_state,
        "recovery_command": command,
        "recovery_hint_zh": hint,
    }


def _next_action(selection: dict, guidance: dict | None, platform_scope: dict) -> str:
    """依据选表、字段指导与平台解析状态推导下一步动作。"""
    if selection["planner_status"] != "candidate_ready":
        return "ask_user_for_clarification"
    if guidance is None:
        return "ask_user_for_clarification"
    status = guidance.get("guidance_status")
    if status == "clarify_required":
        return "ask_user_for_field_clarification"
    if status == "permission_enum_only":
        return "permission_enum_lookup_only"
    if platform_scope["requires_permission_enum_validation"]:
        resolution = platform_scope.get("enum_resolution") or {}
        # 请求了平台筛选但没有任何可解析的语义成员（如非亚马逊平台），
        # 明确阻断为"平台范围不支持"，不能与枚举歧义混为一谈
        if resolution.get("status") == "not_applicable":
            return "block_platform_scope_unsupported"
        lookup = platform_scope.get("component_lookup") or {}
        # 组件引用的权威性来自 select_columns 关系本身；QA 等环境会把渠道组件
        # 发布为 dataset_category=normal（既可查询又当组件，guidance_status=ready），
        # 因此 ready 与 permission_enum_only 均视为组件可用，不得据类目形态阻断
        if lookup.get("guidance_status") not in ("permission_enum_only", "ready"):
            return "block_platform_filter_missing_component"
        if resolution.get("status") == "required":
            return "query_platform_permission_enum"
        if resolution.get("status") == "resolved":
            return "construct_query"
        if resolution.get("status") == "no_authorized_overlap":
            return "block_platform_scope_not_authorized"
        return "block_platform_enum_ambiguous"
    return "construct_query"


def build_query_plan(
    adapter: MetadataAdapter,
    query: str,
    requested_fields: Sequence[str] = (),
    authorized_platform_values: Sequence[str] | None = None,
    *,
    rules: dict | None = None,
    top_n: int = planner.MAX_CANDIDATES,
    refresh_fn=None,
) -> dict:
    """一次调用产出完整的内部规划结果（数据源为后端全量元数据适配器）。

    元数据未就绪（datasets/fields 为空）时触发一次注入的 refresh_fn
    （失效缓存并重取全量元数据），仍未就绪才返回刷新规划器、不做任何选表推断，
    保证规划永远建立在当前账号最新授权元数据之上。

    Args:
        adapter: 元数据适配器（后端 query-metadata 同形行）。
        query: 用户查询原文。
        requested_fields: 用户点名字段。
        authorized_platform_values: 已回传的平台授权值（二段收敛用）。
        rules: 领域意图规则；缺省从内核静态资源加载。
        top_n: 选表候选上限。
        refresh_fn: 元数据未就绪时的刷新回调，返回新 payload（可为 None）。
    """
    adapter, ready, upgrade_performed = _ensure_ready_adapter(adapter, refresh_fn)
    if not ready:
        return _refresh_contract("refresh_failed")

    raw_rules = rules if rules is not None else _load_rules_resource()
    validated_rules = schema.validate_rules(raw_rules)
    cards = planner.load_authorized_cards(adapter)
    selection = planner.plan_query(query, cards, validated_rules, top_n)

    def selected_guidance(current_selection: dict) -> dict | None:
        if current_selection.get("planner_status") != "candidate_ready":
            return None
        candidates = current_selection.get("dataset_candidates", [])
        if not candidates:
            return None
        return dataset_guidance.build_guidance(
            adapter,
            candidates[0]["dataset_alias"],
            query=query,
            requested_fields=requested_fields,
        )

    guidance = selected_guidance(selection)
    # 默认推荐必须同时通过字段指导校验；无法解析点名字段时回到原选表流程。
    if (
        selection.get("default_dataset_recommendation")
        and guidance is not None
        and guidance.get("guidance_status") == "clarify_required"
    ):
        selection = planner.plan_query(
            query,
            cards,
            validated_rules,
            top_n,
            recommend_default_dataset=False,
        )
        guidance = selected_guidance(selection)

    platform_scope = _platform_scope(selection, raw_rules, authorized_platform_values)
    if selection["planner_status"] == "candidate_ready":
        candidates = selection.get("dataset_candidates", [])
        if candidates:
            if platform_scope["requires_permission_enum_validation"]:
                platform_scope["component_lookup"] = _platform_component_lookup(
                    adapter, candidates[0]["dataset_alias"], query
                )
    result = {
        "contract": INTERNAL_CONTRACT,
        "query_execution_allowed": False,
        "data_state": "ready",
        # 元数据来源标记：内核化后恒为后端全量元数据（经用户级元数据缓存）
        "metadata_source": "backend_query_metadata",
        # 本次调用是否执行过刷新：刷新与自动枚举不在同一次调用内叠加
        "upgrade_performed_this_call": upgrade_performed,
        # 元数据快照指纹：替代旧 effective_data_dir，标识本次生效的元数据
        "metadata_fingerprint": adapter.fingerprint(),
        "metadata_version": "",
        "selection": selection,
        "selected_dataset_guidance": guidance,
        "requested_platform_scope": platform_scope,
        "next_action": _next_action(selection, guidance, platform_scope),
    }
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("query_plan_output_too_large")
    return result


# ---------------------------------------------------------------------------
# 模型规划器投影：只暴露模型规划与最终回答所需的最小字段集
# ---------------------------------------------------------------------------


def _requested_fields(guidance: dict, field_type: str, query: str) -> list[dict]:
    """从字段指导结果中筛出用户真正点名的字段。

    只保留显式传参（selection_source=explicit）或中文名出现在
    查询原文中的字段，防止把打分兜底选出的字段当成用户诉求。
    """
    field_guidance = guidance.get("field_guidance") or {}
    fields = field_guidance.get(field_type) or []
    normalized_query = _normalize(query)
    selected = []
    for index, item in enumerate(fields):
        if not isinstance(item, dict):
            continue
        source = item.get("selection_source")
        label = _normalize(item.get("verbose_name"))
        if source in {"explicit", "semantic_alias"} or (
            label and label in normalized_query
        ):
            position = normalized_query.find(label) if label else len(normalized_query)
            if position < 0:
                position = len(normalized_query)
            selected.append((position, index, item))
    return [item for _position, _index, item in sorted(selected)]


def _ambiguous_natural_field_labels(guidance: dict, query: str) -> list[str]:
    """识别自然语言命中的同标签多物理字段；显式 --field 不在此处拦截。"""
    grouped: dict[str, set[str]] = {}
    display: dict[str, str] = {}
    for field_type in ("dimensions", "metrics"):
        for item in _requested_fields(guidance, field_type, query):
            if item.get("selection_source") == "explicit":
                continue
            label = _normalize(item.get("verbose_name"))
            field_name = str(item.get("field_name", ""))
            if label and field_name:
                grouped.setdefault(label, set()).add(field_name)
                display.setdefault(label, str(item.get("verbose_name", "")))
    return [display[label] for label, names in grouped.items() if len(names) > 1]


def _longest_unique_labels(fields: Iterable[dict]) -> list[dict]:
    """标签去重并做最长标签吞并：被更长标签完全包含的短标签让位。

    例：查询同时命中"销售额"与"广告销售额"时只保留"广告销售额"，
    避免同一个文本片段产出两个字段结论。
    """
    unique = []
    identity_keys = set()
    for item in fields:
        label = _normalize(item.get("verbose_name"))
        # 显式字段按物理 field_name 去重；非显式字段才按展示名去重。
        # 这样同标签不同物理字段（以及包含关系）不会吞掉用户明确点名的身份。
        identity = (
            "field",
            str(item.get("field_name", "")),
        ) if item.get("selection_source") == "explicit" else ("label", label)
        if label and identity not in identity_keys:
            identity_keys.add(identity)
            unique.append(item)
    labels = [_normalize(item.get("verbose_name")) for item in unique]
    return [
        item
        for item in unique
        if item.get("selection_source") == "explicit"
        or not any(
            _normalize(item.get("verbose_name")) != other
            and _normalize(item.get("verbose_name")) in other
            for other in labels
        )
    ]


def _selected_fields(
    guidance: dict,
    query: str,
    authorized_field_labels: dict[str, list[dict]],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """确定模型可见的维度与指标列表。

    优先级：字段指导中的显式/原文命中字段 → 全量授权字段标签兜底
    （覆盖指导截断导致点名字段落选的情况）。维度与指标互相做
    包含吞并，避免"广告费"同时被当成维度和指标。
    返回 (点名维度, 点名指标, 推荐维度, 推荐指标)：
    点名为空时给出打分推荐字段（selection_source=recommended，需向用户确认）。
    """
    dimensions = _requested_fields(guidance, "dimensions", query)
    metrics = _requested_fields(guidance, "metrics", query)
    normalized_query = _normalize(query)
    if not dimensions:
        dimensions = [
            dict(item, selection_source="authorized_query_label")
            for item in authorized_field_labels.get("dimensions", [])
            if _normalize(item.get("verbose_name")) in normalized_query
        ]
    if not metrics:
        metrics = [
            dict(item, selection_source="authorized_query_label")
            for item in authorized_field_labels.get("metrics", [])
            if _normalize(item.get("verbose_name")) in normalized_query
        ]
    # 无点名字段时的推荐兜底（P0-1c）：把指导层已按打分选出的 top 字段
    # 以 recommended 来源标注供模型向用户提议，替代「全空无从下手→扫盘」
    field_guidance = guidance.get("field_guidance") or {}
    recommended_dimensions: list[dict] = []
    recommended_metrics: list[dict] = []
    # 只有维度和指标都未点名时才给整套推荐。仅点名指标表示“整体聚合”，
    # 仅点名维度也可能是明细诉求，不能强塞另一类型字段再制造确认门槛。
    if not dimensions and not metrics:
        recommended_dimensions = [
            dict(item, selection_source="recommended")
            for item in (field_guidance.get("dimensions") or [])[:MAX_RECOMMENDED_FIELDS]
            if isinstance(item, dict)
        ]
        recommended_metrics = [
            dict(item, selection_source="recommended")
            for item in (field_guidance.get("metrics") or [])[:MAX_RECOMMENDED_FIELDS]
            if isinstance(item, dict)
        ]
    dimensions = _longest_unique_labels(dimensions)
    metrics = _longest_unique_labels(metrics)
    # 按标签在查询原文中的出现位置排序，保持与用户表述一致的呈现顺序
    dimensions.sort(key=lambda item: normalized_query.find(_normalize(item.get("verbose_name"))))
    metrics.sort(key=lambda item: normalized_query.find(_normalize(item.get("verbose_name"))))
    metric_labels = {
        _normalize(item.get("verbose_name"))
        for item in metrics
        if item.get("selection_source") != "explicit"
    }
    dimensions = [
        item
        for item in dimensions
        if item.get("selection_source") == "explicit"
        or not any(
            _normalize(item.get("verbose_name")) in metric_label
            for metric_label in metric_labels
        )
    ]
    dimension_labels = {_normalize(item.get("verbose_name")) for item in dimensions}
    metrics = [
        item
        for item in metrics
        if item.get("selection_source") == "explicit"
        or not any(
            _normalize(item.get("verbose_name")) != dimension_label
            and _normalize(item.get("verbose_name")) in dimension_label
            for dimension_label in dimension_labels
        )
    ]
    return dimensions, metrics, recommended_dimensions, recommended_metrics


def _field_names(fields: Iterable[dict]) -> list[str]:
    """提取字段中文名列表（模型可见层只允许中文名）。"""
    return _deduplicate(str(item.get("verbose_name", "")) for item in fields)


def _execution_fields(fields: Iterable[dict]) -> list[dict]:
    """生成执行引用字段：技术字段名 + 中文标签 + 公式/快照口径。

    公式字段与快照字段都必须带 aggregation_policy，
    提示查询构造阶段不得对其做二次聚合或跨期聚合。
    """
    result = []
    seen = set()
    for item in fields:
        field_name = str(item.get("field_name", ""))
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        reference = {
            "field_name": field_name,
            "label_zh": str(item.get("verbose_name", "")),
            "is_formula": bool(item.get("is_formula")),
            "is_snapshot": bool(item.get("is_snapshot")),
        }
        if reference["is_formula"] or reference["is_snapshot"]:
            reference["aggregation_policy"] = item.get("aggregation_policy")
        result.append(reference)
    return result


def _status(internal: dict) -> str:
    """把内部规划器状态归一为模型规划器三态：planned / clarify_required / blocked。"""
    if internal.get("data_state") != "ready":
        return "blocked"
    selection = internal.get("selection") or {}
    guidance = internal.get("selected_dataset_guidance") or {}
    next_action = str(internal.get("next_action", ""))
    if selection.get("planner_status") == "clarify_required":
        return "clarify_required"
    if guidance.get("guidance_status") == "clarify_required":
        return "clarify_required"
    if next_action.startswith("ask_user"):
        return "clarify_required"
    if next_action.startswith("block_") or next_action == "refresh_authorized_metadata":
        return "blocked"
    return "planned"


def _platform_filter_state(platform: dict, *, data_ready: bool = True) -> str:
    """归一平台筛选状态：未知 / 未请求 / 待权限枚举 / 已解析 / 被阻断。

    元数据未就绪（刷新规划器）时规划根本没有跑，平台诉求无从判断，
    必须返回 unknown 而非 not_requested，防止模型误读"无平台诉求"。
    """
    if not data_ready:
        return "unknown"
    if not platform.get("requires_permission_enum_validation"):
        return "not_requested"
    resolution = platform.get("enum_resolution") or {}
    status = resolution.get("status")
    if status == "required":
        return "requires_permission_enum"
    if status == "resolved":
        return "resolved"
    return "blocked"


def _answer_contract(
    status: str,
    clarification_reasons: list[str],
    platform_filter_state: str,
    guidance: dict,
) -> dict[str, Any]:
    """生成回答规划器：最终回答必须覆盖的披露与禁止输出。"""
    required = []
    if platform_filter_state == "requires_permission_enum":
        required.append("permission_enum_required")
    if any(
        reason in clarification_reasons
        for reason in ("dataset_constraints", "default_dataset_confirmation")
    ):
        required.append("dataset_confirmation_required")
    if guidance.get("guidance_status") == "clarify_required":
        required.append("field_confirmation_required")
    if status == "blocked":
        required.append("blocked_reason_required")
    # 精简原则（P2-1）：对模型而言中文文案即可执行，*_codes 为校验器冗余，
    # 不再进入模型规划器，节省每次规划的固定 token 开销
    return {
        "required_disclosures_zh": [
            DISCLOSURE_MESSAGES[code]
            for code in _deduplicate(required)
            if code in DISCLOSURE_MESSAGES
        ],
        "forbidden_outputs_zh": FORBIDDEN_OUTPUT_MESSAGES,
        "technical_identifiers_user_visible": False,
        "user_visible_language": "zh-CN",
    }


def _platform_scope_disclosures(platform: dict) -> list[str]:
    """生成裸“亚马逊”默认范围及部分权限降级的强制披露。"""
    if "amazon" not in set(platform.get("requested_slots") or []):
        return []

    disclosures = ["用户未指定亚马逊SC或亚马逊VC，本次默认按亚马逊SC + 亚马逊VC处理。"]
    resolution = platform.get("enum_resolution") or {}
    if resolution.get("status") != "resolved":
        return disclosures

    effective = [
        PLATFORM_MEMBER_LABELS.get(str(item), str(item))
        for item in resolution.get("resolved_semantic_members") or []
    ]
    missing = [
        PLATFORM_MEMBER_LABELS.get(str(item), str(item))
        for item in resolution.get("missing_semantic_members") or []
    ]
    if effective and missing:
        disclosures.append(
            "当前账号实际可用范围为"
            + " + ".join(effective)
            + "，未枚举到"
            + " + ".join(missing)
            + "；本次直接查询可用部分，不把结果表述为完整亚马逊范围。"
        )
    return disclosures


def _reason_zh(reasons: Iterable[str]) -> str:
    """把选表 reasons 代码翻成一句中文短语（取首个可翻译原因）。"""
    for reason in reasons:
        for prefix, label in CANDIDATE_REASON_LABELS:
            if str(reason).startswith(prefix):
                return label
    return "语义相关"


def _candidate_cards_zh(
    selection: dict,
    dataset_names_zh: dict[str, str],
    dataset_summaries_zh: dict[str, str],
) -> list[dict]:
    """澄清态的候选卡片投影（P0-2）：中文名 + 命中原因，供带选项提问。"""
    cards = []
    for item in (selection.get("dataset_candidates") or [])[:MAX_CANDIDATE_CARDS]:
        alias = str(item.get("dataset_alias", ""))
        name_zh = dataset_names_zh.get(alias) or ""
        if not name_zh:
            continue
        card = {"name_zh": name_zh, "reason_zh": _reason_zh(item.get("reasons") or [])}
        summary = dataset_summaries_zh.get(alias)
        if summary:
            card["summary_zh"] = summary
        cards.append(card)
    return cards


def _bigrams(text: str) -> set[str]:
    """中文标签的字符二元组集合（近似相似度用）。"""
    normalized = _normalize(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def _field_suggestions(
    unknown_fields: Iterable[str],
    authorized_field_labels: dict[str, list[dict]],
) -> list[dict]:
    """为未知点名字段生成「你是不是想要」近似建议（P0-2）。

    用字符二元组重合度做轻量相似排序，避免模型对拼错字段盲试。
    """
    labels = _deduplicate(
        str(item.get("verbose_name", ""))
        for item in (
            list(authorized_field_labels.get("dimensions", []))
            + list(authorized_field_labels.get("metrics", []))
        )
        if isinstance(item, dict)
    )
    suggestions = []
    for unknown in unknown_fields:
        target = _bigrams(str(unknown))
        if not target:
            continue
        ranked = sorted(
            (
                (len(target & _bigrams(label)), label)
                for label in labels
            ),
            key=lambda item: (-item[0], item[1]),
        )
        candidates = [label for score, label in ranked[:3] if score > 0]
        suggestions.append({"requested": str(unknown), "candidates_zh": candidates})
    return suggestions


def _build_query_template(
    table_id: object,
    dimensions: list[dict],
    metrics: list[dict],
    date_fields: list[dict],
    scope: dict | None,
) -> dict | None:
    """生成可直接填充的正式查询 payload 骨架（P1-4）。

    形状与已验证的 opscli query simple --json 实测形态一致：
    日期过滤为 >=/<= 两行、对比为 dataComparison{field,startDate,endDate}、
    排序为 orderBy[{field,desc}]（desc 为布尔，true 降序）。普通指标默认 SUM；
    公式/快照指标不带 aggregation（由服务端口径处理）。
    """
    if table_id in (None, ""):
        return None
    dims = [
        {"field": item["field_name"], "alias": item["field_name"]}
        for item in dimensions
    ]
    mets = []
    for item in metrics:
        entry: dict[str, Any] = {"field": item["field_name"], "alias": item["field_name"]}
        if not (item.get("is_formula") or item.get("is_snapshot")):
            entry["aggregation"] = "SUM"
        mets.append(entry)
    date_field = date_fields[0]["field_name"] if date_fields else None
    filters: list[dict] = []
    template: dict[str, Any] = {
        "tableId": table_id,
        "dimensions": dims,
        "metrics": mets,
        "filters": filters,
        "orderBy": None,
        "limit": None,
    }
    if date_field and scope and scope.get("start"):
        filters.append({"field": date_field, "operator": ">=", "value": scope["start"]})
        filters.append({"field": date_field, "operator": "<=", "value": scope["end"]})
        comparison = scope.get("comparison")
        if comparison:
            template["dataComparison"] = {
                "field": date_field,
                "startDate": comparison["start"],
                "endDate": comparison["end"],
            }
    return template


def _platform_enum_command(component_table_id: object) -> str | None:
    """生成可直接执行的平台权限枚举命令（P0-3 兜底层）。"""
    if component_table_id in (None, ""):
        return None
    enum_json = json.dumps(
        {
            "tableId": component_table_id,
            "dimensions": [{"field": "platform_name", "alias": "platform_name"}],
            "metrics": [],
            "limit": 100,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"opscli query simple --table-id {component_table_id} "
        f"--json '{enum_json}' --run --pretty"
    )


def _filter_components(guidance: dict) -> list[dict]:
    """投影可用筛选组件引用（P0-1b）：部门/国家等显式筛选的合规枚举入口。"""
    scope = guidance.get("permission_scope") or {}
    components = []
    for item in scope.get("filter_fields") or []:
        if item.get("component_status") != "component_available":
            continue
        if not item.get("component_dataset_alias"):
            continue
        components.append(
            {
                "field_name": item.get("field_name", ""),
                "label_zh": item.get("verbose_name", ""),
                "component_dataset_alias": item.get("component_dataset_alias"),
                "component_table_id": item.get("component_table_id", ""),
            }
        )
        if len(components) >= MAX_FILTER_COMPONENTS:
            break
    return components


# filter_config 操作符 → 中文描述（披露文案用，与后台配置表单 label 一致）
_FILTER_OPERATOR_ZH = {
    "equals": "等于", "notEquals": "不等于", "gt": "大于", "gte": "大于等于",
    "lt": "小于", "lte": "小于等于", "isEmpty": "为空", "isNotEmpty": "不为空",
}


def _default_filters_ref(guidance: dict) -> list[dict]:
    """把 guidance.default_filters 投影为执行引用形态（模型直接填充查询用）。"""
    refs = []
    for item in guidance.get("default_filters") or []:
        config = item.get("filter_config") or {}
        # 优先取枚举值列表；没有则把 value 归一化为列表
        values = config.get("enum_value") or []
        if not values and config.get("value") not in (None, ""):
            raw = config["value"]
            values = raw if isinstance(raw, list) else [raw]
        refs.append({
            "field_name": item["field_name"],
            "label_zh": item.get("verbose_name", ""),
            "operator": config.get("operator", "equals"),
            "values": values,
            "type": config.get("type", "required"),
            "filter_type": config.get("filter_type", "enum"),
            "filter_agg": config.get("filter_agg", "none"),
        })
    return refs


def _default_filters_zh(refs: list[dict]) -> list[str]:
    """默认条件的用户可见中文描述（回答披露用）。"""
    lines = []
    for ref in refs:
        op_zh = _FILTER_OPERATOR_ZH.get(ref["operator"], ref["operator"])
        value_text = "、".join(str(v) for v in ref["values"]) or "-"
        type_zh = "强制" if ref["type"] == "required" else "可选"
        lines.append(f"{ref['label_zh'] or ref['field_name']} {op_zh} {value_text}（{type_zh}）")
    return lines


def _slot_surplus_disclosure_zh(slot_name: str, detail: dict) -> str:
    """把「数据集覆盖得比请求多」翻成一句语义正确的中文强制披露。

    必须按槽位语义分文案，两类风险的正确应对方式相反：

    - grain（统计粒度）：多出的取值是数据集里另一个维度字段（如请求搜索词级、
      数据集是关键词×搜索词级）。不选该维度即按请求粒度聚合，风险在于份额、
      比率这类非可加指标不能直接汇总 → 说「粒度更细」，提醒不要把明细当汇总。
    - platform / ad_type：能进到这里说明 slot_modes 是 fixed，即数据集**没有**
      该槽位的筛选字段（filterable 的槽位根本不会产出 surplus，见
      agent_query_planner._extra_slot_terms）。多出的取值筛不掉，交付的是合计
      → 必须说「无法按 X 筛选、结果含 Y」。原先照 grain 语义写成「粒度更细、
      不得把明细当汇总」，会引导模型把 SP+SD+SB 合计当成纯 SP 汇报，
      正好是最危险的静默错数方向。
    """
    label = str(detail.get("slot_label_zh") or slot_name)
    surplus = "、".join(str(item) for item in detail.get("surplus_zh") or [])
    requested = "、".join(str(item) for item in detail.get("requested_zh") or [])
    if slot_name == "grain":
        return (
            f"所选数据集的{label}比请求更细，额外覆盖：{surplus}；"
            "结论中必须说明这一口径差异，不得把更细粒度的明细当成请求粒度的汇总。"
        )
    return (
        f"所选数据集无法按{label}筛选，返回数据已包含 {surplus}，"
        f"是把这些一起算进来的合计；结论中必须说明这一范围差异，"
        f"不得当作纯 {requested} 的数据汇报。"
    )


def build_model_contract(
    internal: dict,
    query: str = "",
    authorized_field_labels: dict[str, list[dict]] | None = None,
    dataset_names_zh: dict[str, str] | None = None,
    dataset_summaries_zh: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把内部规划器投影为模型可见的精简规划器。

    model_view 只含用户可见中文结论；execution_ref 仅供查询构造，
    不得向用户展示，也不得作为业务判断理由。
    """
    selection = internal.get("selection") or {}
    guidance = internal.get("selected_dataset_guidance") or {}
    dataset = guidance.get("dataset") or {}
    platform = internal.get("requested_platform_scope") or {}
    resolution = platform.get("enum_resolution") or {}
    clarification_reasons = [
        str(item) for item in selection.get("missing_information", []) if item
    ]
    status = _status(internal)
    data_ready = internal.get("data_state") == "ready"
    platform_state = _platform_filter_state(platform, data_ready=data_ready)
    component = platform.get("component_lookup") or {}
    dimensions, metrics, recommended_dims, recommended_mets = _selected_fields(
        guidance, query, authorized_field_labels or {"dimensions": [], "metrics": []}
    )
    ambiguous_field_labels = _ambiguous_natural_field_labels(guidance, query)
    if ambiguous_field_labels:
        status = "clarify_required"
        if "field_identity" not in clarification_reasons:
            clarification_reasons.append("field_identity")
        ambiguous_keys = {_normalize(item) for item in ambiguous_field_labels}
        dimensions = [
            item
            for item in dimensions
            if _normalize(item.get("verbose_name")) not in ambiguous_keys
        ]
        metrics = [
            item
            for item in metrics
            if _normalize(item.get("verbose_name")) not in ambiguous_keys
        ]
    # 时间口径本地解析（P0-5）：只在元数据就绪时计算，模型不再自算日期窗口
    scope = time_scope.parse(query) if data_ready else None
    field_guidance = guidance.get("field_guidance") or {}
    date_fields = [
        {"field_name": item["field_name"], "label_zh": item.get("verbose_name", "")}
        for item in field_guidance.get("date_fields") or []
    ]
    unknown_fields = [
        str(item) for item in field_guidance.get("unknown_requested_fields") or []
    ]
    pending_confirmations_zh: list[str] = []
    execution_path_ready = str(internal.get("next_action", "")) == "construct_query"
    default_dataset_recommendation = selection.get("default_dataset_recommendation") or {}
    # 即时综合数据集已经通过当前账号授权、业务语义和字段指导三层校验，且原文确实
    # 命中了至少一个查询字段时，默认选表本身已无歧义，不能再制造一次人工确认。
    # 完全模糊、没有任何字段命中的请求仍保留推荐确认，避免擅自决定查询内容。
    default_dataset_auto_selected = bool(
        default_dataset_recommendation
        and guidance.get("guidance_status") == "ready"
        and (dimensions or metrics)
    )
    if default_dataset_auto_selected:
        default_dataset_recommendation["confirmation_required"] = False
        default_dataset_recommendation["auto_selected"] = True
    if default_dataset_recommendation.get("confirmation_required"):
        status = "clarify_required"
        if "default_dataset_confirmation" not in clarification_reasons:
            clarification_reasons.append("default_dataset_confirmation")
        pending_confirmations_zh.append("确认是否使用推荐的即时综合数据集")
    # 只查维度、不查指标（如「某渠道下全部 ASIN」）时，默认时间窗口没有业务意义：
    # 用户要的是去重维度全集，卡近 30 天只会漏掉更早出现过的值。
    # 该规则一度因「筛选值不写入模板导致静默全量」收回，现由组件筛选值解析
    # （_resolve_component_filters 的锁定/澄清/阻断三态）兜底后恢复。
    if (
        scope
        and scope.get("is_default")
        and dimensions
        and not (metrics or recommended_mets)
    ):
        scope = {
            **scope,
            "start": None,
            "end": None,
            "unbounded": True,
            "is_default": False,
            "matched": False,
            "comparison": None,
            "label_zh": "全部时间（仅维度查询，原文未限定时间，不加日期筛选）",
        }
    if status == "planned" and execution_path_ready and scope and scope.get("is_default"):
        status = "clarify_required"
        clarification_reasons.append("time_scope_confirmation")
        pending_confirmations_zh.append("确认是否采用默认近30天时间范围")
    if status == "planned" and execution_path_ready and (recommended_dims or recommended_mets):
        status = "clarify_required"
        clarification_reasons.append("recommended_fields_confirmation")
        pending_confirmations_zh.append("确认是否采用系统推荐的维度和指标")
    model_view: dict[str, Any] = {
        "dataset_name_zh": str(dataset.get("display_name_zh", "")),
        "dimensions": _field_names(dimensions),
        "metrics": _field_names(metrics),
        "platform_semantic_members": [
            # 用户可见层只允许中文标签，内部枚举名留在 execution_ref
            PLATFORM_MEMBER_LABELS.get(str(item), str(item))
            for item in platform.get("semantic_members", [])
        ],
        "platform_filter_state": platform_state,
        "clarification_reason_codes": clarification_reasons,
        "clarification_messages_zh": [
            CLARIFICATION_MESSAGES.get(code, "需要补充查询条件。")
            for code in clarification_reasons
        ],
        "next_action": str(internal.get("next_action", "")),
    }
    resolved_platform_members = [
        PLATFORM_MEMBER_LABELS.get(str(item), str(item))
        for item in resolution.get("resolved_semantic_members") or []
    ]
    if resolved_platform_members:
        model_view["platform_effective_members"] = resolved_platform_members
    platform_disclosures = _platform_scope_disclosures(platform)
    if platform_disclosures:
        model_view["platform_scope_disclosures_zh"] = platform_disclosures
    # 放开固定槽位后，选中数据集覆盖的口径可能比用户要求更宽，必须如实告知，
    # 否则用户会把「关键词×搜索词」级明细当成「搜索词」级汇总，
    # 或把 SP+SD+SB 合计当成纯 SP 数据。
    # 按 dataset_alias 匹配当前实际选中的候选（而非默认取 candidates[0]），
    # 避免候选列表顺序与最终选中项不一致时误取到别的候选的粒度披露。
    selected_alias = dataset.get("dataset_alias")
    grain_extra: dict = {}
    for candidate in selection.get("dataset_candidates") or []:
        if candidate.get("dataset_alias") == selected_alias:
            grain_extra = candidate.get("grain_coverage") or {}
            break
    if grain_extra:
        model_view["grain_disclosure_zh"] = [
            _slot_surplus_disclosure_zh(name, detail) for name, detail in grain_extra.items()
        ]
    if default_dataset_recommendation:
        model_view["default_dataset_recommendation_zh"] = {
            "name_zh": str(dataset.get("display_name_zh", "")),
            "reason_zh": "未明确指定数据集，且该数据集在当前授权范围内并覆盖已明确的业务与字段。",
            "confirmation_required": bool(
                default_dataset_recommendation.get("confirmation_required")
            ),
            "auto_selected": default_dataset_auto_selected,
        }
    if ambiguous_field_labels:
        model_view["ambiguous_field_labels_zh"] = ambiguous_field_labels
        model_view["next_action"] = "ask_user_for_field_clarification"
    if default_dataset_recommendation.get("confirmation_required"):
        model_view["pending_confirmations_zh"] = pending_confirmations_zh
        model_view["next_action"] = "ask_user_for_default_dataset_confirmation"
    elif pending_confirmations_zh:
        model_view["pending_confirmations_zh"] = pending_confirmations_zh
        model_view["next_action"] = "ask_user_for_query_scope_confirmation"
    if scope:
        comparison = scope.get("comparison")
        # 全时段没有起止日期可展示，只声明不加日期筛选，避免出现 None ~ None
        scope_zh = (
            f"{scope['label_zh']}：不限起止日期，查询不含任何日期筛选"
            if scope.get("unbounded")
            else f"{scope['label_zh']}：{scope['start']} ~ {scope['end']}（{scope['timezone']}）"
        )
        if comparison:
            scope_zh += f"；对比期 {comparison['label_zh']}：{comparison['start']} ~ {comparison['end']}"
        if scope.get("is_default"):
            scope_zh += "。注意：未识别到明确时间表述，这是默认口径，必须向用户披露并确认"
            model_view["time_scope_recovery_zh"] = (
                "默认近30天窗口仅在用户原文完全未含时间表述时成立。确认前先回看"
                "用户原始请求：若原文含本月、上月、本周、近N天、指定月份或具体日期，"
                "说明本次规划调用漏传了时间，必须携带用户原文或已锁定的绝对起止日期"
                "重新运行规划器，禁止就时间范围向用户提问。"
            )
        model_view["time_scope_zh"] = scope_zh
        model_view["time_resolution_zh"] = (
            f"时间由 Python 按 {scope['timezone']} 当前日期 {scope['reference_date']} 计算；"
            f"用户未明确年份时以 {scope['reference_year']} 年为相对时间基准，"
            "跨年窗口按真实日历处理，禁止自行推算或改写。"
        )
    # 推荐字段（无点名字段时）：供向用户提议，采用前须在确认摘要中说明来源
    if recommended_dims:
        model_view["recommended_dimensions"] = _field_names(recommended_dims)
    if recommended_mets:
        model_view["recommended_metrics"] = _field_names(recommended_mets)
    # 澄清弹药（P0-2）：候选卡片 + 未知字段回显与近似建议
    if status == "clarify_required":
        cards = _candidate_cards_zh(
            selection,
            dataset_names_zh or {},
            dataset_summaries_zh or {},
        )
        if cards:
            model_view["dataset_candidates_zh"] = cards
        if unknown_fields:
            model_view["unknown_requested_fields"] = unknown_fields
            model_view["field_suggestions_zh"] = _field_suggestions(
                unknown_fields,
                authorized_field_labels or {"dimensions": [], "metrics": []},
            )
    # 刷新规划器的恢复命令必须透传给模型：e2e 实测缺命令原文时 Agent 从不按指引自救
    if internal.get("recovery_command"):
        model_view["recovery_command"] = str(internal["recovery_command"])
        model_view["recovery_hint_zh"] = str(internal.get("recovery_hint_zh", ""))
        if internal.get("recovery_state"):
            model_view["recovery_state"] = str(internal["recovery_state"])

    execution_dimensions = _execution_fields(dimensions + recommended_dims)
    execution_metrics = _execution_fields(metrics + recommended_mets)
    # 推荐来源标注：构造阶段须区分「用户点名」与「系统推荐待确认」
    recommended_names = {
        item["field_name"] for item in recommended_dims + recommended_mets if item.get("field_name")
    }
    for entry in execution_dimensions + execution_metrics:
        if entry["field_name"] in recommended_names:
            entry["selection_source"] = "recommended"
    execution_ref: dict[str, Any] = {
        "user_visible": False,
        "dataset_alias": dataset.get("dataset_alias"),
        "table_id": dataset.get("table_id"),
        "platform_component_alias": component.get("component_dataset_alias"),
        "platform_component_table_id": component.get("component_table_id"),
        "resolved_platform_values": resolution.get("resolved_filter_values", []),
        "dimensions": execution_dimensions,
        "metrics": execution_metrics,
    }
    if platform.get("semantic_members"):
        execution_ref["platform_semantic_keys"] = [
            str(item) for item in platform.get("semantic_members", [])
        ]
    if date_fields:
        execution_ref["date_fields"] = date_fields
    components = _filter_components(guidance)
    if components:
        execution_ref["filter_components"] = components
        # 枚举入口与成员消歧策略必须同时下发，避免模型把包含匹配误当成多个筛选目标。
        execution_ref["filter_value_match_policy"] = {
            **FILTER_VALUE_MATCH_POLICY,
            "normalizations": list(FILTER_VALUE_MATCH_POLICY["normalizations"]),
        }
    if scope:
        execution_ref["time_scope"] = {
            "start": scope["start"],
            "end": scope["end"],
            "unbounded": bool(scope.get("unbounded")),
            "is_default": scope["is_default"],
            "reference_date": scope["reference_date"],
            "reference_year": scope["reference_year"],
            "resolution_source": scope["resolution_source"],
            "year_source": scope["year_source"],
            "comparison_type": (scope.get("comparison") or {}).get("type"),
            "comparison_start": (scope.get("comparison") or {}).get("start"),
            "comparison_end": (scope.get("comparison") or {}).get("end"),
        }
    # 平台枚举现成命令（P0-3 兜底层）：待枚举时模型无需手拼枚举 payload
    if platform_state == "requires_permission_enum":
        enum_command = _platform_enum_command(component.get("component_table_id"))
        if enum_command:
            execution_ref["platform_enum_command"] = enum_command
            execution_ref["platform_enum_return_hint_zh"] = (
                "执行上述命令后，把返回的每个 platform_name 值用重复的 "
                "--authorized-platform-value 参数传回本规划命令，取得终版规划器"
            )
    # 查询模板骨架（P1-4）：status=planned 时给出可直接填充的 payload
    if status == "planned" and str(internal.get("next_action", "")) == "construct_query":
        template = _build_query_template(
            dataset.get("table_id"),
            execution_dimensions,
            execution_metrics,
            date_fields,
            scope,
        )
        if template is not None:
            execution_ref["query_template"] = template
            execution_ref["query_template_fill_rules_zh"] = (
                "模板已预填授权字段与时间窗（日期过滤为 >=/<= 两行实测形态）。"
                "时间窗由 Python 按 execution_ref.time_scope 的参考日期生成，禁止自行心算、猜测年份或改写。"
                "普通指标默认 SUM 按用户口径调整；公式/快照指标不带 aggregation。"
                "排序填 orderBy=[{\"field\":\"<结果alias>\",\"desc\":true/false}]（desc 布尔，true 降序），"
                "行数填 limit；不需要的键（null 值）必须删除后再执行。"
                "selection_source=recommended 的字段须先向用户说明再采用。"
                "数据集默认条件（若有）由服务端查询时自动应用，请勿手动加入 filters；"
                "仅需在回答中向用户披露 default_filters_zh。"
            )
    # 默认条件投影（R5）：把 guidance.default_filters 投影到披露输出，不预填 query_template
    # 服务端是默认条件注入的唯一权威方，客户端预填会与服务端解析后的真实日期 AND 合并 → 恒 0 行
    default_filters = _default_filters_ref(guidance)
    if default_filters:
        execution_ref["default_filters"] = default_filters
        model_view["default_filters_zh"] = _default_filters_zh(default_filters)
    # 回答合同：先构建基础版本，再追加默认条件强制披露
    answer_contract = _answer_contract(status, clarification_reasons, platform_state, guidance)
    answer_contract["required_disclosures_zh"].extend(
        item
        for item in platform_disclosures
        if item not in answer_contract["required_disclosures_zh"]
    )
    if default_filters:
        answer_contract["required_disclosures_zh"].append(
            "本次查询已自动应用数据集默认条件：" + "；".join(model_view["default_filters_zh"])
        )
    if grain_extra:
        answer_contract["required_disclosures_zh"].extend(model_view["grain_disclosure_zh"])
    return {
        "contract": MODEL_CONTRACT,
        "query_mode": "dataset_query",
        "data_state": str(internal.get("data_state", "missing")),
        "metadata_source": str(internal.get("metadata_source", "")),
        "metadata_version": str(internal.get("metadata_version", "")),
        "status": status,
        "model_view": model_view,
        "answer_contract": answer_contract,
        "execution_ref": execution_ref,
    }


def build_model_query_plan(
    adapter: MetadataAdapter,
    query: str,
    requested_fields: Sequence[str] = (),
    authorized_platform_values: Sequence[str] | None = None,
    *,
    refresh_fn=None,
    enum_fn=None,
    auto_enum: bool = True,
    rules: dict | None = None,
    top_n: int = planner.MAX_CANDIDATES,
) -> dict:
    """构建内部合同并投影为模型合同（规划器的默认输出路径）。

    auto_enum=True 时（默认），平台筛选待枚举的 planned 合同会在本函数内
    经注入的 enum_fn 自动执行一次枚举并回灌重规划（P0-3），把「枚举→回传→重规划」
    三步收敛为一次调用；enum_fn 未注入或返回空时，保留首版合同并内嵌现成
    枚举命令走手动路径，绝不阻塞。

    显式图表 UUID 请求在读取元数据前确定性分流，输出 chart_uuid 模式合同；
    该模式直接使用 opscli query chart/chart-doc，不进入普通数据集选表流程。

    Args:
        adapter: 元数据适配器（后端 query-metadata 同形行）。
        refresh_fn: 元数据未就绪时的刷新回调，返回新 payload。
        enum_fn: 平台/组件权限枚举回调，签名 enum_fn(table_id, field_name, *, limit) -> list[str]。
    """
    chart_uuids = _extract_chart_uuids(query)
    if chart_uuids:
        contract = _build_chart_query_contract(query, chart_uuids)
        encoded = json.dumps(
            contract, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise RuntimeError("query_plan_output_too_large")
        return contract

    # 就绪判定与刷新在投影入口统一完成，确保标签收集与选表用的是同一份已就绪元数据
    adapter, _ready, upgraded = _ensure_ready_adapter(adapter, refresh_fn)
    internal = build_query_plan(
        adapter,
        query,
        requested_fields=requested_fields,
        authorized_platform_values=authorized_platform_values,
        rules=rules,
        top_n=top_n,
        refresh_fn=None,
    )
    # 刷新标记合并回内部合同（build_query_plan 未再刷新，upgraded 由本层判定）
    if upgraded:
        internal["upgrade_performed_this_call"] = True
    # 只收集已选数据集的授权字段。跨表全局标签会制造“展示层有字段、
    # execution_ref 无物理身份”的假命中，必须在投影入口收紧作用域。
    authorized_fields = {"dimensions": [], "metrics": []}
    dataset_names_zh: dict[str, str] = {}
    dataset_summaries_zh: dict[str, str] = {}
    if internal.get("data_state") == "ready":
        # 标签读取跟随已就绪的元数据适配器
        rows = adapter.fields_rows()
        selected_alias = str(
            (
                (internal.get("selected_dataset_guidance") or {}).get("dataset")
                or {}
            ).get("dataset_alias", "")
        )
        for row in rows:
            if not selected_alias or row.get("dataset_alias") != selected_alias:
                continue
            key = "dimensions" if row["field_type"] == "dimension" else "metrics"
            authorized_fields[key].append(
                dataset_guidance._compact_field(
                    row, "authorized_query_label", "contract"
                )
            )
        # 数据集 alias → 中文名映射：澄清候选卡片展示用（用户可见层只允许中文）
        for row in adapter.datasets_rows():
            alias = str(row.get("dataset_alias", ""))
            name_zh = str(row.get("description", "") or row.get("dataset_name", ""))
            if alias and name_zh:
                dataset_names_zh[alias] = name_zh
        grouped: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            alias = str(row.get("dataset_alias", ""))
            key = "维度" if row.get("field_type") == "dimension" else "指标"
            grouped.setdefault(alias, {"维度": [], "指标": []})[key].append(
                str(row.get("verbose_name", ""))
            )
        for alias, groups in grouped.items():
            examples = _deduplicate(groups["维度"] + groups["指标"])[:3]
            dataset_summaries_zh[alias] = (
                f"{len(groups['维度'])} 个维度、{len(groups['指标'])} 个指标"
                + ("；代表字段：" + "、".join(examples) if examples else "")
            )
    contract = build_model_contract(
        internal,
        query=query,
        authorized_field_labels=authorized_fields,
        dataset_names_zh=dataset_names_zh,
        dataset_summaries_zh=dataset_summaries_zh,
    )
    # P0-3 二段收敛：待权限枚举时经注入 enum_fn 自动枚举并回灌重规划。
    # 本次调用已执行过刷新时跳过（刷新与自动枚举不在同一次调用叠加，
    # 此时输出内嵌枚举命令走手动路径，各调用均可快速返回）
    if (
        auto_enum
        and not internal.get("upgrade_performed_this_call")
        and not authorized_platform_values
        and internal.get("next_action") == "query_platform_permission_enum"
    ):
        values = _auto_enum_platform_values(
            enum_fn,
            contract["execution_ref"].get("platform_component_table_id"),
        )
        if values:
            internal = build_query_plan(
                adapter,
                query,
                requested_fields=requested_fields,
                authorized_platform_values=values,
                rules=rules,
                top_n=top_n,
                refresh_fn=None,
            )
            contract = build_model_contract(
                internal,
                query=query,
                authorized_field_labels=authorized_fields,
                dataset_names_zh=dataset_names_zh,
                dataset_summaries_zh=dataset_summaries_zh,
            )
            # 枚举来源标注：审计可区分自动枚举与人工回传
            contract["execution_ref"]["platform_enum_source"] = "auto_enum_service"
    contract = _resolve_component_filters(
        contract, query, enum_fn, auto_enum=auto_enum, adapter=adapter
    )
    contract = _attach_fallback_guidance(contract)
    # planned 合同生成后立即封存，执行器据此拒绝规划与执行之间的手工改写。
    if contract.get("status") == "planned" and contract.get("query_mode") == "dataset_query":
        plan_integrity.attach(contract)
    # 模型规划器体积守卫：新增投影（模板/组件/时间规划器）不得撑爆模型上下文
    if len(json.dumps(contract, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("query_plan_output_too_large")
    return contract


def _auto_enum_platform_values(enum_fn, component_table_id: object) -> list[str]:
    """经注入的 enum_fn 枚举平台权限值，返回去重后的平台值列表（P0-3）。

    enum_fn 未注入、组件 table_id 缺失或枚举失败时都返回空列表，
    回落到规划器内嵌的手动枚举命令路径，绝不阻塞。enum_fn 签名：
    enum_fn(table_id, field_name, *, limit) -> list[str]（上层封装内核 simple 查询）。
    """
    if enum_fn is None or component_table_id in (None, ""):
        return []
    try:
        values = enum_fn(component_table_id, "platform_name", limit=100)
    except Exception:  # noqa: BLE001 枚举失败不阻塞，回落手动枚举命令路径
        return []
    return _deduplicate(str(value).strip() for value in values or [] if str(value).strip())


def _auto_enum_component_values(
    enum_fn,
    component_table_id: object,
    field_name: str,
    errors: list[str] | None = None,
) -> list[str]:
    """经注入的 enum_fn 枚举普通筛选组件字段值；任何异常返回空列表，由合同阻断扩大查询。

    Args:
        errors: 可选出参，传入列表时把枚举调用自身的异常摘要 append 进去。
            调用方据此区分「调用失败」（如组件表未暴露该字段，属配置故障，重试无用）
            与「调用成功但无授权值」（可重试/确属无权限），避免一律建议原样重试
            导致调用方徒劳重试。不传时行为与既有完全一致（向后兼容）。
    """
    if enum_fn is None or component_table_id in (None, "") or not field_name:
        return []
    try:
        values = enum_fn(component_table_id, field_name, limit=500)
    except Exception as exc:  # noqa: BLE001 枚举失败不阻塞，交由合同阻断
        if errors is not None:
            errors.append(f"{type(exc).__name__}: {exc}"[:200])
        return []
    return _deduplicate(str(value).strip() for value in values or [] if str(value).strip())


# ── 组件筛选值解析（部门/渠道走授权枚举，ASIN 走字面格式）──────────────────
# ASIN/商品ID 字面形态：宽松切词后再逐个判形，不能写死单一形态。
# 实测该列并非只存标准 Amazon ASIN：TEMU 渠道存的是 10~11 位纯数字商品 ID，
# 另见 14 位纯数字；图书 ASIN 则是 ISBN-10。写死 B0+8 位会漏掉这些值，
# 而漏掉的后果与不解析筛选值一样——静默返回全范围数据。
# 长度下限取 9，避开年份、数量、limit 这类普通数字。
_ASIN_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Za-z]{9,20}(?![0-9A-Za-z])")


def _is_asin_like(token: str) -> bool:
    """判断切出的 token 是否为商品 ID 形态。"""
    value = token.upper()
    if re.fullmatch(r"B[0-9A-Z]{9}", value):  # 标准 Amazon ASIN：B + 9 位
        return True
    if value.isdigit():  # 各平台数字商品 ID（TEMU 实测 10/11/14 位）
        return True
    # 10 位字母数字混合（须同时含字母与数字，避免吃掉纯英文单词）
    return (
        len(value) == 10
        and value.isalnum()
        and any(char.isdigit() for char in value)
        and any(char.isalpha() for char in value)
    )


def _extract_asin_values(query: str) -> list:
    """从原文提取商品 ID 字面值，统一转大写（授权原值恒为大写）。"""
    normalized = unicodedata.normalize("NFKC", query)
    return _deduplicate(
        token.upper() for token in _ASIN_TOKEN_RE.findall(normalized) if _is_asin_like(token)
    )


def _normalize_component_value(value: str) -> str:
    """组件值归一化：NFKC + 去空白 + casefold，与 filter_value_match_policy 声明一致。"""
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def _extract_labeled_value(query: str, label_terms: Sequence[str]) -> str:
    """按「字段名 + 系词 + 值」形态提取筛选值，适用于全部组件字段。

    系词是必需的：没有它，「渠道和ASIN」这类维度点名会被当成筛选值。
    标签按长度降序尝试，避免「渠道」抢先匹配掉「渠道SKU」。
    值用非贪婪 + 边界前瞻收住，否则「渠道是傲彼瑞的所有ASIN」会整段被吞。
    """
    for term in sorted(label_terms, key=len, reverse=True):
        pattern = re.compile(
            re.escape(term)
            + r"\s*(?:为|是|=|＝|：|:|等于)\s*"
            + r"([\u4e00-\u9fffA-Za-z0-9_\-\.]{2,40}?)"
            + r"(?=的|地|，|,|。|；|;|、|\s|和|与|下|里|中|所有|全部|$)",
            re.IGNORECASE,
        )
        match = pattern.search(query)
        if match:
            return match.group(1).strip()
    return ""


def _extract_patterned_value(query: str, pattern: str) -> str:
    """按编码形态从原文抽裸值（SKU/型号/物控编码/SPU 这类有固定长相的字段）。

    形态命中只当候选，仍要走枚举完整等值校验；命中不了不代表没有筛选意图，
    因此不能据此放行——高基数字段的裸值兜底属已知残留，见 SKILL.md 降级章节。
    """
    match = re.search(pattern, unicodedata.normalize("NFKC", query))
    return match.group(0).strip() if match else ""


def _spec_extract(spec: dict, query: str, *, labeled_only: bool = False, consumed=()) -> str:
    """按 spec 配置抽取该字段的筛选值：自定义抽取器 > 标签形态 > 编码形态。

    labeled_only=True 时只认用户显式点名的形态。解析分两趟正是为此：
    第一趟先把「渠道SKU是X」这类显式意图落实并登记 X 已被消费，第二趟才轮到
    形态抽取与枚举反查。否则同一个值会被多个字段重复消费——实测
    「渠道SKU是ON-OB-JL-007-68157」会被产品型号的形态正则再抢一次并误报澄清，
    「品牌是OHWILL」会被渠道反查匹配到 ohwill-shopify-美国而多加一条渠道筛选。
    """
    custom = spec.get("extract")
    if custom is not None:
        return custom(query)
    value = _extract_labeled_value(query, spec.get("label_terms") or ())
    if value:
        return value
    if labeled_only:
        return ""
    pattern = spec.get("value_pattern")
    if not pattern:
        return ""
    candidate = _extract_patterned_value(query, pattern)
    normalized = _normalize_component_value(candidate)
    # 已消费值的子串也要跳过：SPU 的形态会从渠道SKU「ON-OB-JL-007-68157」里
    # 抠出「JL-007」，若不拦就会对同一个值二次澄清并撤掉已生成的模板
    if normalized and any(
        normalized == used or normalized in used for used in consumed
    ):
        return ""
    return candidate


def _value_already_consumed(normalized_value: str, consumed) -> bool:
    """判断某个枚举值是否已被其他字段消费（整值相同或是已消费值的一部分）。"""
    if not normalized_value:
        return True
    base = normalized_value.split("-")[0]
    return any(
        normalized_value == used or normalized_value in used or base == used
        for used in consumed
    )


def _reverse_lookup_component_values(query: str, values: list, normalize) -> list:
    """用授权枚举原值反查原文，返回全部候选。

    为什么需要：用户常直接说「查傲彼瑞的所有ASIN」，原文根本不含「渠道」二字，
    标签正则抽不到值，会被当成没有筛选意图而放行——这正是静默返回全渠道数据的成因。
    这里反过来拿当前账号的授权原值去原文里找，原值本身或其主段（连字符前）
    出现即算候选，「傲彼瑞」因此能同时命中「傲彼瑞-美国」「傲彼瑞-加拿大」并转澄清。
    """
    normalized_query = normalize(query)
    exact_hits, base_hits = [], []
    for value in values:
        norm = normalize(value)
        if not norm:
            continue
        if norm in normalized_query:
            exact_hits.append(value)
            continue
        base = norm.split("-")[0]
        if len(base) >= 2 and base in normalized_query:
            base_hits.append(value)
    # 整值命中优先：原文写了「傲彼瑞-加拿大」就该锁定它，而不是因为主段
    # 「傲彼瑞」同时命中三个地区渠道而退化成澄清
    return _deduplicate(exact_hits or base_hits)


def _shared_prefix(values: list) -> str:
    """多候选时取共同前缀作回显（「傲彼瑞-美国」「傲彼瑞-加拿大」→「傲彼瑞」）。"""
    if not values:
        return ""
    prefix = str(values[0])
    for value in values[1:]:
        while prefix and not str(value).startswith(prefix):
            prefix = prefix[:-1]
    return prefix.rstrip("-_ ") or str(values[0])



# 组件筛选字段总表（值类字段，date_id 归时间口径、platform_name 归平台范围逻辑）。
#
# 三个开关的取舍依据是实测基数与裸值出现概率：
# - label_terms：标签形态抽取用的说法集合，命中标签才发起枚举，零额外网络成本。
# - reverse_lookup：拿授权枚举原值反查原文，用于兜住不带字段名的裸值
#   （「查傲彼瑞的ASIN」「查史子涵的销量」）。只给低基数字段开——实测渠道 9、
#   国家 2、品牌 3、销售 12，枚举一次就能覆盖全集；SKU/产品名这类几百上千的
#   字段开反查既慢又不可能枚举完整，改用形态抽取。
# - value_pattern：编码型字段的裸值形态，抽到候选后仍要枚举校验权限。
_ENUM_COMPONENT_SPECS = (
    {
        "field_name": "dept_name",
        "label_zh": "部门",
        "extract": _extract_requested_department_value,
        "normalize": _normalize_department_value,
        "reverse_lookup": False,
    },
    {
        "field_name": "channel_name",
        "label_zh": "渠道",
        "label_terms": ("渠道", "channel", "channel_name"),
        "reverse_lookup": True,
    },
    {
        "field_name": "country_name",
        "label_zh": "国家",
        "label_terms": ("国家", "站点", "country", "country_name"),
        "reverse_lookup": True,
    },
    {
        "field_name": "brand_name",
        "label_zh": "品牌",
        "label_terms": ("品牌", "brand", "brand_name"),
        "reverse_lookup": True,
    },
    {
        "field_name": "team_username",
        "label_zh": "销售",
        "label_terms": ("销售员", "销售负责人", "销售", "team_username"),
        "reverse_lookup": True,
    },
    {
        "field_name": "develop_username",
        "label_zh": "开发",
        "label_terms": ("开发员", "开发负责人", "开发", "develop_username"),
        "reverse_lookup": True,
    },
    {
        "field_name": "team_name",
        "label_zh": "销售小组",
        "label_terms": ("销售小组", "小组", "team_name"),
        "reverse_lookup": True,
    },
    {
        "field_name": "large_team_name",
        "label_zh": "大组",
        "label_terms": ("大组", "large_team_name"),
        "reverse_lookup": True,
    },
    {
        "field_name": "category",
        "label_zh": "品类",
        "label_terms": ("品类", "category"),
        "reverse_lookup": False,
    },
    {
        "field_name": "amazon_cat",
        "label_zh": "平台类目",
        "label_terms": ("平台类目", "类目", "amazon_cat"),
        "reverse_lookup": False,
    },
    {
        "field_name": "sell_sku",
        "label_zh": "渠道SKU",
        "label_terms": ("渠道sku", "卖家sku", "sell_sku", "sellsku"),
        # 形如 ON-OB-JL-007-68157：字母数字段以连字符相连，至少三段
        "value_pattern": r"[A-Za-z0-9]{2,}(?:-[A-Za-z0-9]{2,}){2,}",
        "reverse_lookup": False,
    },
    {
        "field_name": "ed_sku",
        "label_zh": "公司SKU",
        "label_terms": ("公司sku", "ed_sku", "edsku"),
        # 形如 USAN1051789WF：纯字母数字混合且长度较长
        "value_pattern": r"[A-Z]{2,}[0-9]{4,}[A-Z0-9]*",
        "reverse_lookup": False,
    },
    {
        "field_name": "model",
        "label_zh": "产品型号",
        "label_terms": ("产品型号", "型号", "model"),
        # 形如 COT-135-WA
        "value_pattern": r"[A-Za-z]{2,}-[A-Za-z0-9]{2,}(?:-[A-Za-z0-9]{1,})*",
        "reverse_lookup": False,
    },
    {
        "field_name": "pmc_code",
        "label_zh": "物控编码",
        "label_terms": ("物控编码", "物控码", "pmc_code", "pmc"),
        # 形如 32.002946
        "value_pattern": r"[0-9]{2,}\.[0-9]{4,}",
        "reverse_lookup": False,
    },
    {
        "field_name": "spu",
        "label_zh": "SPU",
        "label_terms": ("spu",),
        # 形如 BKC-107
        "value_pattern": r"[A-Z]{2,}-[0-9]{2,}",
        "reverse_lookup": False,
    },
    {
        "field_name": "product_name",
        "label_zh": "产品名称",
        "label_terms": ("产品名称", "商品名称", "product_name"),
        "reverse_lookup": False,
    },
)


def _component_of(execution: dict, field_name: str) -> dict | None:
    """在合同的 filter_components 中查找指定字段的组件配置。"""
    return next(
        (
            item
            for item in execution.get("filter_components") or []
            if isinstance(item, dict) and item.get("field_name") == field_name
        ),
        None,
    )


def _lookup_component(
    execution: dict, field_name: str, adapter: MetadataAdapter | None
) -> dict | None:
    """查组件配置：优先用合同里的 filter_components，缺失时回落到全量组件表。

    为什么必须回落：filter_components 是按查询相关性排序后截断的，用户原文不含
    「渠道」二字时该组件会被裁掉——而裸值请求（「查傲彼瑞的所有ASIN」）恰恰是
    最需要枚举校验的场景，靠合同里的裁剪结果会漏掉。
    """
    hit = _component_of(execution, field_name)
    if hit:
        return hit
    dataset_alias = str(execution.get("dataset_alias") or "")
    if not dataset_alias or adapter is None:
        return None
    column = next(
        (
            row
            for row in adapter.select_columns_rows()
            if str(row.get("current_dataset_alias", "")) == dataset_alias
            and str(row.get("column_name", "")) == field_name
        ),
        None,
    )
    if not column:
        return None
    component_alias = str(column.get("component_dataset_alias", ""))
    table_id = next(
        (
            row.get("table_id", "")
            for row in adapter.datasets_rows()
            if str(row.get("dataset_alias", "")) == component_alias
        ),
        "",
    )
    if not table_id:
        return None
    return {
        "field_name": field_name,
        "label_zh": str(column.get("verbose_name", "")),
        "component_dataset_alias": component_alias,
        "component_table_id": table_id,
    }


def _dataset_has_field(
    execution: dict, field_name: str, adapter: MetadataAdapter | None
) -> bool:
    """判断已选数据集是否含指定字段（ASIN 字面筛选的前置条件）。"""
    dataset_alias = str(execution.get("dataset_alias") or "")
    if not dataset_alias or adapter is None:
        return False
    return any(
        str(row.get("dataset_alias", "")) == dataset_alias
        and str(row.get("field_name", "")) == field_name
        for row in adapter.fields_rows()
    )


def _block_component_filter(
    contract: dict, execution: dict, *, status: str, state: str, next_action: str, message_zh: str
) -> dict:
    """筛选值无法锁定时统一收口：撤下可执行模板并给出中文恢复指引。

    为什么必须撤模板：run_flow 在 status=planned 时会原样执行 query_template，
    而模板里没有用户要的筛选条件——放行等于把「查某渠道」悄悄变成「查全部渠道」，
    静默错数比查不到数据危险得多。这里一律 fail-closed。
    """
    contract["status"] = status
    contract["model_view"]["component_filter_state"] = state
    contract["model_view"]["next_action"] = next_action
    contract["model_view"].setdefault("clarification_messages_zh", []).append(message_zh)
    execution.pop("query_template", None)
    # 模板已撤下，填充说明再留着会让 Agent 去找一个不存在的模板
    execution.pop("query_template_fill_rules_zh", None)
    return contract


def _write_component_filter(
    contract: dict,
    execution: dict,
    *,
    field_name: str,
    label_zh: str,
    requested: str,
    resolved: str,
) -> None:
    """把已锁定的授权原值写入查询模板，并登记披露信息。"""
    template = execution.get("query_template")
    if not isinstance(template, dict):
        return
    template.setdefault("filters", []).append(
        {"field": field_name, "operator": "=", "value": resolved}
    )
    execution.setdefault("resolved_component_filters", []).append(
        {
            "field_name": field_name,
            "label_zh": label_zh,
            "requested_value": requested,
            "resolved_value": resolved,
            "match_strategy": "exact_normalized",
        }
    )
    contract["model_view"]["component_filter_state"] = "resolved"
    contract["model_view"].setdefault("component_filter_disclosures_zh", []).append(
        f"{label_zh}按当前账号授权枚举完整等值匹配为“{resolved}”。"
    )


def _resolve_enum_component_filter(
    contract: dict,
    query: str,
    spec: dict,
    enum_fn,
    *,
    auto_enum: bool,
    adapter: MetadataAdapter | None,
    enum_cache: dict,
    labeled_only: bool = False,
    consumed: set | None = None,
) -> dict:
    """把原文里的组件筛选值在当前账号授权枚举中唯一等值解析并写入模板。

    两条识别路径互补：标签形态（「渠道是傲彼瑞」）由 spec["extract"] 抽取；
    裸值形态（原文不含字段名）由授权枚举原值反查原文。任一环节无法唯一锁定
    都不放行：枚举调用失败 → blocked（配置类故障，重试无用时另给指引）；
    命中不唯一或零命中 → clarify_required。两种情况都撤下 query_template。
    """
    execution = contract.get("execution_ref")
    if not isinstance(execution, dict):
        return contract
    consumed = consumed if consumed is not None else set()
    field_name = spec["field_name"]
    label_zh = spec["label_zh"]
    # 该字段本趟之前已解析过就不再重复（两趟循环会把同一 spec 走两遍）
    if any(
        isinstance(item, dict) and item.get("field_name") == field_name
        for item in execution.get("resolved_component_filters") or []
    ):
        return contract
    requested = _spec_extract(spec, query, labeled_only=labeled_only, consumed=consumed)
    # 第一趟只落实用户显式点名的字段，反查与形态抽取留到第二趟
    if labeled_only and not requested:
        return contract
    # 只认标签形态的字段原文没提就没有筛选意图，不必付出一次枚举调用
    if not requested and not spec.get("reverse_lookup"):
        return contract
    component = _lookup_component(execution, field_name, adapter)
    if not component:
        return contract

    enum_errors: list[str] = []
    # 同一次规划里同一 (表, 字段) 只枚举一次；内核走进程内调用，
    # 不像 Skill 版需要按组件表合并 subprocess 调用
    cache_key = (str(component.get("component_table_id")), field_name)
    if not auto_enum:
        values = []
    elif cache_key in enum_cache:
        values = enum_cache[cache_key]
    else:
        values = _auto_enum_component_values(
            enum_fn, component.get("component_table_id"), field_name, enum_errors
        )
        enum_cache[cache_key] = values
        enum_cache[("error", *cache_key)] = list(enum_errors)
    if cache_key in enum_cache and not enum_errors:
        enum_errors = list(enum_cache.get(("error", *cache_key)) or [])
    if not values and not requested and not enum_errors:
        # 枚举成功但当前账号无授权值：该字段不可能成为筛选条件，跳过即可。
        # 「开发」在部分账号下就是 0 条，若按失败阻断会把所有查询挡死。
        return contract
    if not values:
        shown = f"“{requested}”" if requested else ""
        if enum_errors:
            # 枚举调用自身报错（实测形态：组件表元数据未暴露该字段，后端报「字段不存在」）。
            # 属配置类故障，重试多少次都不会成功，必须如实告知并透出原始错误。
            return _block_component_filter(
                contract,
                execution,
                status="blocked",
                state="enum_failed",
                next_action="report_component_enum_defect",
                message_zh=(
                    f"{label_zh}{shown}的授权枚举调用失败（{enum_errors[0]}），"
                    "重试无效——通常是该筛选组件的元数据配置异常，请提交反馈由平台侧核查；"
                    "已阻止扩大为全范围查询。"
                ),
            )
        return _block_component_filter(
            contract,
            execution,
            status="blocked",
            state="enum_unavailable",
            next_action="retry_component_permission_enum",
            message_zh=(
                f"当前未能枚举{label_zh}{shown}的授权原值，"
                "已阻止扩大为全范围查询；请原样重试一次。"
            ),
        )

    # 未单独声明归一化的字段走通用规则（NFKC + trim + casefold）；
    # 部门有中文数字等价这类特殊口径，才单独挂自己的归一化器
    normalize = spec.get("normalize") or _normalize_component_value
    if requested:
        target = normalize(requested)
        matched = [value for value in values if normalize(value) == target]
    else:
        matched = [
            value
            for value in _reverse_lookup_component_values(query, values, normalize)
            # 已被其他字段消费掉的值（含其子串）不再算命中：
            # 「品牌是OHWILL」不该连带匹配渠道 ohwill-shopify-美国；
            # 渠道锁定「傲彼瑞-加拿大」后，其中的「加拿大」也不该再被国家反查抓走
            if not _value_already_consumed(normalize(value), consumed)
        ]
        if not matched:
            return contract
        requested = matched[0] if len(matched) == 1 else _shared_prefix(matched)

    if len(matched) != 1:
        # 零命中时用包含关系找近似成员，让用户直接从可见成员里挑，省一轮往返
        approx = matched or [
            value
            for value in values
            if normalize(requested) and normalize(requested) in normalize(value)
        ]
        hint = "、".join(f"“{value}”" for value in approx[:8]) if approx else ""
        return _block_component_filter(
            contract,
            execution,
            status="clarify_required",
            state="clarify_required",
            next_action="ask_user_for_component_filter",
            message_zh=(
                f"{label_zh}“{requested}”没有唯一完整等值的授权成员，"
                + (f"当前账号可见的近似成员：{hint}；" if hint else "")
                + f"请指定当前账号可见的准确{label_zh}名称。"
            ),
        )

    _write_component_filter(
        contract,
        execution,
        field_name=field_name,
        label_zh=label_zh,
        requested=requested,
        resolved=matched[0],
    )
    consumed.add(_normalize_component_value(requested))
    consumed.add(_normalize_component_value(matched[0]))
    return contract


def _resolve_asin_filter(
    contract: dict, query: str, adapter: MetadataAdapter | None
) -> dict:
    """商品 ID 直接从原文字面锁定，不走枚举。

    为什么不枚举：ASIN/商品 ID 基数几万起，500 条枚举覆盖不了，也太慢。
    代价是只能靠形态识别，认错时查询返回 0 行（响亮失败），
    比认不出而静默返回全范围数据安全。
    """
    execution = contract.get("execution_ref")
    if not isinstance(execution, dict):
        return contract
    if not _dataset_has_field(execution, "asin", adapter):
        return contract
    asins = _extract_asin_values(query)
    if not asins:
        return contract
    template = execution.get("query_template")
    if not isinstance(template, dict):
        return contract
    condition = (
        {"field": "asin", "operator": "=", "value": asins[0]}
        if len(asins) == 1
        else {"field": "asin", "operator": "in", "value": asins}
    )
    template.setdefault("filters", []).append(condition)
    execution.setdefault("resolved_component_filters", []).append(
        {
            "field_name": "asin",
            "label_zh": "ASIN",
            "requested_value": "、".join(asins),
            "resolved_value": asins[0] if len(asins) == 1 else asins,
            "match_strategy": "asin_literal_format",
        }
    )
    contract["model_view"].setdefault("component_filter_disclosures_zh", []).append(
        f"商品 ID 按原文字面锁定为 {'、'.join(asins)}。"
    )
    return contract


def _attach_fallback_guidance(contract: dict) -> dict:
    """非 planned 合同补降级信息：权威字段目录 + 禁止猜测声明。

    为什么需要：规划器没产出可执行模板时，Agent 手上若没有权威的表名与字段名，
    就会凭记忆或推测构造查询（线上实测形态：转投其他 Skill、或直接改用 MCP 重来，
    过程中自行编造数据集与字段）。这里把「唯一可用的字段来源」显式交给它。

    只补信息、不改状态：澄清与阻断的判定仍由各自的规则负责。
    """
    if contract.get("status") == "planned":
        return contract
    if contract.get("query_mode") != "dataset_query":
        return contract
    execution = contract.get("execution_ref")
    model_view = contract.get("model_view")
    if not isinstance(execution, dict) or not isinstance(model_view, dict):
        return contract

    def _names(items) -> list:
        return [
            {
                "field_name": str(item.get("field_name", "")),
                "label_zh": str(item.get("label_zh", "")),
            }
            for item in items or []
            if isinstance(item, dict) and item.get("field_name")
        ]

    dimensions = _names(execution.get("dimensions"))
    metrics = _names(execution.get("metrics"))
    date_fields = _names(execution.get("date_fields"))
    has_catalog = bool(dimensions or metrics)
    catalog = {
        "source": "planner_contract" if has_catalog else "unavailable",
        "metadata_version": str(contract.get("metadata_version", "")),
        "table_id": execution.get("table_id"),
        "dataset_alias": execution.get("dataset_alias"),
        "dimensions": dimensions,
        "metrics": metrics,
        "date_fields": date_fields,
    }
    execution["fallback_catalog"] = catalog
    model_view["fallback_level"] = "L1_contract_catalog" if has_catalog else "L3_metadata_refresh"
    model_view["no_guess_policy_zh"] = (
        "本次未下发可执行模板。若要继续取数，只能使用 execution_ref.fallback_catalog 中"
        "出现的 table_id、dataset_alias 与 field_name；禁止凭记忆或推测编造数据集名、"
        "字段名与枚举值。目录为空时不得构造任何查询，先按 next_action 恢复元数据。"
    )
    return contract


def _resolve_component_filters(
    contract: dict,
    query: str,
    enum_fn,
    *,
    auto_enum: bool,
    adapter: MetadataAdapter | None = None,
) -> dict:
    """解析原文中的组件字段筛选值（部门/渠道走授权枚举，ASIN 走字面格式）。

    只在 planned 的数据集查询上生效；任一字段无法唯一锁定即撤下模板，
    避免 run_flow 执行不含用户筛选条件的「骨架」。
    """
    if contract.get("status") != "planned":
        return contract
    contract = _resolve_asin_filter(contract, query, adapter)
    enum_cache: dict = {}
    consumed: set = set()
    # 两趟：先落实用户显式点名的字段并登记已消费的值，再做形态抽取与枚举反查
    for labeled_only in (True, False):
        for spec in _ENUM_COMPONENT_SPECS:
            if contract.get("status") != "planned":
                break
            contract = _resolve_enum_component_filter(
                contract,
                query,
                spec,
                enum_fn,
                auto_enum=auto_enum,
                adapter=adapter,
                enum_cache=enum_cache,
                labeled_only=labeled_only,
                consumed=consumed,
            )
    return contract
