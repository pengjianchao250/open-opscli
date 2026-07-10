#!/usr/bin/env python3
"""反馈提交守门脚本：判断一条 ops 反馈事件是否需要远端提交。

本脚本刻意保持轻副作用：
- `decide` 只输出提交决策；仅在命中重复失败时更新本地 occurrence_count；
- `record` 在远端提交成功后，把 `feedback_uuid` 与会话级预算写入本地状态。

脚本自身不发起任何 HTTP 请求（铁律11：Skill 脚本禁止直连后端），
远端提交动作由 Agent 依据决策结果调用 `feedback_submit` / `opscli feedback submit` 完成。

分级策略（与 SKILL.md 保持一致）：
- L0：dry-run / 本地只读 / 仅生成计划 → 不提交；
- L1：成功事件 → 只写本地任务摘要，远端成功反馈默认关闭；
- L2：0 行 / 全空 / 降级 / 用户纠错等可疑数据 → 按会话预算最多提交 1 条；
- L3：CLI/MCP 硬失败 → 即时提交 bug，30 分钟滑动窗口内去重复用 feedback_uuid。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# 本地状态文件默认路径：保存失败指纹去重记录和 L2 会话预算桶
DEFAULT_STATE_FILE = Path.home() / ".opscli" / "feedback_guard_state.json"
# 失败去重窗口：同一失败指纹 30 分钟内只远端提交 1 次（滑动窗口，重复命中会刷新 last_seen）
DEFAULT_DEDUPE_WINDOW_SECONDS = 30 * 60
# 非失败类（L2）远端反馈预算：同一会话/任务默认最多 1 条
DEFAULT_NON_FAILURE_REMOTE_BUDGET = 1
# 本地状态保留时长：过期的失败指纹和会话预算桶会在下一次 decide/record 时清理
DEFAULT_STATE_RETENTION_SECONDS = 24 * 60 * 60
# fingerprint 输入的体积上限：保证低 token 快速路径不被大日志拖垮
MAX_FINGERPRINT_PAYLOAD_BYTES = 4096
# 单个字符串值参与 fingerprint 的最大字节数，超出部分截断
MAX_FINGERPRINT_STRING_BYTES = 256
# 列表 / 字典参与 fingerprint 的最大元素数，超出部分截断
MAX_FINGERPRINT_LIST_ITEMS = 10
MAX_FINGERPRINT_DICT_ITEMS = 40
# 敏感字段名标记：命中即整值替换为 [REDACTED]，避免 Token/密码进入指纹或输出
SENSITIVE_KEY_MARKERS = (
    "authorization",
    "cookie",
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_key",
)
# 认证流程工具名标记：命中才进入"预期未授权状态"判断
EXPECTED_AUTH_TOOL_MARKERS = (
    "auth_login_start",
    "auth_login_poll",
    "auth login start",
    "auth login poll",
)
# 认证流程中的预期状态文案：命中则视为登录轮询的正常中间态，不提交反馈
EXPECTED_AUTH_STATE_MARKERS = (
    "401",
    "authorization_pending",
    "login_pending",
    "not_logged_in",
    "pending",
    "unauthenticated",
    "unauthorized",
    "待授权",
    "等待授权",
    "未授权",
    "未登录",
    "尚未完成授权",
)


def read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 文件；文件不存在或顶层不是 dict 时返回空 dict。"""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_state_json(path: Path) -> dict[str, Any]:
    """读取本地状态文件；文件损坏或不可读时按空状态继续（不阻塞原任务）。"""
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        # 状态损坏时不抛异常：guard 只是辅助去重，不能因为自身状态问题阻塞主流程
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """写入 JSON 文件，父目录不存在时自动创建。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def parse_now(value: str | None) -> datetime:
    """解析 --now 传入的 ISO 时间；未传时取当前 UTC 时间（--now 主要用于测试注入）。"""
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        # 无时区信息时按 UTC 处理，保证跨机器状态时间可比
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def iso(dt: datetime) -> str:
    """时间序列化为带 Z 后缀的 UTC ISO 字符串。"""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    """稳定 JSON 序列化（键排序、无空白），保证同一事件产生相同指纹。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_bytes(value: Any) -> int:
    """计算值序列化后的 UTF-8 字节数，用于 fingerprint 体积控制。"""
    return len(stable_json(value).encode("utf-8"))


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否命中敏感标记（大小写不敏感，`-` 视同 `_`）。"""
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)


def new_event_hygiene() -> dict[str, Any]:
    """初始化事件卫生统计：记录脱敏次数、截断次数和最终 fingerprint 体积。"""
    return {
        "sanitized_for_fingerprint": True,
        "sensitive_key_count": 0,
        "oversized_value_count": 0,
        "fingerprint_payload_bytes": 0,
        "fingerprint_payload_limit_bytes": MAX_FINGERPRINT_PAYLOAD_BYTES,
        "payload_compacted_to_limit": False,
    }


def truncate_for_fingerprint(value: str, hygiene: dict[str, Any]) -> str:
    """把超长字符串截断到指纹允许的字节数，并在卫生统计中计数。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_FINGERPRINT_STRING_BYTES:
        return value
    hygiene["oversized_value_count"] += 1
    truncated = encoded[:MAX_FINGERPRINT_STRING_BYTES].decode("utf-8", "ignore")
    return f"{truncated}...[truncated_bytes={len(encoded) - MAX_FINGERPRINT_STRING_BYTES}]"


