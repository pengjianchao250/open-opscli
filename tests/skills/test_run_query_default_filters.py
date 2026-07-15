"""run_query 默认条件注入测试。"""
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


def test_apply_injects_missing_required():
    payload = {"filters": [{"field": "date_id", "operator": ">=", "value": "2026-07-01"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    injected = [f for f in payload["filters"] if f["field"] == "date_type"]
    assert injected == [{"field": "date_type", "operator": "=", "value": "QUARTER"}]
    assert any("QUARTER" in note for note in notes)


def test_apply_dedupes_same_or_subset_value():
    """相同值去重时应披露去重文案，不披露冲突文案。"""
    # 场景 1：同值去重
    payload = {"filters": [{"field": "date_type", "operator": "=", "value": "QUARTER"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    assert len([f for f in payload["filters"] if f["field"] == "date_type"]) == 1
    assert any("已去重" in note for note in notes)
    assert not any("同时生效" in note for note in notes)

    # 场景 2：子集去重（用户条件是默认值的子集）
    subset_default = dict(REQUIRED_DEFAULT, values=["QUARTER", "MONTH"])
    payload2 = {"filters": [{"field": "date_type", "operator": "=", "value": "QUARTER"}]}
    notes2 = run_query._apply_default_filters(payload2, [subset_default])
    assert len([f for f in payload2["filters"] if f["field"] == "date_type"]) == 1
    assert any("已去重" in note for note in notes2)
    assert not any("同时生效" in note for note in notes2)


def test_apply_keeps_both_on_conflict():
    """冲突不拦截：与服务端静默 AND 合并行为一致，披露中说明（评审结论 1）。"""
    payload = {"filters": [{"field": "date_type", "operator": "=", "value": "MONTH"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    assert len([f for f in payload["filters"] if f["field"] == "date_type"]) == 2
    assert any("同时生效" in note for note in notes)


def test_apply_multi_values_uses_in_and_optional_skipped():
    multi = dict(REQUIRED_DEFAULT, values=["QUARTER", "MONTH"])
    payload = {"filters": []}
    run_query._apply_default_filters(payload, [multi])
    assert payload["filters"][0]["operator"] == "in"

    optional = dict(REQUIRED_DEFAULT, type="optional")
    payload2 = {"filters": [{"field": "date_type", "operator": "=", "value": "MONTH"}]}
    run_query._apply_default_filters(payload2, [optional])
    assert len(payload2["filters"]) == 1


def test_apply_optional_injected_when_missing():
    """optional 且用户未提供同字段条件时也应注入（服务端合并规则表对齐）。"""
    optional = dict(REQUIRED_DEFAULT, type="optional")
    payload = {"filters": []}
    run_query._apply_default_filters(payload, [optional])
    assert payload["filters"] == [{"field": "date_type", "operator": "=", "value": "QUARTER"}]


def test_apply_not_deduped_on_operator_mismatch():
    """同值异操作符（!=）不去重：required 仍注入，两条同时生效并披露冲突（终审修复）。"""
    payload = {"filters": [{"field": "date_type", "operator": "!=", "value": "QUARTER"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    assert len([f for f in payload["filters"] if f["field"] == "date_type"]) == 2
    assert any("同时生效" in note for note in notes)
