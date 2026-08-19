"""字段/权限指导移植对拍：adapter → dataset_guidance_v1。

验证 dataset_guidance.build_guidance 迁入内核后签名改为消费 MetadataAdapter，
关键分支保持不变：snapshot_metric==1 字段落入快照聚合口径、未知点名字段回显澄清。
"""

import pytest

from opscli.query.services.planner.metadata_adapter import MetadataAdapter
from opscli.query.services.planner import dataset_guidance


def _payload():
    """库存数据集：含日期维度、快照指标（库存量）、普通指标（销售额）。"""
    return {
        "datasets": [
            {
                "table_id": 10,
                "dataset_alias": "ds_inv",
                "dataset_name": "库存数据集",
                "dataset_category": "normal",
                "description": "库存即时数据",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 10,
                "dataset_alias": "ds_inv",
                "dataset_name": "库存数据集",
                "field_name": "stat_date",
                "verbose_name": "统计日期",
                "global_alias": "f_d",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 10,
                "dataset_alias": "ds_inv",
                "dataset_name": "库存数据集",
                "field_name": "inventory_qty",
                "verbose_name": "库存量",
                "global_alias": "f_iq",
                "field_type": "metric",
                "snapshot_metric": 1,
                "has_formula_config": 0,
            },
            {
                "table_id": 10,
                "dataset_alias": "ds_inv",
                "dataset_name": "库存数据集",
                "field_name": "sales_amount",
                "verbose_name": "销售额",
                "global_alias": "f_sa",
                "field_type": "metric",
                "has_formula_config": 0,
            },
        ],
    }


def test_build_guidance_ready_with_dimensions_and_metrics():
    """选定数据集 → guidance ready，含维度/指标与日期字段，携带元数据指纹。"""
    adapter = MetadataAdapter(_payload())
    result = dataset_guidance.build_guidance(adapter, "ds_inv", query="库存量")
    assert result["contract"] == "dataset_guidance_v1"
    assert result["guidance_status"] == "ready"
    fg = result["field_guidance"]
    assert fg["dimension_count"] == 1 and fg["metric_count"] == 2
    # 日期维度无条件输出
    assert any(d["field_name"] == "stat_date" for d in fg["date_fields"])
    # 元数据指纹为非空字符串
    assert isinstance(result["metadata_fingerprint"], str) and result["metadata_fingerprint"]


def test_snapshot_metric_uses_snapshot_aggregation_policy():
    """snapshot_metric==1 的库存量落入快照聚合口径（禁止跨期累加）。"""
    adapter = MetadataAdapter(_payload())
    result = dataset_guidance.build_guidance(
        adapter, "ds_inv", query="库存量", requested_fields=("库存量",)
    )
    metrics = {m["field_name"]: m for m in result["field_guidance"]["metrics"]}
    inv = metrics["inventory_qty"]
    assert inv["is_snapshot"] is True
    assert inv["aggregation_policy"] == dataset_guidance.SNAPSHOT_RULE
    assert result["field_guidance"]["snapshot_field_count"] == 1


def test_unknown_requested_field_triggers_clarify():
    """点名一个不存在字段 → clarify_required 并回显 unknown_requested_fields。"""
    adapter = MetadataAdapter(_payload())
    result = dataset_guidance.build_guidance(
        adapter, "ds_inv", query="随便", requested_fields=("不存在的字段",)
    )
    assert result["guidance_status"] == "clarify_required"
    assert "不存在的字段" in result["field_guidance"]["unknown_requested_fields"]
    assert result["next_action"] == "clarify_fields"


def test_fully_duplicate_rows_are_self_healed():
    """整行完全重复（2026-08-11 事故形态）应静默去重通过，而不是 blocked。"""
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "qty",
            "field_type": "metric",
            "summary_expression": "",
        },
    ]
    selected = dataset_guidance._validated_dataset_fields(
        rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}
    )
    assert [r["field_name"] for r in selected] == ["sales", "qty"]


def test_same_name_different_definition_still_blocks():
    """同名不同定义去重会静默选错口径，必须维持阻断。"""
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(b)",
        },
    ]
    with pytest.raises(ValueError, match="duplicate_dataset_field"):
        dataset_guidance._validated_dataset_fields(
            rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}
        )


def test_duplicate_rows_deduped_count_surfaces_via_advisory():
    """去重条数需通过 advisory 出参带给调用方，供上层向用户披露。"""
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "qty",
            "field_type": "metric",
            "summary_expression": "",
        },
    ]
    advisory: dict = {}
    dataset_guidance._validated_dataset_fields(
        rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}, advisory
    )
    assert advisory["duplicate_fields_deduped_count"] == 1


def test_dict_valued_column_does_not_break_dedup():
    """字段行含 filter_config 这类 dict/None 混合列时，去重不得因不可哈希而报错。

    MetadataAdapter.fields_rows 产出的字段行都带 filter_config 列，取值为
    dict 或 None；tuple(sorted(row.items())) 式的去重键遇到 dict 值会因不可
    哈希而抛 TypeError，必须改用可序列化的键。
    """
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "filter_config": {"type": "enum", "enabled": True},
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "filter_config": {"type": "enum", "enabled": True},
        },
    ]
    selected = dataset_guidance._validated_dataset_fields(
        rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}
    )
    assert len(selected) == 1


def test_build_guidance_duplicate_fields_deduped_count_defaults_to_zero():
    """无重复行时 duplicate_fields_deduped_count 恒为 0，不产生虚假披露。

    注：MetadataAdapter.fields_rows() 内部的 _merge_duplicate_field_rows 已经会把
    整行完全重复的字段行在到达 _validated_dataset_fields 之前合并掉一次，因此无法
    经由 build_guidance(adapter, ...) 这条完整路径反向构造出 count>0 的用例；
    duplicate_fields_deduped_count>0 的行为已在上面对 _validated_dataset_fields
    的直接单元测试中覆盖，这里只保证 field_guidance 的键形状与默认值稳定。
    """
    adapter = MetadataAdapter(_payload())
    result = dataset_guidance.build_guidance(adapter, "ds_inv", query="库存量")
    assert result["field_guidance"]["duplicate_fields_deduped_count"] == 0