def sanitize_for_fingerprint(value: Any, hygiene: dict[str, Any], key: str = "") -> Any:
    """递归清洗参与 fingerprint 的事件副本：脱敏敏感字段、截断大值。

    为什么要清洗：fingerprint 输入若携带 Token 等敏感值，会把敏感信息带进
    决策输出和本地状态文件；若携带大日志，会让低 token 快速路径失效。
    """
    # 敏感字段整值替换，不参与指纹计算
    if key and is_sensitive_key(key):
        hygiene["sensitive_key_count"] += 1
        return "[REDACTED]"

    if isinstance(value, dict):
        # 键排序保证指纹稳定；超出上限的键截断并显式标记
        items = sorted(value.items(), key=lambda item: str(item[0]))
        if len(items) > MAX_FINGERPRINT_DICT_ITEMS:
            hygiene["oversized_value_count"] += 1
        output: dict[str, Any] = {}
        for item_key, item_value in items[:MAX_FINGERPRINT_DICT_ITEMS]:
            output[str(item_key)] = sanitize_for_fingerprint(item_value, hygiene, str(item_key))
        if len(items) > MAX_FINGERPRINT_DICT_ITEMS:
            output["_truncated_items"] = len(items) - MAX_FINGERPRINT_DICT_ITEMS
        return output

    if isinstance(value, list):
        if len(value) > MAX_FINGERPRINT_LIST_ITEMS:
            hygiene["oversized_value_count"] += 1
        items_output: list[Any] = [sanitize_for_fingerprint(item, hygiene, key) for item in value[:MAX_FINGERPRINT_LIST_ITEMS]]
        if len(value) > MAX_FINGERPRINT_LIST_ITEMS:
            items_output.append(f"...[truncated_items={len(value) - MAX_FINGERPRINT_LIST_ITEMS}]")
        return items_output

    if isinstance(value, str):
        return truncate_for_fingerprint(value, hygiene)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    # 其他类型（如自定义对象）转字符串后截断，避免序列化失败
    return truncate_for_fingerprint(str(value), hygiene)


def call_params_compaction_summary(call_params: Any, hygiene: dict[str, Any]) -> dict[str, Any]:
    """把过大的 call_params 压缩成形状摘要（哈希 + 顶层键），保留可区分性但不保留内容。"""
    sanitized = sanitize_for_fingerprint(call_params, hygiene)
    summary: dict[str, Any] = {
        "_compacted": True,
        "_sanitized_shape_hash": hashlib.sha256(stable_json(sanitized).encode("utf-8")).hexdigest()[:20],
        "_value_type": type(call_params).__name__,
    }
    if isinstance(call_params, dict):
        summary["_top_level_keys"] = sorted(str(key) for key in call_params.keys())[:MAX_FINGERPRINT_DICT_ITEMS]
    elif isinstance(call_params, list):
        summary["_item_count"] = len(call_params)
    return summary


