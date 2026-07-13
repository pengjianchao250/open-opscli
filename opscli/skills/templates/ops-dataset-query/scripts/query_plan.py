#!/usr/bin/env python3
"""查询规划组合入口：一次调用产出选表、字段与权限规划合同。

流程：版本检查 → 规则校验 → 构建授权卡片 → 选表 → 字段指导
→ 平台权限枚举解析 → 投影为模型可见合同（model contract）。

输出两层合同：
- 内部合同 query_plan_contract_v1（--output-mode internal，仅维护者排错用）；
- 模型合同 query_plan_model_contract_v2（默认输出，Agent 只消费这一层）。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

import agent_query_planner as planner
import dataset_guidance
import scoped_dataset_reader
import typed_schema_linking as schema


INTERNAL_CONTRACT = "query_plan_contract_v1"
MODEL_CONTRACT = "query_plan_model_contract_v2"
SKILL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SKILL_DIR / "data"
RULES_PATH = DATA_DIR / "intent_rules.json"
MAX_OUTPUT_BYTES = 12000

# 澄清原因代码 → 面向用户的中文澄清话术
CLARIFICATION_MESSAGES = {
    "dataset_constraints": "需要先澄清并确认满足所需业务范围、维度和指标的数据集。",
    "dataset_identity": "需要先确认要查询的数据集。",
    "platform_scope": "需要先确认平台范围。",
    "ad_type": "需要先确认广告类型。",
    "grain": "需要先确认查询粒度。",
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
]


def _load_json_object(path: Path, error_code: str) -> dict:
    """加载 JSON 对象文件，任何读取/解析失败都归一为带错误码的 RuntimeError。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(error_code) from error
    if not isinstance(value, dict):
        raise RuntimeError(error_code)
    return value


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


# ---------------------------------------------------------------------------
# 内部合同：平台权限枚举解析
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
            "missing_semantic_members": [],
        }
    if authorized_values is None:
        return {
            "status": "required",
            "resolved_filter_values": [],
            "resolved_values_are_authorized": False,
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
        "missing_semantic_members": missing,
        "ambiguous_values": ambiguous_values,
    }


