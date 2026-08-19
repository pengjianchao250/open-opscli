#!/usr/bin/env python3
"""查询规划器：一次调用产出选表、字段与权限规划结果。

流程：版本检查 → 规则校验 → 构建授权卡片 → 选表 → 字段指导
→ 平台权限枚举解析 → 投影为模型可见规划器（model contract）。

输出两层规划器：
- 内部规划器 query_plan_contract_v1（--output-mode internal，仅维护者排错用）；
- 模型规划器 query_plan_model_contract_v2（默认输出，Agent 只消费这一层）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Sequence

import agent_query_planner as planner
import core
import dataset_guidance
import enum_cache
import plan_integrity
import scoped_dataset_reader
import time_scope
import typed_schema_linking as schema


INTERNAL_CONTRACT = "query_plan_contract_v1"
MODEL_CONTRACT = "query_plan_model_contract_v2"
SKILL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SKILL_DIR / "data"
RULES_PATH = DATA_DIR / "intent_rules.json"
MAX_OUTPUT_BYTES = 24000

# 澄清原因代码 → 面向用户的中文澄清话术
CLARIFICATION_MESSAGES = {
    "dataset_constraints": "需要先澄清并确认满足所需业务范围、维度和指标的数据集。",
    "dataset_identity": "需要先确认要查询的数据集。",
    "platform_scope": "需要先确认平台范围。",
    "ad_type": "需要先确认广告类型。",
    "grain": "需要先确认查询粒度。",
    "field_identity": "点名字段对应多个同名物理字段，当前中文标签无法唯一绑定。",
    "time_scope_confirmation": "未识别到明确时间范围，需要确认是否使用默认近30天。",
    "recommended_fields_confirmation": "用户未点名完整字段，需要确认是否采用系统推荐字段。",
    "default_dataset_confirmation": "未明确指定数据集，建议使用已授权且兼容的即时综合数据集，需要确认是否采用。",
    "time_comparison_unsupported": "该数据集没有日期字段，无法按时间筛选，也无法做环比或同比。",
    # 兜底文案；实际会在合同层按「组件表」还是「同名冲突」替换成更具体的一句
    "business_dataset": "当前命中的是权限枚举组件或多个同名数据集，无法唯一确定业务数据集。",
}

# business_dataset 的两种具体成因。只给兜底文案时 Agent 只能看到
# 「需要补充查询条件」，既不知道组件表不能当业务结果集，也不知道存在同名冲突，
# 实测 7 张组件表在 14 个维度上全部卡死且被判为「澄清过度」。
BUSINESS_DATASET_MESSAGES = {
    "query_component": (
        "命中的是权限枚举组件数据集，只能用于查询筛选项的可选值，"
        "不能作为业务结果数据集取数。请改为指定一个业务数据集。"
    ),
    "name_conflict": (
        "当前账号内存在多个中文名完全相同的数据集，无法唯一确定要查哪一个。"
        "请按候选卡片中的同名序号或代表字段选择其一。"
    ),
}
# 阻断动作 → 面向用户的中文阻断原因。
# 为什么必须有：answer_contract 会强制要求「说明当前查询被阻断的原因」，
# 但合同里从来没有原因文本、没有 recovery_command、也不说当前账号实际授权了什么，
# Agent 只能泛泛而谈或违反 no-guess 政策去猜。要求解释却不提供解释材料，
# 是把披露义务变成了猜测诱因。
BLOCK_REASON_MESSAGES = {
    "block_platform_scope_unsupported": (
        "请求中的平台不在当前规划规则支持的平台范围内，无法构造平台筛选条件。"
    ),
    "block_platform_scope_not_authorized": (
        "当前账号的平台权限枚举中没有请求的平台，本次未执行查询。"
    ),
    "block_platform_filter_missing_component": (
        "该数据集没有可用的平台权限枚举组件，无法校验平台筛选值，本次未执行查询。"
    ),
    "block_platform_enum_ambiguous": (
        "平台权限枚举值同时命中多个平台语义，禁止猜测，本次未执行查询。"
    ),
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

# 错误码前缀 → (中文下一步指引, 是否直接原样重跑即可)。
# 为什么需要：错误只给紧凑错误码时，Agent 的自然行为是盲重试或翻脚本源码，
# 每个错误必须自带可执行的下一步动作才能截断探查螺旋（e2e 实测长尾主因之一）。
ERROR_NEXT_ACTIONS: list[tuple[str, str, bool]] = [
    (
        "metadata_snapshot_changed",
        "元数据快照在读取期间发生了变化（并发窗口），直接原样重跑本命令一次即可。",
        True,
    ),
    (
        "invalid_version_file",
        f"元数据版本文件损坏或缺失，执行 {METADATA_UPGRADE_COMMAND} 修复后重跑本命令。",
        False,
    ),
    (
        "invalid_rules",
        f"本地规划规则损坏，执行 {METADATA_UPGRADE_COMMAND} 修复后重跑本命令；"
        "仍失败时按 references/feedback-guide.md 提交一次反馈并停止重试。",
        False,
    ),
    (
        "invalid_cards",
        f"授权数据集卡片损坏，执行 {METADATA_UPGRADE_COMMAND} 修复后重跑本命令；"
        "仍失败时按 references/feedback-guide.md 提交一次反馈并停止重试。",
        False,
    ),
    (
        "missing_query_text",
        "缺少查询原文：把用户请求作为位置参数传入，或用 --query-file <文件|-> 传入。",
        False,
    ),
    (
        "query_too_long",
        "查询文本超长，请压缩为一句话核心诉求后重跑本命令。",
        False,
    ),
    (
        "query_plan_output_too_large",
        "规划器输出超限，请减少 --field 数量或调低 --top-n 后重跑本命令。",
        False,
    ),
    (
        "duplicate_dataset_field",
        "该数据集存在同名字段的冲突注册（执行语义不一致，v1.3.6 起语义一致的"
        "重复注册已自动合并），重跑与升级均无法自愈；向用户如实说明该数据集"
        "暂不可查，并按 references/feedback-guide.md 提交一次反馈后停止重试。",
        False,
    ),
    (
        "dataset_has_no_fields",
        "该数据集没有可用查询字段，向用户如实说明并建议更换数据集；"
        "如确认属元数据异常，按 references/feedback-guide.md 提交一次反馈。",
        False,
    ),
]
DEFAULT_ERROR_NEXT_ACTION = (
    f"先原样重跑本命令一次；仍失败则执行 {METADATA_UPGRADE_COMMAND} 后重试；"
    "再失败按 references/feedback-guide.md 提交一次反馈并停止盲试。"
)

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

# 宽后缀兜底正则：任意 1-6 个汉字/字母/数字紧跟「部」即视为部门名候选。
# 上限 6 取自内部真实部门名长度分布（最长如「经营管理团队」为 6 字，
# 带「部」后缀的更短）；放宽会把整句吞进候选。候选仍要走授权枚举完整
# 等值校验，零命中转澄清，因此宽进严出是安全的。
_DEPARTMENT_WIDE_SUFFIX_RE = re.compile(r"[一-鿿A-Za-z0-9]{1,6}部")

# 宽后缀候选头部的噪声前缀：正则按「最左 + 贪婪」匹配，会把紧邻的时间词、
# 祈使动词、连接助词一并吞进候选（「近7天魔法部」「查询销售部」），这里循环剥掉。
# 时间量词必须整段剥除（近7天/上月），不能单剥数字——「3C事业部」这类
# 以数字开头的真实部门名会被误伤。
_DEPARTMENT_NOISE_PREFIX_RE = re.compile(
    r"^(?:"
    # 数字时间跨度：近7天 / 30日 / 过去3个月
    r"(?:近|最近|过去)?\d+(?:天|日|周|个月|月|季度|年)"
    # 中文数字时间跨度：近七天 / 两周
    r"|(?:近|最近|过去)?[一二三四五六七八九十两]+(?:天|日|周|个月|月|季度|年)"
    # 相对时间词：本月 / 上周 / 去年
    r"|[本上下今昨明去前](?:天|日|周|月|季度|年|半年)"
    # 祈使/请求前缀
    r"|请|麻烦|帮我|帮忙|我想|我要|需要"
    # 常见取数动词（长词在前，避免「查询」只剥掉「查」）
    r"|查询|查一下|查下|查看|查|看看|看下|看|获取|拉取|统计|分析|对比|比较|汇总|导出|展示|给出|计算|一下"
    # 连接助词
    r"|的|地|和|与|及|或|在|按|把|给"
    r")"
)

# 宽后缀候选的停用词表：以「部」结尾但几乎不可能是部门名的常见词。
# 取值依据：范围词（全部/内部/外部/局部/大部/各部/多部）、方位词（东西南北中
# 与上下前后顶底头尾）、机构与职务惯用词（俱乐部/干部/总部）、商品描述里
# 高频出现的身体部位词（腰部按摩、颈部支撑等）。按「候选以停用词结尾」判定，
# 这样「按摩腰部」「近7天全部」这类带前缀噪声的候选也能被拦住。
# 停用词只抑制「未知候选转澄清」这一步；真实部门若恰好同名，仍会被授权枚举
# 反查原文（reverse_lookup）兜住，因此宁可多收，也不因误收而丢失真实筛选。
_DEPARTMENT_SUFFIX_STOPWORDS = (
    # 范围词
    "全部", "内部", "外部", "局部", "大部", "各部", "多部",
    # 方位词
    "东部", "西部", "南部", "北部", "中部",
    "上部", "下部", "前部", "后部", "顶部", "底部", "头部", "尾部", "根部",
    # 机构与职务惯用词
    "俱乐部", "干部", "总部",
    # 商品描述高频身体部位词
    "颈部", "肩部", "背部", "腰部", "腹部", "胸部", "臀部",
    "腿部", "膝部", "脚部", "足部", "手部", "腕部",
    "面部", "脸部", "眼部", "鼻部", "唇部", "耳部",
)

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


def _extract_wide_suffix_department_value(query: str) -> str:
    """宽后缀兜底：从「X部」形态中提取部门名候选。

    只在前三条窄规则（编号部门/显式标签/分析句式）都未命中时调用。
    候选返回后走既有「精确等值 → 零命中转澄清」链路：真实部门被枚举锁定，
    虚构部门（「魔法部」）转澄清，取代原先的静默放大为全量查询。
    """
    for match in _DEPARTMENT_WIDE_SUFFIX_RE.finditer(query):
        candidate = match.group(0)
        # 循环剥离候选头部的时间词/动词/助词噪声（「近7天魔法部」→「魔法部」）
        while True:
            noise = _DEPARTMENT_NOISE_PREFIX_RE.match(candidate)
            if not noise:
                break
            candidate = candidate[noise.end():]
        # 剥完只剩「部」或空，说明整个候选都是噪声
        if len(candidate) < 2:
            continue
        # 以停用词结尾的候选（「全部」「按摩腰部」）不是部门名
        if candidate.endswith(_DEPARTMENT_SUFFIX_STOPWORDS):
            continue
        return candidate
    return ""


def _extract_requested_department_value(query: str) -> str:
    """从明确部门表达或“分析某组织的数据”中提取单个部门筛选值。"""
    number_match = _DEPARTMENT_NUMBER_RE.search(query)
    if number_match:
        return number_match.group(0)
    label_match = _DEPARTMENT_LABEL_RE.search(query)
    if label_match:
        return label_match.group(1)
    analysis_match = _DEPARTMENT_ANALYSIS_RE.search(query)
    if analysis_match:
        candidate = analysis_match.group(1)
        if not re.fullmatch(r"(?:本|上|下)?(?:月|周|季度|年)|近\d+(?:天|日)", candidate):
            return candidate
    # 第四条兜底：宽后缀「X部」候选。编号部门已被第一条正则截获，
    # 走到这里的候选要么是特殊名部门（孵化部），要么是虚构部门（魔法部），
    # 交给授权枚举等值校验分流：命中放行、零命中转澄清。
    return _extract_wide_suffix_department_value(query)


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
    *,
    query: str = "",
) -> dict:
    """构建请求的平台范围规划器。

    平台槽位值先经 platform_scope.members 展开为语义成员
    （例如 amazon → amazon_sc + amazon_vc）；不在 members 中的
    平台（如 walmart）展开为空，最终由 _next_action 判定为不支持。
    """
    slots = selection.get("slots", {}).get("platform", [])
    if not isinstance(slots, list):
        slots = []
    excluded_slots: list[str] = []
    for start, end in time_scope.negated_spans(query):
        negated_semantics = schema.extract_query_semantics(query[start:end], rules)
        excluded_slots.extend(
            negated_semantics.get("slots", {}).get("platform", [])
        )
    excluded_slots = _deduplicate(excluded_slots)
    slots = [slot for slot in slots if slot not in excluded_slots]
    members = rules["platform_scope"]["members"]
    excluded_members = {
        member for slot in excluded_slots for member in members.get(slot, [])
    }
    semantic_members = _deduplicate(
        [
            member
            for slot in slots
            for member in members.get(slot, [])
            if member not in excluded_members
        ]
    )
    return {
        "requested_slots": slots,
        "excluded_slots": excluded_slots,
        "excluded_semantic_members": sorted(excluded_members),
        "semantic_members": semantic_members,
        # 保留本次拿到的授权枚举原值：阻断时要把「当前账号实际能查哪些平台」
        # 作为可选项交给用户，否则 Agent 只能说「没权限」而给不出下一步
        "authorized_enum_values": [
            str(value).strip()
            for value in (authorized_platform_values or [])
            if str(value).strip()
        ],
        "requires_permission_enum_validation": bool(slots or excluded_slots),
        "permission_field": "platform_name" if slots or excluded_slots else "",
        "component_lookup": None,
        "enum_resolution": _resolve_platform_enum(
            semantic_members, authorized_platform_values, rules
        ),
        "authorization_rule": (
            "resolve_only_from_current_account_component_enum"
            if slots or excluded_slots
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


def _data_state_ready(version: dict, data_dir: Path) -> tuple[bool, str]:
    """判定元数据是否可用于规划，兼容两种 VERSION.json 形状。

    为什么需要兼容：技能广场发布包内的 VERSION.json 来自 BI 数据发布管线
    （形如 {"version":"v1.1.2","dataset_count":43,...}），没有 data_state 字段；
    若硬性要求 data_state=ready，发布包上的规划器会被无条件打回 blocked
    （2026-07-13 QA e2e 实测 14/14 次全部打回，导致二代管线完全失效）。

    返回 (是否就绪, 元数据来源标记)：
    - "skill_local"：模板/updater 形状，data_state 显式为 ready；
    - "published_bundle"：发布包形状（无 data_state 字段），以真实数据文件佐证就绪；
    - 其余返回 data_state 原值（placeholder/invalid 等），表示未就绪。
    """
    state = version.get("data_state")
    if state == "ready":
        return True, "skill_local"
    if state is None:
        # 无 data_state 字段的两种真实形状：
        # ① BI 发布管线形状（含 dataset_count）；② opscli skills upgrade 写入形状
        #（仅 name+version，2026-07-14 实测）。统一以「核心索引文件存在且含数据行」
        # 佐证就绪，防止把占位/空包（CSV 仅表头）误判为就绪
        try:
            dataset_count = int(version.get("dataset_count", 0))
        except (TypeError, ValueError):
            dataset_count = 0
        if dataset_count > 0 and _csv_has_rows(data_dir / "datasets.csv") and (
            data_dir / "dataset_fields.csv"
        ).is_file():
            return True, "published_bundle"
        if _csv_has_rows(data_dir / "datasets.csv") and _csv_has_rows(
            data_dir / "dataset_fields.csv"
        ):
            return True, "upgraded_local"
        return False, "missing"
    return False, str(state)


def _csv_has_rows(path: Path) -> bool:
    """CSV 是否含表头之外的数据行（只读前两行，不加载全文件）。"""
    try:
        with path.open(encoding="utf-8") as handle:
            next(handle, None)
            return next(handle, None) is not None
    except OSError:
        return False


def _fallback_ready_data_dir(primary: Path) -> Path | None:
    """主数据目录未就绪时，在 opscli 实际安装位置寻找已就绪的数据目录。

    沙箱实测（2026-07-14 v19 验收）：自动升级把最新数据写入 opscli 自己的
    skills 目录（恒为 cwd/.claude/skills），而挂载目录 .agents 是只读快照、
    不会被升级更新——升级明明成功、主目录却仍是占位。此时从候选位置
    接管已就绪的数据目录，完成沙箱内自愈。
    """
    candidates = [
        Path.cwd() / ".claude" / "skills" / "ops-dataset-query" / "data",
        Path.home() / ".claude" / "skills" / "ops-dataset-query" / "data",
    ]
    env_dir = os.getenv("OPSCLI_SKILLS_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser() / "ops-dataset-query" / "data")
    for candidate in candidates:
        try:
            if candidate.resolve() == primary.resolve():
                continue
        except OSError:
            continue
        version_path = candidate / "VERSION.json"
        if not version_path.is_file():
            continue
        try:
            version = _load_json_object(version_path, "invalid_version_file")
        except RuntimeError:
            continue
        ready, _source = _data_state_ready(version, candidate)
        if ready:
            print(f"[query_plan] 主数据目录未就绪，接管已就绪数据目录：{candidate}", file=sys.stderr)
            return candidate
    return None


# 自动升级前台宽限秒数：后端快时（实测 3~10s）一次调用内直接完成；
# 超出宽限则转后台续跑并立即返回，保证单次调用恒在平台命令窗口内。
# 取 8s（< SDK exec 工具默认 yield_time_ms=10000）：验收轮实测模型常不显式设
# 等待窗、沿用 10s 默认，若宽限也是 10s 会卡在临界点被外层窗口切断（48 次调用 2 次超时，
# 均为默认 10s 命令）；压到 8s 留出 ≥2s 安全边际，默认窗口下也能拿到 in_progress 返回。
_UPGRADE_GRACE_SECONDS = 8.0


def _upgrade_marker_path(data_dir: Path) -> Path:
    """后台升级进程的 pid 标记文件路径（按数据目录区分，落在系统临时目录）。"""
    import hashlib
    import tempfile

    digest = hashlib.md5(str(data_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"opsdq_upgrade_{digest}.pid"


def _pid_alive(pid: int) -> bool:
    """判断进程是否存活（0 号信号探测；权限异常按存活处理，宁可多等不误判）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _try_metadata_upgrade(*, data_dir: Path, grace_seconds: float = _UPGRADE_GRACE_SECONDS) -> str:
    """blocked 前的自动升级：前台短宽限 + 超时转后台续跑（30 秒窗口适配设计）。

    为什么这样设计（四轮 e2e 实测结论）：平台单条命令的有效等待硬顶约 30 秒
    （PTY 钳制，模型自设更大超时无效），而升级网络下载常需 30~60 秒——同步等待
    必然被窗口切断（曾实测把升级进程杀死在写文件中途，留下半写入数据）。
    改为：启动升级子进程 → 前台最多等 grace_seconds → 未完成则不杀进程、
    记录 pid 标记后立即返回，升级在后台继续；下次调用凭标记与就绪检查接管结果。

    Returns:
        "completed"    —— 升级已完成（本次调用可直接继续规划）；
        "in_progress"  —— 升级仍在后台进行（本次返回等待重跑提示）；
        "failed"       —— 升级进程退出且失败（返回手动恢复指引）；
        "unavailable"  —— opscli 不可用（返回手动恢复指引）。
    """
    marker = _upgrade_marker_path(data_dir)
    # 前一次调用遗留的后台升级：存活则继续等它，消亡则清理标记按新一轮处理
    try:
        if marker.exists():
            previous_pid = int(marker.read_text(encoding="utf-8").strip() or "0")
            if previous_pid and _pid_alive(previous_pid):
                print(f"[query_plan] 后台元数据刷新进行中（pid={previous_pid}）", file=sys.stderr)
                return "in_progress"
            marker.unlink(missing_ok=True)
    except (OSError, ValueError):
        marker.unlink(missing_ok=True)

    try:
        # start_new_session：命令窗口结束后升级进程仍可在沙箱内继续运行
        process = subprocess.Popen(
            ["opscli", "skills", "upgrade", "ops-dataset-query", "--force"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        print(f"[query_plan] 自动升级不可用：{error}", file=sys.stderr)
        return "unavailable"
    try:
        returncode = process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            marker.write_text(str(process.pid), encoding="utf-8")
        except OSError:
            pass
        print(
            f"[query_plan] 元数据刷新已转后台续跑（pid={process.pid}），约 30 秒后重跑本命令即可",
            file=sys.stderr,
        )
        return "in_progress"
    if returncode == 0:
        print("[query_plan] 自动升级完成，使用刷新后的元数据继续规划", file=sys.stderr)
        return "completed"
    print(f"[query_plan] 自动升级失败（exit={returncode}）", file=sys.stderr)
    return "failed"


# recovery_state → (面向模型的中文恢复指引, 恢复命令)。
# in_progress/started 场景的恢复命令就是「等待后原样重跑」——用 sleep 前缀把
# 等待与重跑合并进一条命令，恰好贴着 30 秒窗口用满等待时间
_REFRESH_RECOVERY = {
    "refresh_in_progress": (
        "元数据刷新已在后台进行（无需任何升级动作）：等待约 25 秒后原样重跑本规划命令即可，"
        "可直接执行 recovery_command 一步完成等待与重跑；连续 3 次仍未就绪才按 "
        "references/feedback-guide.md 提交反馈并停止。",
        'sleep 25 && python3 scripts/query_plan.py "<原查询原文>"',
    ),
    "refresh_failed": (
        "自动刷新失败：手动执行 recovery_command 刷新后重跑本规划命令；"
        "仍失败时向用户如实说明元数据异常，并按 references/feedback-guide.md 提交一次反馈。",
        METADATA_UPGRADE_COMMAND,
    ),
}


def _refresh_contract(version: dict, recovery_state: str = "refresh_failed") -> dict:
    """data_state 未就绪时的刷新规划器输出：自带恢复状态与可执行恢复命令。

    规划器必须自带恢复命令原文：e2e 实测打回输出只有状态码时，
    Agent 无一按指引升级、全部弃管线退回旧探查流程。
    """
    hint, command = _REFRESH_RECOVERY.get(recovery_state, _REFRESH_RECOVERY["refresh_failed"])
    return {
        "contract": INTERNAL_CONTRACT,
        "query_execution_allowed": False,
        "data_state": str(version.get("data_state", "missing")),
        "metadata_version": str(version.get("version", "")),
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
    query: str,
    requested_fields: Sequence[str] = (),
    authorized_platform_values: Sequence[str] | None = None,
    *,
    data_dir: Path = DATA_DIR,
    rules_path: Path = RULES_PATH,
    top_n: int = planner.MAX_CANDIDATES,
    auto_upgrade: bool = True,
) -> dict:
    """一次调用产出完整的本地内部规划结果。

    元数据未就绪（见 _data_state_ready 的兼容判定）时先尝试一次自动升级，
    仍未就绪才返回刷新规划器、不做任何选表推断，
    保证规划永远建立在当前账号最新授权元数据之上。
    """
    data_dir = Path(data_dir)
    version = _load_json_object(data_dir / "VERSION.json", "invalid_version_file")
    ready, metadata_source = _data_state_ready(version, data_dir)
    upgrade_performed = False
    if not ready and auto_upgrade:
        # 先看后台升级是否已把数据写到 opscli 安装位置（上次调用转后台续跑的情形），
        # 就绪即接管，无需再等；自愈动作统一受 auto_upgrade 开关约束
        fallback_dir = _fallback_ready_data_dir(data_dir)
        if fallback_dir is not None:
            data_dir = fallback_dir
            version = _load_json_object(data_dir / "VERSION.json", "invalid_version_file")
            ready, metadata_source = _data_state_ready(version, data_dir)
            metadata_source = f"{metadata_source}+fallback_dir"
        if not ready:
            # 短宽限自动升级：完成→继续规划；后台续跑→立即返回等待重跑提示，
            # 保证本次调用恒在平台 30 秒命令窗口内返回
            state = _try_metadata_upgrade(data_dir=data_dir)
            upgrade_performed = True
            if state == "in_progress":
                return _refresh_contract(version, "refresh_in_progress")
            if state == "completed":
                version = _load_json_object(data_dir / "VERSION.json", "invalid_version_file")
                ready, metadata_source = _data_state_ready(version, data_dir)
                if not ready:
                    # 升级写入了 opscli 自身目录而主目录是只读挂载：接管就绪目录
                    fallback_dir = _fallback_ready_data_dir(data_dir)
                    if fallback_dir is not None:
                        data_dir = fallback_dir
                        version = _load_json_object(data_dir / "VERSION.json", "invalid_version_file")
                        ready, metadata_source = _data_state_ready(version, data_dir)
                        metadata_source = f"{metadata_source}+fallback_dir"
            # failed / unavailable 落到下方统一返回手动恢复指引
    if not ready:
        return _refresh_contract(version, "refresh_failed")

    raw_rules = _load_json_object(Path(rules_path), "invalid_rules_file")
    rules = schema.validate_rules(raw_rules)
    cards = planner.load_authorized_cards(data_dir)
    selection = planner.plan_query(query, cards, rules, top_n)

    def selected_guidance(current_selection: dict) -> dict | None:
        if current_selection.get("planner_status") != "candidate_ready":
            return None
        candidates = current_selection.get("dataset_candidates", [])
        if not candidates:
            return None
        return dataset_guidance.build_guidance(
            data_dir,
            {"dataset_alias": candidates[0]["dataset_alias"]},
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
            rules,
            top_n,
            recommend_default_dataset=False,
        )
        guidance = selected_guidance(selection)

    platform_scope = _platform_scope(
        selection,
        raw_rules,
        authorized_platform_values,
        query=query,
    )
    if selection["planner_status"] == "candidate_ready":
        candidates = selection.get("dataset_candidates", [])
        if candidates:
            if platform_scope["requires_permission_enum_validation"]:
                platform_scope["component_lookup"] = _platform_component_lookup(
                    data_dir, candidates[0]["dataset_alias"], query
                )
    result = {
        "contract": INTERNAL_CONTRACT,
        "query_execution_allowed": False,
        "data_state": "ready",
        # 元数据来源标记（skill_local / published_bundle / *+fallback_dir），供审计与排错区分形状
        "metadata_source": metadata_source,
        # 本次调用是否执行过自动升级：为守住 30 秒命令窗口，升级与自动枚举不在同一次调用内叠加
        "upgrade_performed_this_call": upgrade_performed,
        # 实际生效的数据目录：fallback 接管后与入参不同，投影层读取字段标签须以此为准
        "effective_data_dir": str(data_dir),
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
# 模型规划器投影：只暴露模型规划与最终回答所需的最小字段集
# ---------------------------------------------------------------------------


def _label_is_negated(normalized_query: str, label: str, negated: list) -> bool:
    """标签在原文中的每一次出现是否都落在否定语境区间内。

    为什么不能直接用原文匹配：标签匹配是子串包含，「不加日期筛选」里的「日期」
    会被当成用户点名的分组维度，于是用户越明确要求不加日期，规划器越确定
    按日期分组——实测 38 行的 ASIN 明细因此膨胀到 9625 行并触发服务端截断。

    为什么用区间包含而不是把否定语境替换掉：真实元数据里存在
    「周转天数(不含在途)」这类自带否定词的合法标签，替换会把标签撕开、
    使用户点名的字段反而漏掉。只有标签整体落在否定区间内才算否定，
    标签起点早于否定词时（自带否定词的情形）照常识别。
    否定词表复用 time_scope 的同一份，避免时间口径与字段标签两处判定漂移。
    """
    occurrences = [
        match.span() for match in re.finditer(re.escape(label), normalized_query)
    ]
    if not occurrences:
        return False
    return all(
        any(span_start <= start and end <= span_end for span_start, span_end in negated)
        for start, end in occurrences
    )


def _requested_fields(guidance: dict, field_type: str, query: str) -> list[dict]:
    """从字段指导结果中筛出用户真正点名的字段。

    只保留显式传参（selection_source=explicit）或中文名出现在
    查询原文中的字段，防止把打分兜底选出的字段当成用户诉求。
    """
    field_guidance = guidance.get("field_guidance") or {}
    fields = field_guidance.get(field_type) or []
    normalized_query = _normalize(query)
    # 否定语境区间：落在其中的标签不算用户点名（「不按日期拆分」里的「日期」）
    negated = time_scope.negated_spans(normalized_query)
    selected = []
    for index, item in enumerate(fields):
        if not isinstance(item, dict):
            continue
        source = item.get("selection_source")
        label = _normalize(item.get("verbose_name"))
        if source in {"explicit", "semantic_alias"} or (
            label
            and label in normalized_query
            and not _label_is_negated(normalized_query, label, negated)
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


def _label_spans(label: str, normalized_query: str) -> list[tuple[int, int]]:
    """标签在查询原文中的全部命中区间。"""
    spans = []
    start = normalized_query.find(label)
    while start >= 0:
        spans.append((start, start + len(label)))
        start = normalized_query.find(label, start + 1)
    return spans


def _is_swallowed(short: str, long: str, normalized_query: str) -> bool:
    """短标签是否只是长标签的一部分（同一段文本），而非用户另外说出的字段。

    判据是命中区间而不是字符串包含：只要短标签在原文里存在任何一次
    落在所有长标签区间之外的出现，就说明用户单独提过它，必须保留。
    """
    short_spans = _label_spans(short, normalized_query)
    if not short_spans:
        return True
    long_spans = _label_spans(long, normalized_query)
    if not long_spans:
        return False
    return all(
        any(ls <= ss and se <= le for ls, le in long_spans)
        for ss, se in short_spans
    )


def _longest_unique_labels(fields: Iterable[dict], normalized_query: str = "") -> list[dict]:
    """标签去重并做最长标签吞并：被更长标签完全包含的短标签让位。

    例：查询同时命中"销售额"与"广告销售额"时只保留"广告销售额"，
    避免同一个文本片段产出两个字段结论。

    但吞并必须限定在「同一段文本」内：用户写「花费(原币)和花费」时点名了两个字段，
    单纯按字符串包含判断会把 cost_cny（花费）整个丢掉，且 model_view.metrics
    也只报一个，用户无从察觉少了一半（矩阵实测 10/35 个多指标请求中招）。
    因此改为按命中区间判断——短标签只要在长标签区间之外还出现过，就说明是独立点名。
    normalized_query 为空时退回旧的纯包含判据（保持无原文场景的行为不变）。
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
            and (
                not normalized_query
                or _is_swallowed(
                    _normalize(item.get("verbose_name")), other, normalized_query
                )
            )
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
    # 授权标签兜底同样是子串包含，必须同样排除否定语境，否则
    # 「不按日期拆分」仍会从这条兜底路径把「日期」捞回来
    negated = time_scope.negated_spans(normalized_query)

    def _hit(item: dict) -> bool:
        label = _normalize(item.get("verbose_name"))
        return bool(
            label
            and label in normalized_query
            and not _label_is_negated(normalized_query, label, negated)
        )

    if not dimensions:
        dimensions = [
            dict(item, selection_source="authorized_query_label")
            for item in authorized_field_labels.get("dimensions", [])
            if _hit(item)
        ]
    if not metrics:
        metrics = [
            dict(item, selection_source="authorized_query_label")
            for item in authorized_field_labels.get("metrics", [])
            if _hit(item)
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
    dimensions = _longest_unique_labels(dimensions, normalized_query)
    metrics = _longest_unique_labels(metrics, normalized_query)
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


def _platform_scope_disclosures(platform: dict, *, blocked: bool = False) -> list[str]:
    """生成裸“亚马逊”默认范围及部分权限降级的强制披露。"""
    excluded = platform.get("excluded_semantic_members") or []
    if excluded:
        labels = [PLATFORM_MEMBER_LABELS.get(member, member) for member in excluded]
        return [f"已按用户要求排除{'、'.join(labels)}，未将排除项重新扩入查询范围。"]
    if "amazon" not in set(platform.get("requested_slots") or []):
        return []

    # 阻断态下「本次默认按 SC + VC 处理」是错的：本次根本没有处理，是被拦下了。
    # 这条完成态文案会让用户以为查询已按 SC+VC 执行，必须换成阻断口径。
    if blocked:
        return [
            "「亚马逊」按亚马逊SC + 亚马逊VC解释，但本次查询被阻断，未按该范围执行任何取数。"
        ]

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


def _clarification_message(
    code: str, selection: dict, dataset_names_zh: dict[str, str]
) -> str:
    """把澄清原因码翻成中文话术；business_dataset 按实际成因细分。

    business_dataset 同时承接「命中权限枚举组件」与「命中多个同名数据集」两种成因，
    共用一句笼统文案时 Agent 无从追问。成因可由候选卡片直接判定，不需要新增原因码。
    """
    if code != "business_dataset":
        return CLARIFICATION_MESSAGES.get(code, "需要补充查询条件。")
    candidates = selection.get("dataset_candidates") or []
    if any(item.get("dataset_category") == "query_component" for item in candidates):
        return BUSINESS_DATASET_MESSAGES["query_component"]
    names = [
        _normalize(dataset_names_zh.get(str(item.get("dataset_alias", "")), ""))
        for item in candidates
    ]
    names = [name for name in names if name]
    if len(names) != len(set(names)):
        return BUSINESS_DATASET_MESSAGES["name_conflict"]
    return CLARIFICATION_MESSAGES["business_dataset"]


def _candidate_cards_zh(
    selection: dict,
    dataset_names_zh: dict[str, str],
    dataset_summaries_zh: dict[str, str],
) -> list[dict]:
    """澄清态的候选卡片投影（P0-2）：中文名 + 命中原因，供带选项提问。

    同名候选必须带序号：账号内存在两张中文名完全相同的数据集时（实测
    「用户仪表盘分享明细」table_id 52/61），卡片的 name_zh 一模一样，
    Agent 无法构造「你要第 1 个还是第 2 个」这样的有效提问，14 个维度全部卡死。
    选表层早已算出 name_conflict 标记，但此前从未被消费。
    """
    cards = []
    candidates = (selection.get("dataset_candidates") or [])[:MAX_CANDIDATE_CARDS]
    name_counts: dict[str, int] = {}
    for item in candidates:
        key = _normalize(dataset_names_zh.get(str(item.get("dataset_alias", "")), ""))
        if key:
            name_counts[key] = name_counts.get(key, 0) + 1
    duplicate_seen: dict[str, int] = {}
    for item in candidates:
        alias = str(item.get("dataset_alias", ""))
        name_zh = dataset_names_zh.get(alias) or ""
        if not name_zh:
            continue
        key = _normalize(name_zh)
        total = name_counts.get(key, 0)
        display = name_zh
        if total > 1:
            index = duplicate_seen.get(key, 0) + 1
            duplicate_seen[key] = index
            display = f"{name_zh}（同名第 {index}/{total} 个）"
        card = {"name_zh": display, "reason_zh": _reason_zh(item.get("reasons") or [])}
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


# 全局币种白名单（大写 ISO 4217，与后端 dm_global_currencies 表种子一致）
SUPPORTED_GLOBAL_CURRENCIES = ["USD", "GBP", "CAD", "EUR", "JPY", "CNY"]

# 币种意图识别规则：仅匹配明确的币种词（避免 "元"、"$/¥" 等歧义符号误判）。
# CAD 置于 USD 之前，确保 "canadian dollar/加元" 不被 USD 的 "dollar" 抢先命中。
_CURRENCY_INTENT_PATTERNS = [
    ("CAD", ("cad", "加元", "加币", "加拿大元", "canadian dollar")),
    ("USD", ("usd", "美元", "美金", "美刀", "us dollar", "dollar")),
    ("GBP", ("gbp", "英镑", "pound", "sterling")),
    ("EUR", ("eur", "欧元", "euro")),
    ("JPY", ("jpy", "日元", "日币", "日圆", "yen")),
    ("CNY", ("cny", "rmb", "人民币", "人民幣")),
]


def _detect_global_currencies(query: str) -> list[str]:
    """按原文出现顺序识别全部币种意图，并去除关键词重叠与重复币种。

    ``canadian dollar`` 同时包含通用词 ``dollar``，必须优先保留更长的 CAD
    关键词，否则一次明确的加元请求会被误扩成 CAD + USD。用户要求“同时用加拿大元
    对比显示”时，业务语义是人民币主口径与加拿大元对照，即使原文省略“人民币”，
    也必须产出 CNY + CAD 两次服务端查询，不能拿单次结果做本地汇率换算。
    """
    if not query:
        return []
    text = str(query).lower()
    matches: list[tuple[int, int, int, str]] = []
    for code_order, (code, keywords) in enumerate(_CURRENCY_INTENT_PATTERNS):
        for keyword in keywords:
            start = text.find(keyword)
            while start >= 0:
                matches.append((start, start + len(keyword), code_order, code))
                start = text.find(keyword, start + 1)

    # 同起点先取更长关键词；随后排除与已选关键词区间重叠的短词。
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    occupied: list[tuple[int, int]] = []
    currencies: list[str] = []
    for start, end, _code_order, code in matches:
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        occupied.append((start, end))
        if code not in currencies:
            currencies.append(code)

    # 该中文表达中的“同时/对比显示”明确要求保留人民币主口径，再附加拿大元口径。
    cad_comparison = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in (
            r"(?:同时|一并|并列).{0,12}(?:加拿大元|加元|加币|cad)",
            r"(?:加拿大元|加元|加币|cad).{0,12}(?:对比显示|对照显示|并列显示|双币种)",
            r"双币种.{0,12}(?:加拿大元|加元|加币|cad)",
        )
    )
    if currencies == ["CAD"] and cad_comparison:
        return ["CNY", "CAD"]
    return currencies


def _detect_global_currency(query: str) -> str | None:
    """兼容单模板调用方，返回识别到的第一个服务端查询币种。"""
    currencies = _detect_global_currencies(query)
    return currencies[0] if currencies else None


# ---------------------------------------------------------------------------
# 排序与行数意图解析（Top N）
# ---------------------------------------------------------------------------
#
# 为什么必须由规划期做：模板的 orderBy/limit 曾恒为 None，而 SKILL.md 又规定
# Agent 不得改写模板、plan_integrity 摘要也把模板哈希绑死——三条规则叠加的结果是
# 「取前10名」在 CLI 主线上结构性不可能实现（矩阵实测 0/384 下发排序或行数）。
# 端到端表现为：用户要前 10 名，拿回全量 193 行按主键自然序，truncated=false，
# 且没有任何一处告诉用户 Top N 没生效。排序与行数是用户口径的一部分，
# 必须和表、字段、时间一样由规划器权威确定。

# 行数单位必须显式限定，否则「前7天」这类时间表述会被误读成 limit=7
_ROW_UNIT = r"名|行|条|位|项|个|款|种|款式"
_LIMIT_RE = re.compile(
    rf"(?:前|头)\s*(?P<head>[0-9]+|[一两二三四五六七八九十百]+)\s*(?:{_ROW_UNIT})"
    rf"|top\s*(?P<top>[0-9]+)"
    rf"|(?:只要|只取|仅要|仅取|只显示|只展示|返回|取)\s*"
    rf"(?P<take>[0-9]+|[一两二三四五六七八九十百]+)\s*(?:{_ROW_UNIT})",
    re.IGNORECASE,
)
_DESC_RE = re.compile(
    r"降序|倒序|从高到低|从大到小|从多到少|最高|最多|最大|最好|排行|排名|top",
    re.IGNORECASE,
)
_ASC_RE = re.compile(r"升序|正序|从低到高|从小到大|从少到多|最低|最少|最小|最差|倒数")
# 「按X降序/按X排序」才是排序诉求；「按X统计」是分组维度，不能当排序字段
_ORDER_FIELD_RE = re.compile(
    r"(?:按|以|根据|依据|用)\s*"
    r"(?P<label>[一-鿿A-Za-z0-9_()（）%\.\-]{1,40}?)\s*"
    r"(?:从高到低|从低到高|从大到小|从小到大|从多到少|从少到多|降序|升序|倒序|正序|排序|排列|排名)"
)
_LIMIT_WORDS = {"十": 10, "二十": 20, "三十": 30, "五十": 50, "一百": 100, "百": 100}
_LIMIT_DIGITS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}


def _parse_count(text: str) -> int | None:
    """解析行数：阿拉伯数字优先，另支持 Top N 常用的少量中文数词。"""
    text = text.strip()
    if text.isdigit():
        value = int(text)
        return value if 0 < value <= 5000 else None
    if text in _LIMIT_WORDS:
        return _LIMIT_WORDS[text]
    return _LIMIT_DIGITS.get(text)


def _match_ordered_field(label: str, fields: Sequence[dict]) -> dict | None:
    """把「按X排序」里的 X 绑定到本次已选字段；完整等值优先于去括号基名。"""
    needle = _normalize(label)
    if not needle:
        return None
    for field in fields:
        if _normalize(field.get("label_zh")) == needle:
            return field
    for field in fields:
        base = re.split(r"[（(]", _normalize(field.get("label_zh")), maxsplit=1)[0]
        if base and base == needle:
            return field
    return None


def _resolve_order_and_limit(
    query: str, dimensions: Sequence[dict], metrics: Sequence[dict]
) -> tuple[list[dict] | None, int | None, str]:
    """解析排序与行数意图。

    返回 (orderBy, limit, 未解析原因)。未解析原因非空时调用方必须强制披露——
    静默放行会让用户把「全量自然序」当成「Top N」，是本审计中修掉的高危形态之一。

    排序字段解析优先级：
    1. 「按X降序/按X排序」显式点名，且 X 能绑定到本次已选字段；
    2. 本次只选了一个指标时按该指标排（Top N 的常识语义）；
    3. 都不成立则不下发排序与行数，改为强制披露。
    """
    match = _LIMIT_RE.search(query)
    raw_count = ""
    if match:
        raw_count = match.group("head") or match.group("top") or match.group("take") or ""
    limit = _parse_count(raw_count) if raw_count else None
    has_direction = bool(_DESC_RE.search(query) or _ASC_RE.search(query))
    if not limit and not has_direction:
        return None, None, ""

    # 方向：显式升序优先于降序词（「最低的前5名」应按升序），都没有时 Top N 默认降序
    direction = "ASC" if _ASC_RE.search(query) else "DESC"

    ordered_field = None
    field_match = _ORDER_FIELD_RE.search(query)
    if field_match:
        ordered_field = _match_ordered_field(
            field_match.group("label"), list(metrics) + list(dimensions)
        )
    if ordered_field is None and len(metrics) == 1:
        ordered_field = metrics[0]
    if ordered_field is None:
        target = "排序指标" if metrics else "排序字段"
        return None, None, (
            f"用户要求了排序或行数限制，但未能唯一确定{target}"
            f"（本次共 {len(metrics)} 个指标）：本次查询未应用排序与行数限制，"
            "返回的是完整结果集且按服务端自然序排列，不得当作 Top N 汇报。"
        )
    return (
        [{"field": ordered_field["field_name"], "direction": direction}],
        limit,
        "",
    )


def _build_query_template(
    table_id: object,
    dimensions: list[dict],
    metrics: list[dict],
    date_fields: list[dict],
    scope: dict | None,
    platform_values: list[str] | None = None,
    global_currency: str | None = None,
) -> dict | None:
    """生成可直接填充的正式查询 payload 骨架（P1-4）。

    形状与已验证的 opscli query simple --json 实测形态一致：
    日期过滤为 >=/<= 两行、对比为 dataComparison{field,startDate,endDate}、
    排序为 orderBy[{field,direction}]。普通指标默认 SUM；
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
    resolved_platforms = [
        str(value).strip() for value in (platform_values or []) if str(value).strip()
    ]
    if resolved_platforms:
        filters.append(
            {
                "field": "platform_name",
                "operator": "=" if len(resolved_platforms) == 1 else "in",
                "value": (
                    resolved_platforms[0]
                    if len(resolved_platforms) == 1
                    else resolved_platforms
                ),
            }
        )
    # 全局币种：命中币种意图时写入模板（纳入 integrity 哈希）；无意图则不加该键
    if global_currency:
        template["globalCurrency"] = global_currency
    return template


def _attach_multi_currency_templates(contract: dict, query: str) -> dict:
    """为多币种意图复制同口径模板，每个币种都绑定一次独立服务端查询。

    此函数在字段和筛选解析完成后运行，因此各模板除 ``globalCurrency`` 外完全一致。
    ``query_template`` 保留首个模板以兼容单模板执行器；``query_templates`` 由
    ``query_flow.py`` 逐项执行，整个列表随后一起进入 plan integrity 摘要。
    """
    if contract.get("status") != "planned" or contract.get("query_mode") != "dataset_query":
        return contract
    currencies = _detect_global_currencies(query)
    if len(currencies) < 2:
        return contract
    execution = contract.get("execution_ref")
    if not isinstance(execution, dict):
        return contract
    template = execution.get("query_template")
    if not isinstance(template, dict):
        return contract

    templates: list[dict] = []
    for currency in currencies:
        currency_template = deepcopy(template)
        currency_template["globalCurrency"] = currency
        templates.append(currency_template)
    execution["requested_global_currencies"] = currencies
    execution["query_templates"] = templates
    execution["query_template"] = deepcopy(templates[0])
    execution["currency_execution_contract_zh"] = (
        "每个 query_templates 项必须分别调用取数服务；禁止用任一结果配合外部汇率或本地换算"
        "生成其他币种。各次查询除 globalCurrency 外的表、字段、时间和筛选必须完全一致。"
    )
    return contract


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
    # 无日期字段的数据集：_build_query_template 只在 date_fields 非空时才落日期过滤，
    # 而 time_scope 已按用户原文算出了具体窗口。放任不管的后果是 model_view 声明一个
    # 根本没生效的时间窗，Agent 按 SKILL.md 第 4 条把它当权威口径讲给用户，
    # 数字却是全表历史累计——无异常、无阻断、无披露，是唯一会产出
    # 「看起来完全正常的错误答案」的路径（矩阵实测 41/384 命中，涉及 5 张表）。
    # 处置分两种：请求含环比/同比时根本无从对比，必须澄清；否则收敛为全时段并强制披露。
    date_scope_unavailable = False
    if scope and not date_fields and not scope.get("unbounded"):
        date_scope_unavailable = True
        if scope.get("comparison"):
            status = "clarify_required"
            if "time_comparison_unsupported" not in clarification_reasons:
                clarification_reasons.append("time_comparison_unsupported")
            pending_confirmations_zh.append(
                "该数据集没有日期字段，无法做环比或同比：确认改为不限时间的整体查询，或更换数据集"
            )
        scope = {
            **scope,
            "start": None,
            "end": None,
            "unbounded": True,
            "is_default": False,
            "matched": False,
            "comparison": None,
            "label_zh": "全部时间（该数据集没有日期字段，无法按时间筛选）",
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
            _clarification_message(code, selection, dataset_names_zh or {})
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
    platform_disclosures = _platform_scope_disclosures(platform, blocked=status == "blocked")
    if platform_disclosures:
        model_view["platform_scope_disclosures_zh"] = platform_disclosures
    # 阻断态必须自带可执行材料：原因一句话 + 当前账号实际可用的平台。
    # 只留一条「需要说明被阻断的原因」而不给原因，等于把披露义务变成猜测诱因。
    block_reason = BLOCK_REASON_MESSAGES.get(str(internal.get("next_action", "")))
    if status == "blocked" and block_reason:
        model_view["block_reason_zh"] = block_reason
        authorized_values = platform.get("authorized_enum_values") or []
        if authorized_values:
            model_view["authorized_alternatives_zh"] = (
                "当前账号已授权的平台为：" + "、".join(authorized_values)
                + "。可改用其中之一重新提问。"
            )
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
    order_unresolved = ""
    if status == "planned" and str(internal.get("next_action", "")) == "construct_query":
        template = _build_query_template(
            dataset.get("table_id"),
            execution_dimensions,
            execution_metrics,
            date_fields,
            scope,
            resolution.get("resolved_filter_values", []),
            _detect_global_currency(query),
        )
        if template is not None:
            # 排序与行数由规划期解析后直接写入模板（纳入 plan_integrity 摘要）。
            # 交给 Agent 填是行不通的：SKILL.md 禁止改写模板，改了也过不了完整性校验。
            order_by, row_limit, order_unresolved = _resolve_order_and_limit(
                query, execution_dimensions, execution_metrics
            )
            if order_by:
                template["orderBy"] = order_by
            if row_limit:
                template["limit"] = row_limit
            execution_ref["query_template"] = template
            execution_ref["query_template_fill_rules_zh"] = (
                "模板已预填授权字段、时间窗与排序行数（日期过滤为 >=/<= 两行实测形态）。"
                "时间窗由 Python 按 execution_ref.time_scope 的参考日期生成，禁止自行心算、猜测年份或改写。"
                "普通指标默认 SUM 按用户口径调整；公式/快照指标不带 aggregation。"
                "排序与行数已由规划器按用户原文解析写入 orderBy/limit，Agent 不得改写；"
                "未下发时以 answer_contract 的披露为准。不需要的键（null 值）必须删除后再执行。"
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
    # 时间窗被收敛为全时段时必须显式告知：用户原文里说了时间，结论却不能按那个时间讲。
    # 少了这条，Agent 只会看到一个语气平静的「全部时间」标签，不会意识到需要向用户交代差异。
    if date_scope_unavailable:
        answer_contract["required_disclosures_zh"].append(
            "该数据集没有日期字段，用户请求的时间范围无法作为查询条件生效："
            "本次为全量口径，结论不得表述为该时间段的数据。"
        )
    # 排序/行数解析不出时必须显式告知：静默放行会让用户把「全量自然序」当成 Top N
    if order_unresolved:
        answer_contract["required_disclosures_zh"].append(order_unresolved)
    # 阻断原因与可选平台一并进入强制披露，让「说明被阻断的原因」这条要求真正可执行
    if model_view.get("block_reason_zh"):
        answer_contract["required_disclosures_zh"].append(model_view["block_reason_zh"])
    if model_view.get("authorized_alternatives_zh"):
        answer_contract["required_disclosures_zh"].append(
            model_view["authorized_alternatives_zh"]
        )
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
    query: str,
    requested_fields: Sequence[str] = (),
    authorized_platform_values: Sequence[str] | None = None,
    **kwargs,
) -> dict:
    """构建内部合同并投影为模型合同（规划器的默认输出路径）。

    auto_enum=True 时（默认），平台筛选待枚举的 planned 合同会在本函数内
    自动执行一次枚举查询并回灌重规划（P0-3），把「枚举→回传→重规划」
    三步收敛为一次调用；枚举短超时（7s，贴合默认命令窗）内未返回或失败时，
    保留首版合同并内嵌现成枚举命令走手动路径，绝不阻塞命令窗口。

    显式图表 UUID 请求在读取本地元数据前确定性分流，输出 chart_uuid 模式合同；
    该模式直接使用 opscli query chart/chart-doc，不进入普通数据集选表流程。
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

    auto_enum = bool(kwargs.pop("auto_enum", True))
    data_dir = Path(kwargs.get("data_dir", DATA_DIR))
    internal = build_query_plan(
        query,
        requested_fields=requested_fields,
        authorized_platform_values=authorized_platform_values,
        **kwargs,
    )
    # 只收集已选数据集的授权字段。跨表全局标签会制造“展示层有字段、
    # execution_ref 无物理身份”的假命中，必须在投影入口收紧作用域。
    authorized_fields = {"dimensions": [], "metrics": []}
    dataset_names_zh: dict[str, str] = {}
    dataset_summaries_zh: dict[str, str] = {}
    if internal.get("data_state") == "ready":
        # fallback 接管数据目录后，标签读取必须跟随实际生效目录
        data_dir = Path(internal.get("effective_data_dir") or data_dir)
        rows = scoped_dataset_reader.load_dataset_fields(data_dir)
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
        for row in scoped_dataset_reader.load_datasets(data_dir):
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
    # P0-3 二段收敛：待权限枚举时自动执行枚举查询并回灌重规划。
    # 本次调用已执行过自动升级时跳过（升级宽限+枚举叠加会撑破 30 秒命令窗口，
    # 此时输出内嵌枚举命令走手动路径，各调用均可快速返回）
    if (
        auto_enum
        and not internal.get("upgrade_performed_this_call")
        and not authorized_platform_values
        and internal.get("next_action") == "query_platform_permission_enum"
    ):
        cache_meta: dict = {}
        values = _auto_enum_platform_values(
            contract["execution_ref"].get("platform_component_table_id"),
            cache_meta=cache_meta,
        )
        if values:
            internal = build_query_plan(
                query,
                requested_fields=requested_fields,
                authorized_platform_values=values,
                **kwargs,
            )
            contract = build_model_contract(
                internal,
                query=query,
                authorized_field_labels=authorized_fields,
                dataset_names_zh=dataset_names_zh,
                dataset_summaries_zh=dataset_summaries_zh,
            )
            # 枚举来源标注：审计可区分自动枚举与人工回传；命中本地缓存时单独标注
            # 来源与"来自 N 小时前缓存"的中文披露，避免 Agent 把降级值当实时数据
            stale_hours = cache_meta.get("stale_hours")
            if stale_hours is None:
                contract["execution_ref"]["platform_enum_source"] = "auto_enum_service"
            else:
                contract["execution_ref"]["platform_enum_source"] = "auto_enum_service_cache"
                contract["model_view"].setdefault("platform_scope_disclosures_zh", []).append(
                    f"平台枚举值来自约 {stale_hours:.1f} 小时前缓存（实时枚举超时/失败后的降级兜底）。"
                )
    contract = _resolve_component_filters(
        contract, query, auto_enum=auto_enum, data_dir=data_dir
    )
    contract = _attach_multi_currency_templates(contract, query)
    contract = _attach_fallback_guidance(contract)
    # planned 合同生成后立即封存，执行器据此拒绝规划与执行之间的手工改写。
    if contract.get("status") == "planned" and contract.get("query_mode") == "dataset_query":
        plan_integrity.attach(contract)
    # 模型规划器体积守卫：新增投影（模板/组件/时间规划器）不得撑爆模型上下文
    if len(json.dumps(contract, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("query_plan_output_too_large")
    return contract


def _enum_cache_fallback(
    component_table_id: object, field_name: str, *, cache_meta: dict | None = None
) -> list[str]:
    """实时枚举超时/失败后的统一降级入口：命中本地缓存则返回陈旧值，未命中返回空列表。

    为什么集中成一个函数：三处枚举调用各自有 4 条独立的失败出口（subprocess 异常、
    非零退出码、返回体无法解析、业务失败），若每条出口都各写一遍缓存读取逻辑，
    极易漏改。缓存命中时把年龄（小时）写入 cache_meta 供调用方拼披露文案；
    未命中时 cache_meta 不变，调用方按现行失败路径处理（行为不回归）。
    """
    cached = enum_cache.get(component_table_id, field_name)
    if cached is None:
        return []
    if cache_meta is not None:
        age_hours = enum_cache.get_age_hours(component_table_id, field_name)
        cache_meta["stale_hours"] = age_hours if age_hours is not None else 0.0
    print(
        f"[query_plan] 实时枚举失败，改用本地缓存（{field_name}，"
        f"{cache_meta.get('stale_hours') if cache_meta else '?'} 小时前）",
        file=sys.stderr,
    )
    return cached


def _auto_enum_platform_values(
    component_table_id: object,
    *,
    timeout_seconds: float = 7.0,
    cache_meta: dict | None = None,
) -> list[str]:
    """自动执行平台权限枚举查询，返回服务端实际平台值列表（P0-3）。

    实时枚举失败时先尝试本地缓存降级（TTL 24h，见 enum_cache 模块），命中则把
    缓存年龄写入 cache_meta 供调用方标注"来自缓存"；缓存也未命中时才返回空列表，
    回落到规划器内嵌的手动枚举命令路径——不改变原有 fail-closed 行为，只是新增
    一条恢复路径。诊断信息只走 stderr。
    """
    command = _platform_enum_command(component_table_id)
    if not command:
        return []
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
    try:
        result = subprocess.run(
            [
                "opscli", "query", "simple",
                "--table-id", str(component_table_id),
                "--json", enum_json,
                "--run",
            ],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            **core.utf8_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"[query_plan] 自动枚举未完成：{error}", file=sys.stderr)
        return _enum_cache_fallback(component_table_id, "platform_name", cache_meta=cache_meta)
    if result.returncode != 0:
        print(f"[query_plan] 自动枚举失败：{(result.stderr or result.stdout or '')[:200]}", file=sys.stderr)
        return _enum_cache_fallback(component_table_id, "platform_name", cache_meta=cache_meta)
    try:
        payload = json.loads(result.stdout[result.stdout.index("{"):])
    except (ValueError, json.JSONDecodeError):
        print("[query_plan] 自动枚举返回无法解析，回落手动枚举", file=sys.stderr)
        return _enum_cache_fallback(component_table_id, "platform_name", cache_meta=cache_meta)
    if payload.get("success") is False:
        print(f"[query_plan] 自动枚举业务失败：{str(payload.get('error'))[:200]}", file=sys.stderr)
        return _enum_cache_fallback(component_table_id, "platform_name", cache_meta=cache_meta)
    # 结果行兜底遍历：不同版本返回形状可能是 data.result.data / result.data / data
    rows: list = []
    for path in (("data", "result", "data"), ("result", "data"), ("data", "data")):
        node: Any = payload
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list) and node:
            rows = node
            break
    values = _deduplicate(
        str(row.get("platform_name", "")).strip()
        for row in rows
        if isinstance(row, dict)
    )
    if values:
        print(f"[query_plan] 自动枚举取得平台值：{values}", file=sys.stderr)
        # 实时枚举成功：写入本地缓存供下次超时/失败时降级兜底（TTL 24h）
        enum_cache.put(component_table_id, "platform_name", values)
    return values


def _auto_enum_component_values(
    component_table_id: object,
    field_name: str,
    *,
    timeout_seconds: float = 7.0,
    errors: list | None = None,
    cache_meta: dict | None = None,
) -> list[str]:
    """枚举普通筛选组件字段；远端异常返回空列表并把原因写入 errors。

    调用方必须区分两种空：调用失败（errors 非空，无法校验，须阻断）与
    调用成功但当前账号无授权值（errors 为空，该字段不可能成为筛选条件，跳过即可）。
    混为一谈会让「开发」这类本账号无授权值的字段把所有查询都阻断。

    实时枚举失败时先尝试本地缓存降级（TTL 24h）：命中则视为恢复成功，
    不写入 errors（避免把已恢复的调用错判为需要阻断），并把缓存年龄写入
    cache_meta 供调用方标注"来自缓存"；缓存也未命中才写 errors 并返回空列表，
    维持现行 fail-closed 行为。
    """
    if component_table_id in (None, "") or not field_name:
        return []
    enum_json = json.dumps(
        {
            "tableId": component_table_id,
            "dimensions": [{"field": field_name, "alias": field_name}],
            "metrics": [],
            "limit": 500,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        result = subprocess.run(
            [
                "opscli",
                "query",
                "simple",
                "--table-id",
                str(component_table_id),
                "--json",
                enum_json,
                "--run",
            ],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            **core.utf8_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"[query_plan] 普通筛选组件枚举未完成：{error}", file=sys.stderr)
        cached = _enum_cache_fallback(component_table_id, field_name, cache_meta=cache_meta)
        if cached:
            return cached
        if errors is not None:
            errors.append(f"{type(error).__name__}: {error}"[:200])
        return []
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "")[:200]
        print(f"[query_plan] 普通筛选组件枚举失败：{detail}", file=sys.stderr)
        cached = _enum_cache_fallback(component_table_id, field_name, cache_meta=cache_meta)
        if cached:
            return cached
        if errors is not None:
            errors.append(detail)
        return []
    try:
        payload = json.loads(result.stdout[result.stdout.index("{") :])
    except (ValueError, json.JSONDecodeError):
        print("[query_plan] 普通筛选组件枚举返回无法解析", file=sys.stderr)
        cached = _enum_cache_fallback(component_table_id, field_name, cache_meta=cache_meta)
        if cached:
            return cached
        return []
    if payload.get("success") is False:
        print(
            f"[query_plan] 普通筛选组件枚举业务失败：{str(payload.get('error'))[:200]}",
            file=sys.stderr,
        )
        cached = _enum_cache_fallback(component_table_id, field_name, cache_meta=cache_meta)
        if cached:
            return cached
        return []
    rows: list = []
    for path in (("data", "result", "data"), ("result", "data"), ("data", "data")):
        node: Any = payload
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list):
            rows = node
            break
    values = _deduplicate(
        str(row.get(field_name, "")).strip()
        for row in rows
        if isinstance(row, dict) and row.get(field_name) not in (None, "")
    )
    if values:
        # 实时枚举成功：写入本地缓存供下次超时/失败时降级兜底（TTL 24h）
        enum_cache.put(component_table_id, field_name, values)
    return values


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
    """按标签形态提取单个筛选值（不关心是否为列举的调用方用这个）。"""
    return _labeled_value_match(query, label_terms)[0]


# 显式列举的分隔符只收列举标点与「或」。不收「和」「与」：
# 「渠道为傲彼瑞-美国和所有ASIN」里的「和」后面接的不是同类枚举值。
_VALUE_SEPARATOR = re.compile(r"\s*(?:、|,|，|/|或)\s*")


def _labeled_value_match(query: str, label_terms: Sequence[str]) -> tuple[str, bool]:
    """按「字段名 + 系词 + 值」形态提取筛选值，并判断其后是否紧跟显式列举。

    返回 (首个值, 是否为显式列举)。只检测列举、不负责把其余值抽出来：
    其余值交给授权枚举反查做完整等值匹配。为什么不在这里抽：末位值后面往往
    接自由描述（「…傲彼瑞-加拿大三个当前账号授权渠道中的任意一个」），
    靠边界前瞻猜结尾必然过度捕获成「傲彼瑞-加拿大三个当前账号授权渠道」。

    为什么需要这个判断：原先只取第一个值就落地筛选，
    「筛选渠道为傲彼瑞-美国、傲彼瑞-tiktok、傲彼瑞-加拿大中任意一个」
    会静默把三渠道缩成一个；而剩下两个值没被登记成已消费，
    其中的「加拿大」又被国家字段反查抓走，最终下发
    channel=傲彼瑞-美国 AND country=加拿大 这种用户从未表达的条件。

    系词是必需的：没有它，「渠道和ASIN」这类维度点名会被当成筛选值。
    标签按长度降序尝试，避免「渠道」抢先匹配掉「渠道SKU」。
    值用非贪婪 + 边界前瞻收住，否则「渠道是傲彼瑞的所有ASIN」会整段被吞。
    """
    for term in sorted(label_terms, key=len, reverse=True):
        pattern = re.compile(
            re.escape(term)
            + r"\s*(?:为|是|=|＝|：|:|等于)\s*"
            + r"([\u4e00-\u9fffA-Za-z0-9_\-\.]{2,40}?)"
            + r"(?=的|地|，|,|。|；|;|、|/|\s|和|与|或|下|里|中|所有|全部|$)",
            re.IGNORECASE,
        )
        match = pattern.search(query)
        if not match:
            continue
        # 值之后紧跟列举分隔符即判定为显式列举。
        # 这里必须用 Pattern.match(s, pos)（已锚定在 pos），不能再加 ^——
        # ^ 只认字符串真开头，叠加后续接判断永远为假
        enumerated = bool(_VALUE_SEPARATOR.match(query, match.end(1)))
        return match.group(1).strip(), enumerated
    return "", False


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


def _generic_slot_terms() -> set:
    """收集通用业务词，用于排除枚举值主段的误判匹配。

    为什么需要：反查规则「枚举原值的主段出现在原文即算命中」对同源多地区渠道
    （傲彼瑞-美国 / 傲彼瑞-加拿大）是必要的，但当主段本身是通用业务词时就会误判——
    销售小组的授权值形如「亚马逊-运营C组」，主段是「亚马逊」，于是任何提到亚马逊
    的查询都被当成指定了销售小组，真实元数据下已观察到 team_name 被注入 filters。

    词表全部取自 intent_rules.json 现有内容（槽位取值 terms、筛选字段名、业务域词），
    不新造词表——新造就等于把本计划想消灭的人工维护成本又加回来。
    规则文件不可读时返回空集：宁可退回旧行为，也不因排除集缺失而漏掉真实命中。
    """
    try:
        rules = _load_json_object(RULES_PATH, "invalid_rules_file")
    except (RuntimeError, OSError):
        return set()
    terms: set = set()
    for slot in (rules.get("slots") or {}).values():
        if not isinstance(slot, dict):
            continue
        for spec in slot.values():
            if isinstance(spec, dict):
                terms |= {_normalize_component_value(t) for t in spec.get("terms") or []}
    for field_terms in (rules.get("filter_fields") or {}).values():
        terms |= {_normalize_component_value(t) for t in field_terms or []}
    for domain in (rules.get("domains") or {}).values():
        if isinstance(domain, dict):
            terms |= {_normalize_component_value(t) for t in domain.get("terms") or []}
    return {term for term in terms if term}


def _reverse_lookup_component_matches(
    query: str, values: list, normalize
) -> tuple[list, str]:
    """用授权枚举原值反查原文，返回 (候选, 命中类型)。

    为什么需要：用户常直接说「查傲彼瑞的所有ASIN」，原文根本不含「渠道」二字，
    标签正则抽不到值，会被当成没有筛选意图而放行——这正是静默返回全渠道数据的成因。
    这里反过来拿当前账号的授权原值去原文里找，原值本身或其主段（连字符前）
    出现即算候选，"傲彼瑞" 因此能同时命中「傲彼瑞-美国」「傲彼瑞-加拿大」并转澄清。

    命中类型必须回传给调用方，因为两类命中的语义完全不同：
    - exact：原文逐个写出了完整授权原值，是用户点名的准确值，多个也应全部锁定；
    - base：原文只出现主段，天然歧义，必须按 fail-closed 转澄清。
    原先两类被拍平成一个列表返回，调用方只能统一要求"唯一命中"，
    于是用户显式给出的三个准确渠道名被当成主段歧义，回显还退化成共同前缀「傲彼瑞」，
    反过来要求用户"请指定准确渠道名称"——而用户给的本来就是准确全名。
    """
    normalized_query = normalize(query)
    generic = _generic_slot_terms()
    exact_hits, base_hits = [], []
    for value in values:
        norm = normalize(value)
        if not norm:
            continue
        if norm in normalized_query:
            exact_hits.append(value)
            continue
        base = norm.split("-")[0]
        # 主段是通用业务词（平台名/业务域/筛选字段名）时不做主段匹配：
        # 用户说「亚马逊」指的是平台，不是主段恰好叫「亚马逊」的销售小组
        if len(base) >= 2 and base not in generic and base in normalized_query:
            base_hits.append(value)
    # 整值命中优先：原文写了「傲彼瑞-加拿大」就该锁定它，而不是因为主段
    # 「傲彼瑞」同时命中三个地区渠道而退化成澄清
    if exact_hits:
        return _deduplicate(exact_hits), "exact"
    if base_hits:
        return _deduplicate(base_hits), "base"
    return [], ""


def _reverse_lookup_component_values(query: str, values: list, normalize) -> list:
    """反查授权枚举原值，只取候选列表（不关心命中类型的调用方用这个）。"""
    return _reverse_lookup_component_matches(query, values, normalize)[0]


def _shared_prefix(values: list) -> str:
    """多候选时取共同前缀作回显（「傲彼瑞-美国」「傲彼瑞-加拿大」→「傲彼瑞」）。"""
    if not values:
        return ""
    prefix = str(values[0])
    for value in values[1:]:
        while prefix and not str(value).startswith(prefix):
            prefix = prefix[:-1]
    return prefix.rstrip("-_ ") or str(values[0])



def _component_field_group_cache_fallback(
    component_table_id: object, field_names: list, *, cache_meta: dict | None = None
) -> dict:
    """批量枚举失败后逐字段尝试本地缓存降级；未命中的字段不出现在返回字典里。

    批量调用是一次网络请求取多个字段，但持久缓存按 (表, 字段) 单独落盘，
    因此失败降级只能逐字段查——允许部分字段命中、部分未命中（部分降级）。
    """
    fallback: dict = {}
    for name in field_names:
        cached = enum_cache.get(component_table_id, name)
        if cached is None:
            continue
        fallback[name] = cached
        if cache_meta is not None:
            age_hours = enum_cache.get_age_hours(component_table_id, name)
            cache_meta[name] = age_hours if age_hours is not None else 0.0
    return fallback


def _auto_enum_component_field_group(
    component_table_id: object,
    field_names: list,
    *,
    timeout_seconds: float = 7.0,
    cache_meta: dict | None = None,
) -> dict:
    """一次查询取组件表多个字段的授权枚举值，按列返回去重结果。

    组件表返回的是各字段的组合行，行数受 limit 限制；低基数字段（渠道 9、
    国家 2、销售 12 之类）在 500 行内可完整覆盖，这也是只给低基数字段开
    反查的原因。实时枚举失败时先逐字段尝试本地缓存降级（TTL 24h，允许部分
    命中），命中的字段年龄写入 cache_meta；缓存也未命中的字段返回空字典，
    由上层按现行 fail-closed 阻断（行为不回归）。
    """
    if component_table_id in (None, "") or not field_names:
        return {}
    enum_json = json.dumps(
        {
            "tableId": component_table_id,
            "dimensions": [{"field": name, "alias": name} for name in field_names],
            "metrics": [],
            "limit": 500,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        result = subprocess.run(
            ["opscli", "query", "simple", "--table-id", str(component_table_id),
             "--json", enum_json, "--run"],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            **core.utf8_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"[query_plan] 组件批量枚举未完成：{error}", file=sys.stderr)
        return _component_field_group_cache_fallback(
            component_table_id, field_names, cache_meta=cache_meta
        )
    if result.returncode != 0:
        return _component_field_group_cache_fallback(
            component_table_id, field_names, cache_meta=cache_meta
        )
    try:
        payload = json.loads(result.stdout[result.stdout.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return _component_field_group_cache_fallback(
            component_table_id, field_names, cache_meta=cache_meta
        )
    rows: list = []
    for path in (("data", "result", "data"), ("result", "data"), ("data", "data")):
        node = payload
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, list) and node:
            rows = node
            break
    grouped = {
        name: _deduplicate(
            str(row.get(name, "")).strip()
            for row in rows
            if isinstance(row, dict) and str(row.get(name, "")).strip()
        )
        for name in field_names
    }
    # 实时枚举成功：逐字段写入本地缓存供下次超时/失败时降级兜底（TTL 24h）
    for name, values in grouped.items():
        if values:
            enum_cache.put(component_table_id, name, values)
    return grouped


# 组件筛选字段总表（值类字段，date_id 归时间口径、platform_name 归平台范围逻辑）。
#
# 三个开关的取舍依据是实测基数与裸值出现概率：
# - label_terms：标签形态抽取用的说法集合，命中标签才发起枚举，零额外网络成本。
# - reverse_lookup：拿授权枚举原值反查原文，用于兜住不带字段名的裸值
#   （「查傲彼瑞的ASIN」「查史子涵的销量」）。只给低基数字段开——实测渠道 9、
#   国家 2、品牌 3、销售 12，枚举一次就能覆盖全集；部门枚举是当前账号的
#   权限子集、同属低基数，开反查兜住「宁波」「泛泰克」「孵化部」这类
#   无后缀或特殊名部门的裸值提及；SKU/产品名这类几百上千的
#   字段开反查既慢又不可能枚举完整，改用形态抽取。
# - value_pattern：编码型字段的裸值形态，抽到候选后仍要枚举校验权限。
_ENUM_COMPONENT_SPECS = (
    {
        "field_name": "dept_name",
        "label_zh": "部门",
        "extract": _extract_requested_department_value,
        "normalize": _normalize_department_value,
        "reverse_lookup": True,
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


def _lookup_component(execution: dict, field_name: str, data_dir) -> dict | None:
    """查组件配置：优先用合同里的 filter_components，缺失时回落到全量组件表。

    为什么必须回落：filter_components 是按查询相关性排序后截断的，用户原文不含
    「渠道」二字时该组件会被裁掉——而裸值请求（「查傲彼瑞的所有ASIN」）恰恰是
    最需要枚举校验的场景，靠合同里的裁剪结果会漏掉。
    """
    hit = _component_of(execution, field_name)
    if hit:
        return hit
    dataset_alias = str(execution.get("dataset_alias") or "")
    if not dataset_alias or data_dir is None:
        return None
    column = next(
        (
            row
            for row in scoped_dataset_reader.load_select_columns(Path(data_dir))
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
            for row in scoped_dataset_reader.load_datasets(Path(data_dir))
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


def _dataset_has_field(execution: dict, field_name: str, data_dir) -> bool:
    """判断已选数据集是否含指定字段（ASIN 字面筛选的前置条件）。"""
    dataset_alias = str(execution.get("dataset_alias") or "")
    if not dataset_alias or data_dir is None:
        return False
    return any(
        str(row.get("dataset_alias", "")) == dataset_alias
        and str(row.get("field_name", "")) == field_name
        for row in scoped_dataset_reader.load_dataset_fields(Path(data_dir))
    )


def _block_component_filter(
    contract: dict, execution: dict, *, state: str, next_action: str, message_zh: str
) -> dict:
    """筛选值无法锁定时统一收口：撤下可执行模板并给出中文恢复指引。

    为什么必须撤模板：query_flow 在 status=planned 时会原样执行 query_template，
    而模板里没有用户要的筛选条件——放行等于把「查某渠道」悄悄变成「查全部渠道」，
    静默错数比查不到数据危险得多。这里一律 fail-closed。
    """
    contract["status"] = "blocked" if state == "enum_unavailable" else "clarify_required"
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
    resolved: str | list,
    stale_hours: float | None = None,
) -> None:
    """把已锁定的授权原值写入查询模板，并登记披露信息。

    resolved 传列表表示用户点名了多个准确值，按 IN 语义下发
    （服务端支持 {"operator": "in", "value": [...]}），单值仍用 `=`，
    避免为单值场景改变既有 payload 形状。

    stale_hours 非 None 表示本次授权枚举来自本地缓存降级（实时枚举超时/失败），
    须在披露里如实标注，不能让 Agent 把降级值当成实时数据转述给用户。
    """
    template = execution.get("query_template")
    if not isinstance(template, dict):
        return
    multi = isinstance(resolved, list)
    values = list(resolved) if multi else [resolved]
    template.setdefault("filters", []).append(
        {"field": field_name, "operator": "in", "value": values}
        if multi
        else {"field": field_name, "operator": "=", "value": resolved}
    )
    execution.setdefault("resolved_component_filters", []).append(
        {
            "field_name": field_name,
            "label_zh": label_zh,
            "requested_value": requested,
            "resolved_value": values if multi else resolved,
            "match_strategy": "exact_normalized",
        }
    )
    contract["model_view"]["component_filter_state"] = "resolved"
    shown = "、".join(f"“{value}”" for value in values) if multi else f"“{resolved}”"
    contract["model_view"].setdefault("component_filter_disclosures_zh", []).append(
        f"{label_zh}按当前账号授权枚举完整等值匹配为{shown}"
        + ("（任一命中）。" if multi else "。")
    )
    if stale_hours is not None:
        contract["model_view"]["component_filter_disclosures_zh"].append(
            f"{label_zh}的授权枚举值来自约 {stale_hours:.1f} 小时前缓存"
            "（实时枚举超时/失败后的降级兜底）。"
        )


def _resolve_enum_component_filter(
    contract: dict,
    query: str,
    spec: dict,
    *,
    auto_enum: bool,
    data_dir,
    enum_cache: dict,
    labeled_only: bool = False,
    consumed: set | None = None,
) -> dict:
    """把用户原文里的组件筛选值在当前账号授权枚举中唯一等值解析并写入模板。

    两条识别路径互补：
    1. 标签形态（「渠道是傲彼瑞」）由 spec["extract"] 正则抽取；
    2. 裸值形态（「查傲彼瑞的所有ASIN」，原文不含字段名）由授权枚举原值反查原文。
       没有第 2 条时，裸值请求会因抽不到值而被当成「没有筛选意图」直接放行，
       正是静默返回全范围数据的成因。

    任一环节无法唯一锁定都不放行：枚举拿不到 → blocked；命中不唯一或零命中 →
    clarify_required，并撤下 query_template。
    """
    execution = contract.get("execution_ref")
    if not isinstance(execution, dict):
        return contract
    consumed = consumed if consumed is not None else set()
    field_name = spec["field_name"]
    label_zh = spec["label_zh"]
    component = _lookup_component(execution, field_name, data_dir)
    if not component:
        return contract

    # 该字段本趟之前已解析过就不再重复（两趟循环会把同一 spec 走两遍）
    if any(
        isinstance(item, dict) and item.get("field_name") == field_name
        for item in execution.get("resolved_component_filters") or []
    ):
        return contract
    requested = _spec_extract(spec, query, labeled_only=labeled_only, consumed=consumed)
    # 标签形态的值后面紧跟列举分隔符时，用户点名的是一组值而不是一个值。
    # 此时不能拿抽到的首个值去做单值等值匹配——那会静默把三渠道缩成一个渠道，
    # 且其余值不会登记为已消费，其中的「加拿大」会被国家字段反查抓走。
    # 改走下面的枚举反查分支：由授权枚举做完整等值匹配，不靠边界前瞻猜结尾。
    labeled_first, labeled_enumeration = _labeled_value_match(
        query, spec.get("label_terms") or ()
    )
    enumerated = bool(labeled_enumeration and requested and requested == labeled_first)
    # 第一趟只落实用户显式点名的字段，反查与形态抽取留到第二趟
    if labeled_only and not requested:
        return contract
    # 只认标签形态的字段原文没提就没有筛选意图，不必付出一次枚举调用
    if not requested and not spec.get("reverse_lookup"):
        return contract
    # 未开启自动枚举时无从校验：抽到了值才阻断，否则保持原状供维护者排查
    if not auto_enum:
        if requested:
            return _block_component_filter(
                contract,
                execution,
                state="enum_unavailable",
                next_action="retry_component_permission_enum",
                message_zh=(
                    f"当前未能枚举{label_zh}“{requested}”的授权原值，"
                    "已阻止扩大为全范围查询；请原样重试一次。"
                ),
            )
        return contract

    enum_errors: list = []
    values = _cached_enum_values(
        enum_cache, component.get("component_table_id"), field_name, enum_errors
    )
    if not values and not requested and not enum_errors:
        # 枚举成功但当前账号无授权值：该字段不可能成为筛选条件，跳过即可。
        # 「开发」在部分账号下就是 0 条，若按失败阻断会把所有查询挡死。
        return contract
    if not values:
        # 枚举失败时无法判断原文里有没有筛选值，一律不放行（宁可错杀）
        return _block_component_filter(
            contract,
            execution,
            state="enum_unavailable",
            next_action="retry_component_permission_enum",
            message_zh=(
                f"当前未能枚举{label_zh}"
                + (f"“{requested}”" if requested else "")
                + "的授权原值，已阻止扩大为全范围查询；请原样重试一次。"
            ),
        )

    # 未单独声明归一化的字段走通用规则（NFKC + trim + casefold）；
    # 部门有中文数字等价这类特殊口径，才单独挂自己的归一化器
    normalize = spec.get("normalize") or _normalize_component_value
    # 整值多命中：原文逐个写出了完整授权原值，是用户点名的准确值集合，
    # 全部锁定并以 IN 下发，不再因为"命中不唯一"退化成澄清
    exact_multi = False
    if requested and not enumerated:
        target = normalize(requested)
        matched = [value for value in values if normalize(value) == target]
    else:
        # 裸值反查：授权原值本身或其主段（连字符前）出现在原文即算候选
        candidates, match_kind = _reverse_lookup_component_matches(query, values, normalize)
        matched = [
            value
            for value in candidates
            # 已被其他字段消费掉的值（含其子串）不再算命中：
            # 「品牌是OHWILL」不该连带匹配渠道 ohwill-shopify-美国；
            # 渠道锁定「傲彼瑞-加拿大」后，其中的「加拿大」也不该再被国家反查抓走
            if not _value_already_consumed(normalize(value), consumed)
        ]
        if not matched:
            # requested 非空说明用户用「字段+系词」显式点名了一组值（如
            # 「国家为德国、法国」，labeled_enumeration 命中），只是反查在授权
            # 枚举里零命中——不同于原文根本没提该字段的静默放行场景，不能沿用
            # 同一条 `return contract`：那会把「用户点名的国家全部未授权」悄悄
            # 处理成「用户没有筛选意图」，下发不含筛选条件的可执行模板，
            # query_flow 会原样执行，等同于把「只查德国」放行成「查全部国家」
            # （QA 实测另一形态：值本身在授权枚举里，被执行器 precheck 拒绝；
            # 无论哪种，客户端都必须先与权限枚举求交集，零交集时不注入且披露）。
            # requested 为空则是原文确实没提这个字段，继续保持原有静默放行。
            if requested:
                return _block_component_filter(
                    contract,
                    execution,
                    state="clarify_required",
                    next_action="ask_user_for_component_filter",
                    message_zh=(
                        f"识别到{label_zh}“{requested}”等表述，但均不在当前账号"
                        f"授权范围内，已阻止扩大为全范围查询；请改用当前账号可见的"
                        f"{label_zh}取值，或确认是否需要该筛选。"
                    ),
                )
            return contract
        exact_multi = len(matched) > 1 and match_kind == "exact"
        if exact_multi:
            requested = "、".join(matched)
        else:
            requested = matched[0] if len(matched) == 1 else _shared_prefix(matched)

    if len(matched) != 1 and not exact_multi:
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
            state="clarify_required",
            next_action="ask_user_for_component_filter",
            message_zh=(
                f"{label_zh}“{requested}”没有唯一完整等值的授权成员，"
                + (f"当前账号可见的近似成员：{hint}；" if hint else "")
                + f"请指定当前账号可见的准确{label_zh}名称。"
            ),
        )

    # 裸值（无字段标签）且该值在别的字段枚举里也存在时不得静默绑定：
    # 值在错字段里同样合法，等值校验兜不住，只能让用户点明是哪个字段
    if not labeled_first and not exact_multi:
        candidates = _cross_field_candidates(
            spec, matched[0], execution, data_dir, enum_cache
        )
        if len(candidates) > 1:
            listed = "、".join(f"“{item}”" for item in candidates)
            return _block_component_filter(
                contract,
                execution,
                state="clarify_required",
                next_action="ask_user_for_component_filter",
                message_zh=(
                    f"“{matched[0]}”同时是{listed}的授权值，无法确定你要按哪个字段筛选；"
                    f"请指明字段，例如「{candidates[0]}是{matched[0]}」。"
                ),
            )

    # 本字段的授权枚举是否来自本地缓存降级（实时枚举超时/失败后的兜底），
    # 由 _cached_enum_values / _batch_enum_reverse_lookup_fields 写入的伴随键判定
    stale_hours = enum_cache.get(("stale", str(component.get("component_table_id")), field_name))
    _write_component_filter(
        contract,
        execution,
        field_name=field_name,
        label_zh=label_zh,
        requested=requested,
        resolved=matched if exact_multi else matched[0],
        stale_hours=stale_hours,
    )
    consumed.add(_normalize_component_value(requested))
    # 多值时每个已锁定的值都要登记，避免其中某个值的子串被后续字段反查抓走
    for value in matched if exact_multi else [matched[0]]:
        consumed.add(_normalize_component_value(value))
    return contract


def _cross_field_candidates(
    owner_spec: dict, value: str, execution: dict, data_dir, enum_cache: dict
) -> list[str]:
    """裸值在其他字段的授权枚举里也存在时，返回全部候选字段的中文标签。

    为什么只对裸值判：用户显式写「产品型号是BKC-107」或「SPU是BKC-107」时
    字段已由标签确定，两种写法实测都能正确落到各自字段；只有裸值
    （靠编码形态抽出来）才存在歧义。碰撞扫描在本账号真实枚举里找到 10 个
    同值跨字段的情形（产品型号∩SPU 8 个、渠道SKU∩公司SKU 2 个），
    原先按 _ENUM_COMPONENT_SPECS 顺序静默绑到靠前的字段——
    值在错字段里同样合法，因此没有任何 fail-closed 兜底，用户拿到的是
    另一个口径的数据且无从察觉。

    检查范围限定为「同样带编码形态的字段」（当前 5 个），不按形态是否命中该值
    再缩小——`USAN1088833` 同属渠道SKU 与公司SKU，但渠道SKU 的形态要求三段
    连字符、匹配不上它，按形态缩范围会漏掉这一对。5 次枚举有上限且走缓存。
    """
    normalized = _normalize_component_value(value)
    labels = [owner_spec.get("label_zh") or owner_spec["field_name"]]
    for spec in _ENUM_COMPONENT_SPECS:
        if spec["field_name"] == owner_spec["field_name"]:
            continue
        if not spec.get("value_pattern"):
            continue
        component = _lookup_component(execution, spec["field_name"], data_dir)
        if not component:
            continue
        errors: list = []
        others = _cached_enum_values(
            enum_cache, component.get("component_table_id"), spec["field_name"], errors
        )
        if errors:
            continue
        if any(_normalize_component_value(item) == normalized for item in others):
            labels.append(spec.get("label_zh") or spec["field_name"])
    return labels


def _cached_enum_values(
    cache: dict, table_id: object, field_name: str, errors: list | None = None
) -> list:
    """带缓存的组件枚举：同一次规划里同一 (表, 字段) 只查一次。

    缓存同时记住「本次枚举是否报错」以及「本次结果是否来自本地磁盘缓存降级」
    （("stale", *key) → 缓存年龄小时数，未降级则不写这个键），
    供调用方区分调用失败/无授权值/降级取值三种情况。
    """
    key = (str(table_id), field_name)
    if key not in cache:
        local_errors: list = []
        local_cache_meta: dict = {}
        cache[key] = _auto_enum_component_values(
            table_id, field_name, errors=local_errors, cache_meta=local_cache_meta
        )
        cache[("error", *key)] = local_errors
        if "stale_hours" in local_cache_meta:
            cache[("stale", *key)] = local_cache_meta["stale_hours"]
    if errors is not None:
        errors.extend(cache.get(("error", *key)) or [])
    return cache[key]


def _batch_enum_reverse_lookup_fields(
    contract: dict, data_dir, enum_cache: dict
) -> None:
    """把需要裸值反查的字段按组件表合并成一次查询，避免逐字段各发一次网络请求。

    实测 17 个值类字段只落在 6 张组件表上（渠道/国家/平台同表，销售/小组/大组同表），
    合并后反查成本从「字段数」降到「表数」。组件表一次返回的是各字段的组合行，
    按列取去重值即可。
    """
    execution = contract.get("execution_ref")
    if not isinstance(execution, dict):
        return
    by_table: dict[str, list[str]] = {}
    for spec in _ENUM_COMPONENT_SPECS:
        if not spec.get("reverse_lookup"):
            continue
        component = _lookup_component(execution, spec["field_name"], data_dir)
        if not component:
            continue
        table_id = str(component.get("component_table_id") or "")
        if table_id:
            by_table.setdefault(table_id, []).append(spec["field_name"])
    for table_id, fields in by_table.items():
        if all((table_id, field) in enum_cache for field in fields):
            continue
        group_cache_meta: dict = {}
        grouped = _auto_enum_component_field_group(
            table_id, fields, cache_meta=group_cache_meta
        )
        for field in fields:
            enum_cache.setdefault((table_id, field), grouped.get(field, []))
            if field in group_cache_meta:
                enum_cache[("stale", table_id, field)] = group_cache_meta[field]


def _resolve_asin_filter(contract: dict, query: str, data_dir) -> dict:
    """商品 ID 直接从原文字面锁定，不走枚举。

    为什么不枚举：ASIN/商品 ID 基数几万起，500 条枚举覆盖不了，也太慢。
    代价是只能靠形态识别，认错时查询返回 0 行（响亮失败），
    比认不出而静默返回全范围数据安全。
    """
    execution = contract.get("execution_ref")
    if not isinstance(execution, dict):
        return contract
    if not _dataset_has_field(execution, "asin", data_dir):
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


def _time_literals_consumed(contract: dict) -> set:
    """把时间解析已经用掉的日期字面量登记为已消费。

    为什么需要：渠道SKU 的编码形态是 `[A-Za-z0-9]{2,}(-[A-Za-z0-9]{2,}){2,}`，
    ISO 日期「2026-07-01」正好命中。实测「沿用 2026-07-01 至 2026-07-30 的口径」
    被误读成渠道SKU 筛选值并转澄清，用户的日期口径反而落不了地。
    日期已被时间解析消费，不该再被组件形态抽取二次消费——这正是 consumed 的语义。
    """
    time_scope = (contract.get("execution_ref") or {}).get("time_scope") or {}
    literals = set()
    for key in ("start", "end", "comparison_start", "comparison_end"):
        value = time_scope.get(key)
        if value:
            literals.add(_normalize_component_value(value))
    return literals


def _resolve_component_filters(
    contract: dict, query: str, *, auto_enum: bool, data_dir=None
) -> dict:
    """解析原文中的组件字段筛选值（部门/渠道走授权枚举，ASIN 走字面格式）。

    只在 planned 的数据集查询上生效；任一字段无法唯一锁定即撤下模板，
    避免 query_flow 执行不含用户筛选条件的「骨架」。
    """
    if contract.get("status") != "planned":
        return contract
    contract = _resolve_asin_filter(contract, query, data_dir)
    enum_cache: dict = {}
    consumed: set = _time_literals_consumed(contract)
    if auto_enum and contract.get("status") == "planned":
        _batch_enum_reverse_lookup_fields(contract, data_dir, enum_cache)
    # 两趟：先落实用户显式点名的字段并登记已消费的值，再做形态抽取与枚举反查
    for labeled_only in (True, False):
        for spec in _ENUM_COMPONENT_SPECS:
            if contract.get("status") != "planned":
                break
            contract = _resolve_enum_component_filter(
                contract,
                query,
                spec,
                auto_enum=auto_enum,
                data_dir=data_dir,
                enum_cache=enum_cache,
                labeled_only=labeled_only,
                consumed=consumed,
            )
    return contract


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """规划器命令行参数。internal 输出模式仅供维护者排错。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query",
        nargs="?",
        default="",
        help="查询原文；含引号等特殊字符时改用 --query-file 或 stdin（传 -）",
    )
    parser.add_argument(
        "--query-file",
        default="",
        help="从文件读取查询原文（- 表示 stdin），防止 shell 引号拼接碎裂",
    )
    parser.add_argument("--field", action="append", default=[])
    parser.add_argument("--authorized-platform-value", action="append")
    parser.add_argument("--top-n", type=int, default=planner.MAX_CANDIDATES)
    parser.add_argument(
        "--output-mode", choices=("model", "internal"), default="model"
    )
    parser.add_argument(
        "--no-auto-upgrade",
        action="store_true",
        help="元数据未就绪时不自动执行 opscli skills upgrade（默认自动升级一次）",
    )
    parser.add_argument(
        "--no-auto-enum",
        action="store_true",
        help="平台待枚举时不自动执行枚举查询（默认自动枚举一次并回灌重规划）",
    )
    return parser.parse_args(argv)


def _resolve_query_text(args: argparse.Namespace) -> str:
    """归一查询原文来源：--query-file（- 为 stdin）优先于位置参数。"""
    if args.query_file:
        if args.query_file == "-":
            return sys.stdin.read().strip()
        return core.read_text_auto(Path(args.query_file)).strip()
    return args.query


def _error_next_action(code: str) -> tuple[str, bool]:
    """按错误码前缀匹配下一步指引，未命中时给通用自救路径。"""
    for prefix, hint, retryable in ERROR_NEXT_ACTIONS:
        if code.startswith(prefix):
            return hint, retryable
    return DEFAULT_ERROR_NEXT_ACTION, False


def main(argv: Sequence[str] | None = None) -> int:
    # 入口先切 UTF-8 stdio：规划合同与 stderr 诊断都含中文，Windows 管道下不能走 GBK
    core.force_utf8_stdio()
    args = _parse_args(argv)
    try:
        query = _resolve_query_text(args)
        if not query.strip():
            raise ValueError("missing_query_text")
        extra: dict[str, Any] = {}
        if args.output_mode != "internal":
            # auto_enum 仅模型规划器路径支持（internal 为维护者排错，不做网络调用）
            extra["auto_enum"] = not args.no_auto_enum
        builder = (
            build_query_plan
            if args.output_mode == "internal"
            else build_model_query_plan
        )
        result = builder(
            query,
            requested_fields=args.field,
            authorized_platform_values=args.authorized_platform_value,
            top_n=args.top_n,
            auto_upgrade=not args.no_auto_upgrade,
            **extra,
        )
    except Exception as error:  # noqa: BLE001 —— 兜底捕获：内部错误裸 traceback 极耗 token 且会吓退模型
        expected = isinstance(
            error, (FileNotFoundError, LookupError, RuntimeError, TypeError, ValueError)
        )
        code = (str(error) or type(error).__name__) if expected else (
            f"internal_error:{type(error).__name__}"
        )
        next_action_zh, retryable = _error_next_action(code)
        # 错误改走 stdout（保留 exit 2）：部分执行器会吞 stderr，
        # Agent 若只看到空输出会盲重试；错误 JSON 自带下一步动作
        print(
            json.dumps(
                {"error": code, "retryable": retryable, "next_action_zh": next_action_zh},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
