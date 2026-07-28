"""字段/权限指导移植对拍：adapter → dataset_guidance_v1。

验证 dataset_guidance.build_guidance 迁入内核后签名改为消费 MetadataAdapter，
关键分支保持不变：snapshot_metric==1 字段落入快照聚合口径、未知点名字段回显澄清。
"""

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
