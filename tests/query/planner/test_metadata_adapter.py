"""元数据适配器：query-metadata JSON → scoped_dataset_reader 同形行。

适配器把 QueryManager.metadata_all() 的 payload（datasets 内嵌 select_columns/
filter_configs、fields 扁平列表）映射为与旧 scoped_dataset_reader.load_* 同形的
行字典，供下游选表/字段指导逻辑近乎逐字移植消费。
"""

from opscli.query.services.planner.metadata_adapter import MetadataAdapter


def _payload():
    """构造一个覆盖数据集/维度/指标/组件列的最小 payload。"""
    return {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_a",
                "dataset_name": "订单",
                "dataset_category": "sales",
                "inner_where_enabled": True,
                "description": "订单数据",
                "remarks": "",
                "select_columns": [
                    {
                        "column_name": "channel_uuid",
                        "verbose_name": "渠道",
                        "component_dataset_alias": "ds_ch",
                    }
                ],
                "filter_configs": [],
            },
        ],
        "fields": [
            {
                "table_id": 1,
                "dataset_alias": "ds_a",
                "dataset_name": "订单",
                "field_name": "amount",
                "verbose_name": "金额",
                "global_alias": "f_amt",
                "field_type": "metric",
                "summary_expression": "sum(amount)",
                "detail_expression": "amount",
                "has_formula_config": 1,
            },
            {
                "table_id": 1,
                "dataset_alias": "ds_a",
                "dataset_name": "订单",
                "field_name": "sku",
                "verbose_name": "SKU",
                "global_alias": "f_sku",
                "field_type": "dimension",
                "snapshot_metric": 0,
            },
        ],
    }


def test_datasets_rows_shape():
    """datasets 行含 scoped_dataset_reader 期望列，含派生 select_column_count/names。"""
    a = MetadataAdapter(_payload())
    rows = a.datasets_rows()
    assert len(rows) == 1
    r = rows[0]
    assert r["dataset_alias"] == "ds_a" and r["dataset_category"] == "sales"
    assert r["select_column_count"] == 1
    assert r["select_column_names"] == "channel_uuid"  # 单列；多列以逗号拼接


def test_fields_rows_preserve_field_columns():
    """fields 行保留 field_name/verbose_name/global_alias/field_type/表达式/快照/公式标记。"""
    a = MetadataAdapter(_payload())
    rows = a.fields_rows()
    by_name = {r["field_name"]: r for r in rows}
    assert by_name["amount"]["has_formula_config"] in (1, "1")
    assert by_name["amount"]["global_alias"] == "f_amt"
    assert by_name["sku"]["field_type"] == "dimension"
    # snapshot_metric 归一为字符串（空/缺省视同 "0"）
    assert by_name["sku"]["snapshot_metric"] in (0, "0")


def test_select_columns_rows_flatten_with_current_alias():
    """select_columns 从 datasets 内嵌展平为行，带 current_dataset_alias。"""
    a = MetadataAdapter(_payload())
    rows = a.select_columns_rows()
    assert rows == [
        {
            "current_dataset_alias": "ds_a",
            "column_name": "channel_uuid",
            "verbose_name": "渠道",
            "component_dataset_alias": "ds_ch",
        }
    ]


def test_duplicate_field_rows_merged():
    """同物理字段多 global_alias 双注册应按 scoped_dataset_reader 规则合并去重。"""
    p = _payload()
    # 构造同 field_name 不同 global_alias 的重复行（执行语义一致，应被合并）
    dup = dict(p["fields"][0])
    dup["global_alias"] = "f_amt2"
    p["fields"].append(dup)
    a = MetadataAdapter(p)
    amt = [r for r in a.fields_rows() if r["field_name"] == "amount"]
    assert len(amt) == 1  # 合并为一行（合并策略对齐 _merge_duplicate_field_rows）