def bound_fingerprint_payload(payload: dict[str, Any], hygiene: dict[str, Any]) -> dict[str, Any]:
    """把 fingerprint 输入体积压到上限以内。

    两级降级：先把 call_params 换成形状摘要；仍超限时进一步只保留摘要哈希。
    """
    size = json_bytes(payload)
    if size <= MAX_FINGERPRINT_PAYLOAD_BYTES:
        hygiene["fingerprint_payload_bytes"] = size
        return payload

    bounded = dict(payload)
    bounded["call_params"] = call_params_compaction_summary(payload.get("call_params", {}), hygiene)
    hygiene["payload_compacted_to_limit"] = True
    hygiene["oversized_value_count"] += 1
    size = json_bytes(bounded)
    if size > MAX_FINGERPRINT_PAYLOAD_BYTES:
        # 第二级降级：连顶层键列表都不保留，只留哈希
        bounded["call_params"] = {
            "_compacted": True,
            "_sanitized_shape_hash": hashlib.sha256(stable_json(bounded["call_params"]).encode("utf-8")).hexdigest()[:20],
            "_value_type": type(payload.get("call_params", {})).__name__,
        }
        size = json_bytes(bounded)
    hygiene["fingerprint_payload_bytes"] = size
    return bounded


def tool_name(event: dict[str, Any]) -> str:
    """提取事件的工具标识：MCP 工具名 > CLI 命令名 > 通用 tool 字段。"""
    return str(event.get("mcp_tool_name") or event.get("command_name") or event.get("tool") or "unknown")


def is_feedback_tool(event: dict[str, Any]) -> bool:
    """判断失败的是否是反馈通道自身（feedback submit/detail），是则必须 fail-open 防递归。"""
    name = tool_name(event).lower().replace("_", " ")
    return any(marker in name for marker in ("feedback submit", "feedback detail"))


def is_expected_auth_state(event: dict[str, Any]) -> bool:
    """判断是否为认证流程中的预期未授权/轮询中状态。

    登录轮询期间会连续产生"未授权"类错误，属于正常中间态；
    若不抑制，会造成反馈风暴。仅当工具名和状态文案同时命中才抑制，
    认证服务 5xx 等非预期错误不在此列，仍按 L3 处理。
    """
    name = tool_name(event).lower().replace("-", "_")
    if not any(marker in name for marker in EXPECTED_AUTH_TOOL_MARKERS):
        return False
    status_text = " ".join(
        str(event.get(key) or "").lower()
        for key in ["error_code", "error_message", "status", "outcome"]
    )
    return any(marker in status_text for marker in EXPECTED_AUTH_STATE_MARKERS)


def classify_event(event: dict[str, Any]) -> str:
    """事件分级：返回 L0 / L1 / L2 / L3。

    判定顺序刻意先看硬失败信号（失败态 outcome、success=false、非 0 exit_code、
    明确 error_code），再看 L2 可疑数据，最后才看成功态；这样保证：
    - zero_rows / degraded 等可疑结果即使带 error_message 也走 L2 预算而非 L3；
    - 成功事件里的 warning 文本不会被误判成失败。
    事件可通过 policy_level 字段显式指定层级，跳过自动判定。
    """
    explicit = str(event.get("policy_level") or "").upper()
    if explicit in {"L0", "L1", "L2", "L3"}:
        return explicit

    outcome = str(event.get("outcome") or event.get("status") or "").lower()
    # 硬失败信号：任一命中即 L3
    if outcome in {"failure", "failed", "error", "exception"}:
        return "L3"
    if event.get("success") is False or event.get("mcp_success") is False:
        return "L3"
    if event.get("exit_code") not in {None, 0, "0"}:
        return "L3"
    if event.get("error_code"):
        return "L3"

    # 可疑数据信号：按 L2 预算处理，即使事件携带 error_message
    if outcome in {"suspicious", "data_issue", "zero_rows", "all_null", "degraded", "user_correction"}:
        return "L2"
    if event.get("needs_owner_action") is True:
        return "L2"

    # 纯本地/计划类事件：不提交
    if outcome in {"dry_run", "local_eval", "read_only", "plan", "planning"}:
        return "L0"

    # 明确成功信号：L1
    if outcome in {"success", "succeeded", "ok", "completed"} or event.get("success") is True or event.get("mcp_success") is True:
        return "L1"

    # 无 outcome 但携带错误文本：保守视为失败
    if event.get("error_message"):
        return "L3"

    return "L1"