def _platform_scope(
    selection: dict,
    rules: dict,
    authorized_platform_values: Sequence[str] | None,
) -> dict:
    """构建请求的平台范围合同。

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


def _platform_component_lookup(data_dir: Path, dataset_alias: str, query: str) -> dict:
    """定位平台筛选字段对应的权限枚举组件数据集（alias 与 table_id）。

    任何一步不满足（无 platform_name 筛选字段、组件未授权等）
    都归一为 guidance_status=unavailable，由上层阻断该筛选。
    """
    try:
        full = dataset_guidance.build_guidance(
            data_dir,
            {"dataset_alias": dataset_alias},
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
            data_dir,
            {"dataset_alias": component_alias},
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


def _refresh_contract(version: dict) -> dict:
    """data_state 未就绪时的刷新合同：要求先升级当前账号元数据。"""
    return {
        "contract": INTERNAL_CONTRACT,
        "query_execution_allowed": False,
        "data_state": str(version.get("data_state", "missing")),
        "metadata_version": str(version.get("version", "")),
        "selection": None,
        "selected_dataset_guidance": None,
        "requested_platform_scope": None,
        "next_action": "refresh_authorized_metadata",
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
        if lookup.get("guidance_status") != "permission_enum_only":
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
    query: str,
    requested_fields: Sequence[str] = (),
    authorized_platform_values: Sequence[str] | None = None,
    *,
    data_dir: Path = DATA_DIR,
    rules_path: Path = RULES_PATH,
    top_n: int = planner.MAX_CANDIDATES,
) -> dict:
    """一次调用产出完整的本地内部规划合同。

    data_state 不为 ready 时直接返回刷新合同，不做任何选表推断，
    保证规划永远建立在当前账号最新授权元数据之上。
    """
    data_dir = Path(data_dir)
    version = _load_json_object(data_dir / "VERSION.json", "invalid_version_file")
    if version.get("data_state") != "ready":
        return _refresh_contract(version)

    raw_rules = _load_json_object(Path(rules_path), "invalid_rules_file")
    rules = schema.validate_rules(raw_rules)
    cards = planner.load_authorized_cards(data_dir)
    selection = planner.plan_query(query, cards, rules, top_n)
    platform_scope = _platform_scope(
        selection, raw_rules, authorized_platform_values
    )
    guidance = None
    if selection["planner_status"] == "candidate_ready":
        candidates = selection.get("dataset_candidates", [])
        if candidates:
            guidance = dataset_guidance.build_guidance(
                data_dir,
                {"dataset_alias": candidates[0]["dataset_alias"]},
                query=query,
                requested_fields=requested_fields,
            )
            if platform_scope["requires_permission_enum_validation"]:
                platform_scope["component_lookup"] = _platform_component_lookup(
                    data_dir, candidates[0]["dataset_alias"], query
                )
    result = {
        "contract": INTERNAL_CONTRACT,
        "query_execution_allowed": False,
        "data_state": "ready",
        "metadata_version": str(version.get("version", "")),
        "selection": selection,
        "selected_dataset_guidance": guidance,
        "requested_platform_scope": platform_scope,
        "next_action": _next_action(selection, guidance, platform_scope),
    }
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("query_plan_output_too_large")
    return result


# ---------------------------------------------------------------------------
# 模型合同投影：只暴露模型规划与最终回答所需的最小字段集
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
        if source == "explicit" or (label and label in normalized_query):
            position = normalized_query.find(label) if label else len(normalized_query)
            selected.append((position, index, item))
    return [item for _position, _index, item in sorted(selected)]


def _longest_unique_labels(fields: Iterable[dict]) -> list[dict]:
    """标签去重并做最长标签吞并：被更长标签完全包含的短标签让位。

    例：查询同时命中"销售额"与"广告销售额"时只保留"广告销售额"，
    避免同一个文本片段产出两个字段结论。
    """
    unique = []
    labels = []
    for item in fields:
        label = _normalize(item.get("verbose_name"))
        if label and label not in labels:
            labels.append(label)
            unique.append(item)
    return [
        item
        for item in unique
        if not any(
            _normalize(item.get("verbose_name")) != other
            and _normalize(item.get("verbose_name")) in other
            for other in labels
        )
    ]


def _selected_fields(
    guidance: dict,
    query: str,
    authorized_field_labels: dict[str, list[str]],
) -> tuple[list[dict], list[dict]]:
    """确定模型可见的维度与指标列表。

    优先级：字段指导中的显式/原文命中字段 → 全量授权字段标签兜底
    （覆盖指导截断导致点名字段落选的情况）。维度与指标互相做
    包含吞并，避免"广告费"同时被当成维度和指标。
    """
    dimensions = _requested_fields(guidance, "dimensions", query)
    metrics = _requested_fields(guidance, "metrics", query)
    normalized_query = _normalize(query)
    if not dimensions:
        dimensions = [
            {"verbose_name": label, "selection_source": "authorized_query_label"}
            for label in authorized_field_labels.get("dimensions", [])
            if _normalize(label) in normalized_query
        ]
    if not metrics:
        metrics = [
            {"verbose_name": label, "selection_source": "authorized_query_label"}
            for label in authorized_field_labels.get("metrics", [])
            if _normalize(label) in normalized_query
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
        if not any(
            _normalize(item.get("verbose_name")) != dimension_label
            and _normalize(item.get("verbose_name")) in dimension_label
            for dimension_label in dimension_labels
        )
    ]
    return dimensions, metrics


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
    """把内部合同状态归一为模型合同三态：planned / clarify_required / blocked。"""
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


def _platform_filter_state(platform: dict) -> str:
    """归一平台筛选状态：未请求 / 待权限枚举 / 已解析 / 被阻断。"""
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
    """生成回答合同：最终回答必须覆盖的披露与禁止输出。"""
    required = []
    if platform_filter_state == "requires_permission_enum":
        required.append("permission_enum_required")
    if "dataset_constraints" in clarification_reasons:
        required.append("dataset_confirmation_required")
    if guidance.get("guidance_status") == "clarify_required":
        required.append("field_confirmation_required")
    if status == "blocked":
        required.append("blocked_reason_required")
    return {
        "required_disclosure_codes": _deduplicate(required),
        "required_disclosures_zh": [
            DISCLOSURE_MESSAGES[code]
            for code in _deduplicate(required)
            if code in DISCLOSURE_MESSAGES
        ],
        "forbidden_output_codes": [
            "english_dataset_key",
            "technical_identifier_as_business_reason",
            "permission_scope_without_enum_validation",
        ],
        "forbidden_outputs_zh": FORBIDDEN_OUTPUT_MESSAGES,
        "technical_identifiers_user_visible": False,
        "user_visible_language": "zh-CN",
    }


def build_model_contract(
    internal: dict,
    query: str = "",
    authorized_field_labels: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """把内部合同投影为模型可见的精简合同。

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
    platform_state = _platform_filter_state(platform)
    component = platform.get("component_lookup") or {}
    dimensions, metrics = _selected_fields(
        guidance, query, authorized_field_labels or {"dimensions": [], "metrics": []}
    )
    return {
        "contract": MODEL_CONTRACT,
        "data_state": str(internal.get("data_state", "missing")),
        "metadata_version": str(internal.get("metadata_version", "")),
        "status": status,
        "model_view": {
            "dataset_name_zh": str(dataset.get("display_name_zh", "")),
            "dimensions": _field_names(dimensions),
            "metrics": _field_names(metrics),
            "platform_semantic_members": [
                str(item) for item in platform.get("semantic_members", [])
            ],
            "platform_filter_state": platform_state,
            "clarification_reason_codes": clarification_reasons,
            "clarification_messages_zh": [
                CLARIFICATION_MESSAGES.get(code, "需要补充查询条件。")
                for code in clarification_reasons
            ],
            "next_action": str(internal.get("next_action", "")),
        },
        "answer_contract": _answer_contract(
            status, clarification_reasons, platform_state, guidance
        ),
        "execution_ref": {
            "user_visible": False,
            "dataset_alias": dataset.get("dataset_alias"),
            "table_id": dataset.get("table_id"),
            "platform_component_alias": component.get("component_dataset_alias"),
            "platform_component_table_id": component.get("component_table_id"),
            "resolved_platform_values": resolution.get("resolved_filter_values", []),
            "dimensions": _execution_fields(dimensions),
            "metrics": _execution_fields(metrics),
        },
    }


