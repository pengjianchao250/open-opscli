"""run_query 默认条件披露测试（服务端权威注入，客户端只披露不预注入）。"""
# 导入方式与 test_dataset_query_planner.py 一致
import sys
from pathlib import Path

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_query  # noqa: E402


REQUIRED_DEFAULT = {
    "field_name": "date_type", "label_zh": "日期类型", "operator": "equals",
    "values": ["QUARTER"], "type": "required", "filter_type": "enum", "filter_agg": "none",
}


def test_apply_discloses_missing_required():
    """required 且用户无该字段：payload 不变，note 披露服务端将自动应用。"""
    original_filter = {"field": "date_id", "operator": ">=", "value": "2026-07-01"}
    payload = {"filters": [dict(original_filter)]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    # payload["filters"] 不应被修改：长度不变，不含 date_type 条目
    assert len(payload["filters"]) == 1, "payload filters 不应被注入新条目"
    assert not any(f.get("field") == "date_type" for f in payload["filters"]), \
        "payload 中不应出现 date_type 条件"
    # 仍应有默认条件相关披露
    assert any("QUARTER" in note for note in notes), "notes 应包含 QUARTER 披露"
    assert any("服务端" in note for note in notes), "notes 应说明服务端将应用"


def test_apply_dedupes_same_or_subset_value():
    """相同值或子集：payload 不变，note 含"一致"类文案，不含"同时生效"。"""
    # 场景 1：同值
    payload = {"filters": [{"field": "date_type", "operator": "=", "value": "QUARTER"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    # payload 不变（仍只有 1 条 date_type）
    assert len([f for f in payload["filters"] if f.get("field") == "date_type"]) == 1
    assert any("已去重" in note for note in notes)
    assert not any("同时生效" in note for note in notes)

    # 场景 2：子集去重（用户条件是默认值的子集）
    subset_default = dict(REQUIRED_DEFAULT, values=["QUARTER", "MONTH"])
    payload2 = {"filters": [{"field": "date_type", "operator": "=", "value": "QUARTER"}]}
    notes2 = run_query._apply_default_filters(payload2, [subset_default])
    assert len([f for f in payload2["filters"] if f.get("field") == "date_type"]) == 1
    assert any("已去重" in note for note in notes2)
    assert not any("同时生效" in note for note in notes2)


def test_apply_keeps_both_on_conflict():
    """冲突场景：payload 不变（服务端负责 AND 合并），note 含"同时生效"。"""
    payload = {"filters": [{"field": "date_type", "operator": "=", "value": "MONTH"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    # payload 不变：只有用户原有的 1 条 date_type，不额外追加
    assert len([f for f in payload["filters"] if f.get("field") == "date_type"]) == 1, \
        "payload 不应被修改，date_type 条目仍只有 1 条"
    assert any("同时生效" in note for note in notes)


def test_apply_multi_values_discloses_and_optional_skipped():
    """多值 required：payload 不变，note 存在；optional 用户已有时跳过，也不修改 payload。"""
    # required 多值：不注入 in 条件，只披露
    multi = dict(REQUIRED_DEFAULT, values=["QUARTER", "MONTH"])
    payload = {"filters": []}
    notes = run_query._apply_default_filters(payload, [multi])
    assert payload["filters"] == [], "payload filters 应保持为空，不注入多值条件"
    assert any("QUARTER" in note or "MONTH" in note for note in notes), \
        "notes 应包含多值披露"

    # optional 用户已有同字段：跳过，payload 不变
    optional = dict(REQUIRED_DEFAULT, type="optional")
    payload2 = {"filters": [{"field": "date_type", "operator": "=", "value": "MONTH"}]}
    run_query._apply_default_filters(payload2, [optional])
    assert len(payload2["filters"]) == 1, "optional 用户已有时 payload 不变"


def test_apply_optional_discloses_when_missing():
    """optional 且用户未提供同字段条件：payload 不变，note 提示服务端将应用。"""
    optional = dict(REQUIRED_DEFAULT, type="optional")
    payload = {"filters": []}
    notes = run_query._apply_default_filters(payload, [optional])
    # payload 不被注入
    assert payload["filters"] == [], "optional 缺失时 payload 仍不注入"
    # note 应说明服务端将应用
    assert any("服务端" in note for note in notes), "notes 应说明服务端将应用可选默认条件"
    assert any("QUARTER" in note for note in notes)


def test_apply_not_deduped_on_operator_mismatch():
    """同字段异操作符（!=）冲突：payload 不变，note 含"同时生效"。"""
    payload = {"filters": [{"field": "date_type", "operator": "!=", "value": "QUARTER"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    # payload 不变：只有原有 1 条，不追加
    assert len([f for f in payload["filters"] if f.get("field") == "date_type"]) == 1, \
        "payload 不应被修改"
    assert any("同时生效" in note for note in notes)