def feedback_group_key(event: dict[str, Any]) -> str:
    """提取批量失败聚合键：事件顶层或 context 中的 feedback_group_key / dedupe_key。"""
    context = event.get("context")
    context = context if isinstance(context, dict) else {}
    value = (
        event.get("feedback_group_key")
        or event.get("dedupe_key")
        or context.get("feedback_group_key")
        or context.get("dedupe_key")
    )
    return str(value).strip() if value else ""


def fingerprint_payload(event: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """构造参与指纹计算的清洗后事件副本。

    返回 (payload, 指纹来源, 卫生统计)。指纹来源有两种：
    - feedback_group_key：显式聚合键覆盖变化的工具名和参数，
      用于把批量扫描中同根因、不同参数的多条失败聚合到同一指纹；
    - call_params：默认回退，指纹由 {source, tool, error_code, error_message, call_params} 组成。
    """
    hygiene = new_event_hygiene()
    source = str(event.get("source") or "unknown")
    error_code = str(event.get("error_code") or "")
    group_key = feedback_group_key(event)
    if group_key:
        # 显式 group key：故意不含 tool 和 call_params，让参数变体命中同一指纹
        payload = {
            "source": source,
            "error_code": sanitize_for_fingerprint(error_code, hygiene, "error_code"),
            "feedback_group_key": sanitize_for_fingerprint(group_key, hygiene, "feedback_group_key"),
        }
        hygiene["fingerprint_payload_bytes"] = json_bytes(payload)
        return payload, "feedback_group_key", hygiene

    error_message = str(event.get("error_message") or "")
    call_params = sanitize_for_fingerprint(event.get("call_params", {}), hygiene, "call_params")
    identity = tool_name(event)
    payload = {
        "source": source,
        "tool": identity,
        "error_code": sanitize_for_fingerprint(error_code, hygiene, "error_code"),
        "error_message": sanitize_for_fingerprint(error_message, hygiene, "error_message"),
        "call_params": call_params,
    }
    return bound_fingerprint_payload(payload, hygiene), "call_params", hygiene


def fingerprint_identity(event: dict[str, Any], source: str) -> str:
    """指纹中段标识：group key 场景固定为 feedback_group_key，否则用工具名。"""
    if source == "feedback_group_key":
        return "feedback_group_key"
    return tool_name(event)


def fingerprint_details(event: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """计算失败指纹，返回 (指纹字符串, 指纹来源, 卫生统计)。

    指纹格式：`{事件source}:{标识}:{payload哈希前20位}`。
    """
    payload, source, hygiene = fingerprint_payload(event)
    event_source = str(event.get("source") or "unknown")
    identity = fingerprint_identity(event, source)
    digest = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()[:20]
    return f"{event_source}:{identity}:{digest}", source, hygiene


def default_state() -> dict[str, Any]:
    """本地状态初始结构：failures 为失败指纹表，sessions 为 L2 会话预算桶。

    session（单数）是 v1 遗留字段，保留用于向后兼容旧状态文件。
    """
    return {
        "version": 2,
        "failures": {},
        "session": {
            "non_failure_remote_count": 0,
        },
        "sessions": {},
    }


def load_state(path: Path) -> dict[str, Any]:
    """加载本地状态并修复缺失/损坏的子结构，保证后续代码可安全访问。"""
    state = default_state()
    state.update(read_state_json(path))
    if not isinstance(state.get("failures"), dict):
        state["failures"] = {}
    if not isinstance(state.get("session"), dict):
        state["session"] = {"non_failure_remote_count": 0}
    state["session"].setdefault("non_failure_remote_count", 0)
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    return state


def stale_timestamp(timestamp: Any, now: datetime, retention_seconds: int) -> bool:
    """判断时间戳是否已超过保留时长；retention<=0 表示不清理。"""
    if retention_seconds <= 0 or not timestamp:
        return False
    return seconds_since(str(timestamp), now) > retention_seconds


def prune_state(state: dict[str, Any], now: datetime, retention_seconds: int) -> bool:
    """清理过期的失败指纹和会话预算桶，返回状态是否发生变化。

    为什么要清理：状态文件长期累积会无限膨胀，且旧会话的 L2 预算桶
    如果不过期，可能误拦截很久之后的新任务。
    """
    changed = False
    failures = state.get("failures")
    if isinstance(failures, dict):
        for key, record in list(failures.items()):
            if not isinstance(record, dict):
                # 结构损坏的记录直接删除
                del failures[key]
                changed = True
                continue
            timestamp = record.get("last_seen") or record.get("first_seen")
            if stale_timestamp(timestamp, now, retention_seconds):
                del failures[key]
                changed = True
    else:
        state["failures"] = {}
        changed = True

    sessions = state.get("sessions")
    if isinstance(sessions, dict):
        for key, bucket in list(sessions.items()):
            if not isinstance(bucket, dict):
                del sessions[key]
                changed = True
                continue
            if stale_timestamp(bucket.get("last_seen"), now, retention_seconds):
                del sessions[key]
                changed = True
    else:
        state["sessions"] = {}
        changed = True

    # 同步 v1 遗留的 session 字段，保证旧读取方看到与 default 桶一致的计数
    default_bucket = state["sessions"].get("default") if isinstance(state.get("sessions"), dict) else None
    state["session"] = default_bucket if isinstance(default_bucket, dict) else {"non_failure_remote_count": 0}
    return changed


def session_budget_scope(event: dict[str, Any]) -> str:
    """确定 L2 预算桶的作用域：按会话/任务标识隔离，未传任何标识时回退到 default 桶。"""
    context = event.get("context")
    context = context if isinstance(context, dict) else {}
    for key in [
        "feedback_session_id",
        "session_id",
        "thread_id",
        "conversation_id",
        "task_id",
        "run_id",
    ]:
        value = event.get(key) or context.get(key)
        if value:
            return str(value)
    return "default"


def session_budget_bucket(state: dict[str, Any], scope: str) -> dict[str, Any]:
    """获取（必要时创建）指定作用域的 L2 预算桶。

    default 桶首次创建时继承 v1 遗留 session 字段的计数，保证升级后预算不被重置。
    """
    sessions = state.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        state["sessions"] = sessions
    if scope == "default" and "default" not in sessions:
        legacy = state.get("session")
        sessions["default"] = legacy if isinstance(legacy, dict) else {"non_failure_remote_count": 0}
    bucket = sessions.setdefault(scope, {"non_failure_remote_count": 0})
    if not isinstance(bucket, dict):
        bucket = {"non_failure_remote_count": 0}
        sessions[scope] = bucket
    bucket.setdefault("non_failure_remote_count", 0)
    return bucket


def seconds_since(timestamp: str, now: datetime) -> float:
    """计算时间戳距 now 的秒数；解析失败返回无穷大（视为窗口外，允许重新提交）。"""
    try:
        previous = parse_now(timestamp)
    except (TypeError, ValueError):
        return float("inf")
    return (now - previous).total_seconds()


def decide(
    event: dict[str, Any],
    state: dict[str, Any],
    state_file: Path,
    now: datetime,
    dedupe_window_seconds: int,
    non_failure_remote_budget: int,
) -> dict[str, Any]:
    """核心决策：判断事件是否需要远端提交，输出决策对象。

    参数：
        event: 事件 JSON（由 Agent 构造的小事件文件）。
        state: 已加载的本地状态。
        state_file: 状态文件路径（重复失败时需要就地写回计数）。
        now: 当前时间（可由 --now 注入，便于测试）。
        dedupe_window_seconds: 失败去重滑动窗口秒数。
        non_failure_remote_budget: L2 非失败远端反馈预算。

    返回的决策对象至少包含 submit_remote / policy_level / agent_action / reason；
    L3 场景额外携带 fingerprint 和 event_hygiene。
    """
    level = classify_event(event)

    # 认证轮询的预期中间态：抑制提交，避免登录期间反馈风暴
    if level == "L3" and is_expected_auth_state(event):
        return {
            "submit_remote": False,
            "policy_level": "L0",
            "agent_action": "do_not_submit_expected_auth_state",
            "reason": "expected_auth_login_state",
            "non_blocking": True,
        }

    # 反馈通道自身失败：fail-open，禁止递归提交"反馈失败"的反馈
    if level == "L3" and is_feedback_tool(event):
        return {
            "submit_remote": False,
            "policy_level": "L3",
            "agent_action": "fail_open_no_recursive_feedback",
            "reason": "feedback_submit_or_detail_failed",
            "non_blocking": True,
        }

    if level == "L0":
        return {
            "submit_remote": False,
            "policy_level": "L0",
            "agent_action": "do_not_submit",
            "reason": "local_or_planning_event",
            "non_blocking": True,
        }

    # L1 成功事件：远端成功反馈默认关闭，只写本地任务摘要
    if level == "L1":
        return {
            "submit_remote": False,
            "policy_level": "L1",
            "agent_action": "write_local_execution_summary",
            "reason": "successful_event_remote_feedback_disabled_by_default",
            "non_blocking": True,
        }

    # L2 可疑数据：仅当明确需要 owner 处理且预算未用完时才放行 1 条
    if level == "L2":
        budget_scope = session_budget_scope(event)
        budget_bucket = session_budget_bucket(state, budget_scope)
        count = int(budget_bucket.get("non_failure_remote_count", 0) or 0)
        if event.get("needs_owner_action") is not True:
            return {
                "submit_remote": False,
                "policy_level": "L2",
                "agent_action": "write_local_execution_summary",
                "reason": "owner_action_not_required",
                "budget_scope": budget_scope,
                "non_blocking": True,
            }
        if count >= non_failure_remote_budget:
            return {
                "submit_remote": False,
                "policy_level": "L2",
                "agent_action": "write_local_execution_summary",
                "reason": "non_failure_remote_budget_exhausted",
                "budget_scope": budget_scope,
                "non_blocking": True,
            }
        return {
            "submit_remote": True,
            "policy_level": "L2",
            "feedback_type": str(event.get("feedback_type") or "data_issue"),
            "agent_action": "submit_single_suspicious_summary",
            "reason": "owner_action_required_with_budget_available",
            "budget_scope": budget_scope,
            "non_blocking": True,
        }

    # L3 失败：先查滑动窗口内是否已有同指纹提交记录
    fp, fp_source, event_hygiene = fingerprint_details(event)
    record = state["failures"].get(fp)
    duplicate_missing_feedback_uuid = False
    if isinstance(record, dict) and seconds_since(str(record.get("last_seen", "")), now) <= dedupe_window_seconds:
        feedback_uuid = str(record.get("feedback_uuid") or "")
        if not feedback_uuid:
            # 记录损坏（缺少 feedback_uuid）：不能复用空 UUID，走重新提交分支
            duplicate_missing_feedback_uuid = True
        else:
            # 命中去重：刷新 last_seen（滑动窗口）并累加本地计数，复用已有 UUID
            record["last_seen"] = iso(now)
            record["occurrence_count"] = int(record.get("occurrence_count", 1) or 1) + 1
            state["failures"][fp] = record
            write_json(state_file, state)
            return {
                "submit_remote": False,
                "policy_level": "L3",
                "agent_action": "reuse_existing_feedback_uuid",
                "reason": "duplicate_failure_within_dedupe_window",
                "feedback_uuid": feedback_uuid,
                "fingerprint": fp,
                "fingerprint_source": str(record.get("fingerprint_source") or fp_source),
                "event_hygiene": event_hygiene,
                "occurrence_count": record["occurrence_count"],
                "non_blocking": True,
            }

    # 新失败或窗口已过期：要求 Agent 立即提交 bug（non_blocking 表示提交后须继续原任务）
    return {
        "submit_remote": True,
        "policy_level": "L3",
        "feedback_type": "bug",
        "agent_action": "submit_immediate_failure_feedback",
        "reason": "duplicate_failure_missing_feedback_uuid" if duplicate_missing_feedback_uuid else "new_failure_or_dedupe_window_expired",
        "fingerprint": fp,
        "fingerprint_source": fp_source,
        "event_hygiene": event_hygiene,
        "dedupe_window_seconds": dedupe_window_seconds,
        "non_blocking": True,
    }


def record_submission(event: dict[str, Any], state: dict[str, Any], now: datetime, feedback_uuid: str) -> dict[str, Any]:
    """远端提交成功后的登记：L3 写入失败指纹表，L2 消耗会话预算。

    参数：
        event: 与 decide 时相同的事件 JSON。
        state: 已加载的本地状态（由调用方负责落盘）。
        now: 当前时间。
        feedback_uuid: 远端返回的反馈 UUID。
    """
    level = classify_event(event)
    if level == "L3":
        fp, fp_source, event_hygiene = fingerprint_details(event)
        previous = state["failures"].get(fp) if isinstance(state.get("failures"), dict) else None
        occurrence_count = int(previous.get("occurrence_count", 0) if isinstance(previous, dict) else 0) + 1
        state["failures"][fp] = {
            "feedback_uuid": feedback_uuid,
            # first_seen 保留首次出现时间，重复提交只刷新 last_seen
            "first_seen": str(previous.get("first_seen")) if isinstance(previous, dict) and previous.get("first_seen") else iso(now),
            "last_seen": iso(now),
            "occurrence_count": occurrence_count,
            "tool": tool_name(event),
            "fingerprint_source": fp_source,
            "fingerprint_payload_bytes": event_hygiene["fingerprint_payload_bytes"],
            "feedback_group_key": feedback_group_key(event),
        }
        return {
            "recorded": True,
            "policy_level": "L3",
            "fingerprint": fp,
            "fingerprint_source": fp_source,
            "event_hygiene": event_hygiene,
            "feedback_uuid": feedback_uuid,
            "occurrence_count": occurrence_count,
        }

    if level == "L2":
        budget_scope = session_budget_scope(event)
        budget_bucket = session_budget_bucket(state, budget_scope)
        budget_bucket["non_failure_remote_count"] = int(budget_bucket.get("non_failure_remote_count", 0) or 0) + 1
        budget_bucket.setdefault("first_seen", iso(now))
        budget_bucket["last_seen"] = iso(now)
        if budget_scope == "default":
            # 同步 v1 遗留 session 字段，保持向后兼容
            state["session"]["non_failure_remote_count"] = budget_bucket["non_failure_remote_count"]
            state["session"].setdefault("first_seen", budget_bucket["first_seen"])
            state["session"]["last_seen"] = budget_bucket["last_seen"]
        return {
            "recorded": True,
            "policy_level": "L2",
            "feedback_uuid": feedback_uuid,
            "budget_scope": budget_scope,
            "non_failure_remote_count": budget_bucket["non_failure_remote_count"],
        }

    # L0/L1 本不该远端提交，record 调用视为无效登记
    return {
        "recorded": False,
        "policy_level": level,
        "reason": "remote_submission_not_expected_for_this_level",
    }


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器：decide 与 record 两个子命令共享大部分参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ["decide", "record"]:
        sub = subparsers.add_parser(command)
        sub.add_argument("--event-file", type=Path, required=True)
        sub.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
        # --now 用于测试注入固定时间，日常使用不传
        sub.add_argument("--now")
        sub.add_argument("--dedupe-window-seconds", type=int, default=DEFAULT_DEDUPE_WINDOW_SECONDS)
        sub.add_argument("--non-failure-remote-budget", type=int, default=DEFAULT_NON_FAILURE_REMOTE_BUDGET)
        sub.add_argument("--state-retention-seconds", type=int, default=DEFAULT_STATE_RETENTION_SECONDS)
        if command == "record":
            sub.add_argument("--feedback-uuid", required=True)

    return parser


def main() -> int:
    """脚本入口：加载事件与状态 → 清理过期状态 → 执行 decide/record → 输出 JSON 决策。"""
    args = build_parser().parse_args()
    event = read_json(args.event_file)
    state = load_state(args.state_file)
    now = parse_now(args.now)
    pruned = prune_state(state, now, max(args.state_retention_seconds, 0))

    if args.command == "decide":
        output = decide(
            event=event,
            state=state,
            state_file=args.state_file,
            now=now,
            dedupe_window_seconds=max(args.dedupe_window_seconds, 0),
            non_failure_remote_budget=max(args.non_failure_remote_budget, 0),
        )
        # decide 一般不落盘（重复失败分支内部已写）；仅当清理了过期状态时补写一次
        if pruned:
            write_json(args.state_file, state)
    else:
        output = record_submission(event=event, state=state, now=now, feedback_uuid=args.feedback_uuid)
        write_json(args.state_file, state)

    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