def build_model_query_plan(
    query: str,
    requested_fields: Sequence[str] = (),
    authorized_platform_values: Sequence[str] | None = None,
    **kwargs,
) -> dict:
    """构建内部合同并投影为模型合同（组合入口的默认输出路径）。"""
    data_dir = Path(kwargs.get("data_dir", DATA_DIR))
    internal = build_query_plan(
        query,
        requested_fields=requested_fields,
        authorized_platform_values=authorized_platform_values,
        **kwargs,
    )
    # 收集全量授权字段中文标签，用于点名字段被指导截断时的兜底匹配
    authorized_fields = {"dimensions": [], "metrics": []}
    if internal.get("data_state") == "ready":
        rows = scoped_dataset_reader.load_dataset_fields(data_dir)
        for row in rows:
            key = "dimensions" if row["field_type"] == "dimension" else "metrics"
            label = str(row.get("verbose_name", ""))
            if label and label not in authorized_fields[key]:
                authorized_fields[key].append(label)
    return build_model_contract(
        internal,
        query=query,
        authorized_field_labels=authorized_fields,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """组合入口命令行参数。internal 输出模式仅供维护者排错。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--field", action="append", default=[])
    parser.add_argument("--authorized-platform-value", action="append")
    parser.add_argument("--top-n", type=int, default=planner.MAX_CANDIDATES)
    parser.add_argument(
        "--output-mode", choices=("model", "internal"), default="model"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        builder = (
            build_query_plan
            if args.output_mode == "internal"
            else build_model_query_plan
        )
        result = builder(
            args.query,
            requested_fields=args.field,
            authorized_platform_values=args.authorized_platform_value,
            top_n=args.top_n,
        )
    except (FileNotFoundError, LookupError, RuntimeError, TypeError, ValueError) as error:
        # 错误统一走 stderr 的紧凑 JSON，避免污染 stdout 的合同输出
        print(
            json.dumps(
                {"error": str(error) or type(error).__name__},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
