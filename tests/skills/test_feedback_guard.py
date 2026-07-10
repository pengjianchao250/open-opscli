"""feedback_guard.py 决策逻辑回归测试。

覆盖分级反馈策略的核心路径：事件分类、失败去重（滑动窗口）、
feedback_group_key 批量聚合、L2 会话预算、敏感字段脱敏、事件瘦身、
认证轮询抑制、反馈通道 fail-open、状态损坏兜底与过期清理。

测试通过 importlib 直接加载模板脚本并调用其内部函数（不走 subprocess），
时间统一用 parse_now 注入固定值，状态文件使用 tmp_path（铁律8）。
"""

import importlib.util
import json
from pathlib import Path

# 直接从 Skill 模板目录加载脚本作为模块
GUARD_PATH = Path("opscli/skills/templates/ops-feedback/scripts/feedback_guard.py")
_spec = importlib.util.spec_from_file_location("feedback_guard", GUARD_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

# 测试统一使用的固定基准时间
T0 = guard.parse_now("2026-07-10T08:00:00Z")


def make_failure_event(**overrides):
    """构造一条典型 L3 失败事件，允许按需覆盖字段。"""
    event = {
        "outcome": "failure",
        "source": "cli",
        "command_name": "opscli query simple",
        "call_params": {"table_id": 1},
        "error_code": "QS-EXE-001",
        "error_message": "field not found",
        "session_id": "sess-1",
    }
    event.update(overrides)
    return event


def run_decide(event, state, state_file, now=T0, window=1800, budget=1):
    """封装 decide 调用，收敛默认参数。"""
    return guard.decide(
        event=event,
        state=state,
        state_file=state_file,
        now=now,
        dedupe_window_seconds=window,
        non_failure_remote_budget=budget,
    )


# ---------- 事件分类 ----------


class TestClassifyEvent:
    def test_dry_run_is_l0(self):
        assert guard.classify_event({"outcome": "dry_run"}) == "L0"

    def test_success_is_l1(self):
        assert guard.classify_event({"outcome": "success"}) == "L1"
        assert guard.classify_event({"success": True}) == "L1"

    def test_hard_failure_signals_are_l3(self):
        # 四种硬失败信号：失败态 outcome、success=false、非 0 exit_code、明确 error_code
        assert guard.classify_event({"outcome": "failure"}) == "L3"
        assert guard.classify_event({"success": False}) == "L3"
        assert guard.classify_event({"exit_code": 2}) == "L3"
        assert guard.classify_event({"error_code": "QS-EXE-001"}) == "L3"

    def test_suspicious_outcomes_stay_l2_even_with_error_message(self):
        # zero_rows / degraded 等可疑结果即使带 error_message 也按 L2 预算处理，不误报为 L3
        for outcome in ["zero_rows", "all_null", "degraded", "user_correction"]:
            assert guard.classify_event({"outcome": outcome, "error_message": "warn"}) == "L2"

    def test_error_message_without_outcome_is_l3(self):
        # 无 outcome 但带错误文本：保守视为失败
        assert guard.classify_event({"error_message": "boom"}) == "L3"

    def test_explicit_policy_level_overrides(self):
        assert guard.classify_event({"policy_level": "L0", "outcome": "failure"}) == "L0"


# ---------- L0 / L1 决策 ----------


def test_l1_success_writes_local_summary_only(tmp_path):
    state = guard.default_state()
    result = run_decide({"outcome": "success", "source": "cli"}, state, tmp_path / "st.json")
    assert result["submit_remote"] is False
    assert result["agent_action"] == "write_local_execution_summary"


def test_l0_dry_run_not_submitted(tmp_path):
    state = guard.default_state()
    result = run_decide({"outcome": "dry_run"}, state, tmp_path / "st.json")
    assert result["submit_remote"] is False
    assert result["agent_action"] == "do_not_submit"


# ---------- 认证轮询抑制与反馈通道 fail-open ----------


def test_expected_auth_state_suppressed(tmp_path):
    # 登录轮询中的预期未授权状态：不提交，避免反馈风暴
    event = {
        "outcome": "failure",
        "mcp_tool_name": "auth_login_poll",
        "error_code": "authorization_pending",
    }
    result = run_decide(event, guard.default_state(), tmp_path / "st.json")
    assert result["submit_remote"] is False
    assert result["agent_action"] == "do_not_submit_expected_auth_state"


def test_auth_tool_unexpected_error_still_l3(tmp_path):
    # 认证服务 5xx 等非预期错误仍按 L3 提交
    event = {
        "outcome": "failure",
        "mcp_tool_name": "auth_login_poll",
        "error_code": "500",
        "error_message": "internal server error",
    }
    result = run_decide(event, guard.default_state(), tmp_path / "st.json")
    assert result["submit_remote"] is True
    assert result["policy_level"] == "L3"


def test_feedback_tool_failure_fails_open(tmp_path):
    # feedback_submit 自身失败：fail-open，禁止递归提交
    event = {"outcome": "failure", "mcp_tool_name": "feedback_submit", "error_code": "500"}
    result = run_decide(event, guard.default_state(), tmp_path / "st.json")
    assert result["submit_remote"] is False
    assert result["agent_action"] == "fail_open_no_recursive_feedback"


# ---------- L3 失败去重（滑动窗口） ----------


def test_l3_first_failure_requires_immediate_submit(tmp_path):
    result = run_decide(make_failure_event(), guard.default_state(), tmp_path / "st.json")
    assert result["submit_remote"] is True
    assert result["feedback_type"] == "bug"
    assert result["agent_action"] == "submit_immediate_failure_feedback"
    assert result["non_blocking"] is True


def test_duplicate_within_window_reuses_uuid_and_counts(tmp_path):
    state_file = tmp_path / "st.json"
    state = guard.default_state()
    event = make_failure_event()
    # 首次提交并登记
    guard.record_submission(event, state, T0, "uuid-1")
    # 10 分钟后同一失败再次发生：复用 UUID，本地累加计数
    later = guard.parse_now("2026-07-10T08:10:00Z")
    result = run_decide(event, state, state_file, now=later)
    assert result["submit_remote"] is False
    assert result["agent_action"] == "reuse_existing_feedback_uuid"
    assert result["feedback_uuid"] == "uuid-1"
    assert result["occurrence_count"] == 2
    # 去重命中时状态会就地落盘
    assert json.loads(state_file.read_text())["failures"]


def test_failure_outside_window_resubmits(tmp_path):
    state = guard.default_state()
    event = make_failure_event()
    guard.record_submission(event, state, T0, "uuid-1")
    # 31 分钟后：窗口过期，要求重新提交
    later = guard.parse_now("2026-07-10T08:31:00Z")
    result = run_decide(event, state, tmp_path / "st.json", now=later)
    assert result["submit_remote"] is True
    assert result["reason"] == "new_failure_or_dedupe_window_expired"


def test_duplicate_missing_uuid_forces_resubmit(tmp_path):
    # 记录损坏（缺 feedback_uuid）：不得复用空 UUID，必须重新提交
    state = guard.default_state()
    event = make_failure_event()
    fp, _, _ = guard.fingerprint_details(event)
    state["failures"][fp] = {"last_seen": guard.iso(T0), "occurrence_count": 1}
    result = run_decide(event, state, tmp_path / "st.json")
    assert result["submit_remote"] is True
    assert result["reason"] == "duplicate_failure_missing_feedback_uuid"


# ---------- feedback_group_key 批量聚合 ----------


def test_group_key_overrides_varying_tool_and_params(tmp_path):
    # 显式 group key：命令字符串和参数不同的同根因失败必须命中同一指纹
    e1 = make_failure_event(
        command_name="opscli query simple --table-id 1",
        call_params={"table_id": 1},
        feedback_group_key="smoke-batch-QS-EXE-001",
    )
    e2 = make_failure_event(
        command_name="opscli query simple --table-id 99",
        call_params={"table_id": 99, "extra": "x"},
        feedback_group_key="smoke-batch-QS-EXE-001",
    )
    fp1, src1, _ = guard.fingerprint_details(e1)
    fp2, src2, _ = guard.fingerprint_details(e2)
    assert src1 == src2 == "feedback_group_key"
    assert fp1 == fp2

    # 后续同组失败复用首条的 feedback_uuid
    state = guard.default_state()
    guard.record_submission(e1, state, T0, "uuid-group")
    result = run_decide(e2, state, tmp_path / "st.json")
    assert result["agent_action"] == "reuse_existing_feedback_uuid"
    assert result["feedback_uuid"] == "uuid-group"


def test_without_group_key_different_params_have_different_fingerprints():
    fp1, _, _ = guard.fingerprint_details(make_failure_event(call_params={"table_id": 1}))
    fp2, _, _ = guard.fingerprint_details(make_failure_event(call_params={"table_id": 2}))
    assert fp1 != fp2


# ---------- L2 会话预算 ----------


def test_l2_without_owner_action_stays_local(tmp_path):
    event = {"outcome": "zero_rows", "source": "cli", "session_id": "sess-1"}
    result = run_decide(event, guard.default_state(), tmp_path / "st.json")
    assert result["submit_remote"] is False
    assert result["reason"] == "owner_action_not_required"


def test_l2_budget_allows_one_then_exhausts(tmp_path):
    state = guard.default_state()
    event = {"outcome": "zero_rows", "source": "cli", "needs_owner_action": True, "session_id": "sess-1"}
    # 预算未用：放行 1 条
    first = run_decide(event, state, tmp_path / "st.json")
    assert first["submit_remote"] is True
    assert first["agent_action"] == "submit_single_suspicious_summary"
    # 提交成功登记后：预算耗尽，后续只写本地
    guard.record_submission(event, state, T0, "uuid-l2")
    second = run_decide(event, state, tmp_path / "st.json")
    assert second["submit_remote"] is False
    assert second["reason"] == "non_failure_remote_budget_exhausted"


def test_l2_budget_isolated_by_session(tmp_path):
    # 预算按 session_id 隔离：sess-1 耗尽不影响 sess-2
    state = guard.default_state()
    e1 = {"outcome": "zero_rows", "needs_owner_action": True, "session_id": "sess-1"}
    guard.record_submission(e1, state, T0, "uuid-a")
    e2 = {"outcome": "zero_rows", "needs_owner_action": True, "session_id": "sess-2"}
    result = run_decide(e2, state, tmp_path / "st.json")
    assert result["submit_remote"] is True
    assert result["budget_scope"] == "sess-2"


# ---------- 敏感字段脱敏与事件瘦身 ----------


def test_sensitive_values_redacted_from_fingerprint_and_state(tmp_path):
    secret = "super-secret-value-abc"
    event = make_failure_event(call_params={"table_id": 1, "token": secret, "Api-Key": secret})
    result = run_decide(event, guard.default_state(), tmp_path / "st.json")
    assert result["event_hygiene"]["sensitive_key_count"] >= 2
    # 指纹 payload 中不得出现敏感原值
    payload, _, _ = guard.fingerprint_payload(event)
    assert secret not in guard.stable_json(payload)


def test_oversized_event_compacted_within_limit():
    # 大日志事件：fingerprint payload 必须被压到 4096 bytes 以内
    event = make_failure_event(
        error_message="x" * 10000,
        call_params={f"key_{i}": "v" * 500 for i in range(100)},
    )
    _, _, hygiene = guard.fingerprint_details(event)
    assert hygiene["fingerprint_payload_bytes"] <= guard.MAX_FINGERPRINT_PAYLOAD_BYTES
    assert hygiene["oversized_value_count"] > 0


# ---------- 状态损坏兜底与过期清理 ----------


def test_corrupted_state_file_treated_as_empty(tmp_path):
    state_file = tmp_path / "st.json"
    state_file.write_text("{not valid json", encoding="utf-8")
    state = guard.load_state(state_file)
    # 损坏状态按空状态继续，不抛异常
    assert state["failures"] == {}
    result = run_decide(make_failure_event(), state, state_file)
    assert result["submit_remote"] is True


def test_prune_removes_stale_failures_and_sessions():
    state = guard.default_state()
    event = make_failure_event()
    guard.record_submission(event, state, T0, "uuid-old")
    l2_event = {"outcome": "zero_rows", "needs_owner_action": True, "session_id": "sess-old"}
    guard.record_submission(l2_event, state, T0, "uuid-l2-old")
    # 25 小时后（超过 24 小时保留期）：过期指纹和预算桶被清理
    later = guard.parse_now("2026-07-11T09:00:00Z")
    changed = guard.prune_state(state, later, guard.DEFAULT_STATE_RETENTION_SECONDS)
    assert changed is True
    assert state["failures"] == {}
    assert "sess-old" not in state["sessions"]


# ---------- record 登记 ----------


def test_record_l1_is_rejected():
    # L1 成功事件本不该远端提交，record 视为无效登记
    result = guard.record_submission({"outcome": "success"}, guard.default_state(), T0, "uuid-x")
    assert result["recorded"] is False


def test_record_l3_preserves_first_seen():
    state = guard.default_state()
    event = make_failure_event()
    guard.record_submission(event, state, T0, "uuid-1")
    later = guard.parse_now("2026-07-10T09:00:00Z")
    result = guard.record_submission(event, state, later, "uuid-2")
    fp = result["fingerprint"]
    record = state["failures"][fp]
    # 重新提交刷新 UUID 和 last_seen，但保留首次出现时间
    assert record["feedback_uuid"] == "uuid-2"
    assert record["first_seen"] == guard.iso(T0)
    assert record["occurrence_count"] == 2
