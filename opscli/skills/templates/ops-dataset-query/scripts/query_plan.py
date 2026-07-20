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
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

import agent_query_planner as planner
import dataset_guidance
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

    platform_scope = _platform_scope(selection, raw_rules, authorized_platform_values)
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
        scope_zh = f"{scope['label_zh']}：{scope['start']} ~ {scope['end']}（{scope['timezone']}）"
        if comparison:
            scope_zh += f"；对比期 {comparison['label_zh']}：{comparison['start']} ~ {comparison['end']}"
        if scope.get("is_default"):
            scope_zh += "。注意：未识别到明确时间表述，这是默认口径，必须向用户披露并确认"
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
                "排序填 orderBy=[{\"field\":\"<结果alias>\",\"direction\":\"DESC|ASC\"}]，"
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
    return {
        "contract": MODEL_CONTRACT,
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
    """
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
        values = _auto_enum_platform_values(
            contract["execution_ref"].get("platform_component_table_id")
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
            # 枚举来源标注：审计可区分自动枚举与人工回传
            contract["execution_ref"]["platform_enum_source"] = "auto_enum_service"
    # 模型规划器体积守卫：新增投影（模板/组件/时间规划器）不得撑爆模型上下文
    if len(json.dumps(contract, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("query_plan_output_too_large")
    return contract


def _auto_enum_platform_values(component_table_id: object, *, timeout_seconds: float = 7.0) -> list[str]:
    """自动执行平台权限枚举查询，返回服务端实际平台值列表（P0-3）。

    任何失败（opscli 不可用/未登录/超时/形状不符）都返回空列表，
    回落到规划器内嵌的手动枚举命令路径；诊断只走 stderr。
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
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"[query_plan] 自动枚举未完成：{error}", file=sys.stderr)
        return []
    if result.returncode != 0:
        print(f"[query_plan] 自动枚举失败：{(result.stderr or result.stdout or '')[:200]}", file=sys.stderr)
        return []
    try:
        payload = json.loads(result.stdout[result.stdout.index("{"):])
    except (ValueError, json.JSONDecodeError):
        print("[query_plan] 自动枚举返回无法解析，回落手动枚举", file=sys.stderr)
        return []
    if payload.get("success") is False:
        print(f"[query_plan] 自动枚举业务失败：{str(payload.get('error'))[:200]}", file=sys.stderr)
        return []
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
    return values


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
        return Path(args.query_file).read_text(encoding="utf-8").strip()
    return args.query


def _error_next_action(code: str) -> tuple[str, bool]:
    """按错误码前缀匹配下一步指引，未命中时给通用自救路径。"""
    for prefix, hint, retryable in ERROR_NEXT_ACTIONS:
        if code.startswith(prefix):
            return hint, retryable
    return DEFAULT_ERROR_NEXT_ACTION, False


def main(argv: Sequence[str] | None = None) -> int:
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
