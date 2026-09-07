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


@pytest.mark.parametrize(
    "query",
    [
        "查询8月各部门的销售情况",
        "所有部门的销售情况，按部门分组，不筛选具体部门",
        "按部门汇总销售额和销量",
        "不限部门，按部门统计销量",
        "不按部门筛选，按部门汇总销售额",
        "部门筛选为空，按部门统计销量",
    ],
)
def test_department_grouping_is_not_ranked_as_specific_filter_value(query):
    """guidance 不能把部门分组或否定筛选提升为具体部门筛选意图。"""
    assert dataset_guidance._has_department_filter_value(query) is False


@pytest.mark.parametrize(
    "query",
    ["查询项目二部的销量", "部门是宁波的销量", "分析泛泰克的数据"],
)
def test_specific_department_value_is_still_detected(query):
    """收紧规则后仍保留编号、显式标签和组织分析三类真实筛选。"""
    assert dataset_guidance._has_department_filter_value(query) is True


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


# ── 默认条件聚合（R5，自 tests/skills/test_dataset_guidance_default_filters.py 移植）──
#
# build_guidance 返回体顶层 default_filters 键的聚合行为：
# - 自身字段中 filter_config 已启用的条目；
# - select_columns 关联的组件数据集字段中 filter_config 已启用的条目；
# - 未配置 filter_config 的数据集返回空列表。

# filter_config 启用行（后端下发形态）
_ENABLED_FC = {
    "type": "required",
    "enabled": True,
    "operator": "equals",
    "filter_type": "enum",
    "enum_value": ["QUARTER"],
    "value": None,
    "filter_agg": "none",
}


def _filter_config_payload(*, with_filter_config: bool) -> dict:
    """ds_a 主数据集 + ds_comp 组件数据集，按需给字段挂 filter_config。

    ds_a.date_type 与 ds_comp.platform_name 配置 required 默认条件；
    ds_a 通过 select_columns 关联 platform_name → ds_comp。
    """
    def _field(alias: str, name: str, label: str, table_id: int, ftype: str, fc: dict | None):
        row = {
            "table_id": table_id,
            "dataset_alias": alias,
            "dataset_name": "主数据集" if alias == "ds_a" else "组件数据集",
            "field_name": name,
            "verbose_name": label,
            "global_alias": f"f_{name}",
            "field_type": ftype,
            "has_formula_config": 0,
        }
        if fc is not None:
            row["filter_config"] = fc
        return row

    enabled = dict(_ENABLED_FC) if with_filter_config else None
    return {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_a",
                "dataset_name": "主数据集",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "主数据集说明",
                "remarks": "",
                "select_columns": (
                    [
                        {
                            "column_name": "platform_name",
                            "verbose_name": "平台名称",
                            "component_dataset_alias": "ds_comp",
                        }
                    ]
                    if with_filter_config
                    else []
                ),
            },
            {
                "table_id": 2,
                "dataset_alias": "ds_comp",
                "dataset_name": "组件数据集",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "平台枚举组件",
                "remarks": "",
                "select_columns": [],
            },
        ],
        "fields": [
            _field("ds_a", "date_type", "日期类型", 1, "dimension", enabled),
            _field("ds_a", "gmv", "GMV", 1, "metric", None),
            _field("ds_comp", "platform_name", "平台名称", 2, "dimension", enabled),
            _field("ds_comp", "region", "地区", 2, "dimension", None),
        ],
    }


def test_build_guidance_collects_default_filters():
    """build_guidance 顶层 default_filters 聚合自身字段与组件关联字段的默认条件。"""
    adapter = MetadataAdapter(_filter_config_payload(with_filter_config=True))
    result = dataset_guidance.build_guidance(adapter, "ds_a", query="按日期看GMV")
    defaults = result["default_filters"]
    by_name = {item["field_name"]: item for item in defaults}
    # 自身字段：ds_a.date_type 配置了 required 默认条件
    assert by_name["date_type"]["source_dataset_alias"] == "ds_a"
    assert by_name["date_type"]["filter_config"]["enum_value"] == ["QUARTER"]
    # 组件关联字段：ds_comp.platform_name 通过 select_columns 关联，配置了 required 默认条件
    assert by_name["platform_name"]["source_dataset_alias"] == "ds_comp"
    # 六键压缩契约：filter_config 不得携带 enabled 键（下游 query_plan 依赖此形态）
    fc = by_name["date_type"]["filter_config"]
    assert "enabled" not in fc
    assert set(fc) <= {"type", "operator", "filter_type", "enum_value", "value", "filter_agg"}


def test_build_guidance_default_filters_empty_when_unconfigured():
    """未配置任何 filter_config 的数据集，default_filters 应返回空列表。"""
    adapter = MetadataAdapter(_filter_config_payload(with_filter_config=False))
    result = dataset_guidance.build_guidance(adapter, "ds_a", query="按日期看GMV")
    assert result["default_filters"] == []


def test_empty_query_component_derives_fields_from_select_columns():
    """空组件从现有关系派生枚举字段，不新增旁路索引。"""
    payload = {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_main",
                "dataset_name": "main_set",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "主数据集",
                "remarks": "",
                "select_columns": [
                    {
                        "column_name": "dept_name",
                        "verbose_name": "部门",
                        "component_dataset_alias": "ds_dept",
                    }
                ],
            },
            {
                "table_id": 48,
                "dataset_alias": "ds_dept",
                "dataset_name": "custom_dept_set",
                "dataset_category": "query_component",
                "inner_where_enabled": 0,
                "description": "查询组件部门数据集",
                "remarks": "",
                "select_columns": [],
            },
        ],
        "fields": [
            {
                "table_id": 1,
                "dataset_alias": "ds_main",
                "dataset_name": "main_set",
                "field_name": "amount",
                "verbose_name": "金额",
                "global_alias": "f_amount",
                "field_type": "metric",
                "has_formula_config": 0,
            }
        ],
    }
    result = dataset_guidance.build_guidance(
        MetadataAdapter(payload),
        "ds_dept",
        query="部门枚举值",
        requested_fields=["dept_name"],
    )
    assert result["guidance_status"] == "permission_enum_only"
    assert result["field_guidance"]["dimensions"][0]["field_name"] == "dept_name"


# ── 双注册合并与旧标签匹配（自 tests/skills/test_scoped_reader_duplicate_fields.py 移植）──
#
# BI 发布包同一物理字段可能挂多个全局别名（2026-07-15 实测即时综合数据集 44 个字段
# 双注册），曾令下游 duplicate_dataset_field 硬失败、整个数据集不可查且升级无法自愈。
# 内核合并逻辑在 MetadataAdapter._merge_duplicate_field_rows，逐字对齐旧 CSV 读取器。


def _dup_payload(*fields: dict) -> dict:
    """构造只含 ds_a 一张表的最小 payload，字段行由调用方给定。"""
    return {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_a",
                "dataset_name": "set_a",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": list(fields),
    }


def _dup_field(name: str, label: str, ftype: str, **extra) -> dict:
    row = {
        "table_id": 1,
        "dataset_alias": "ds_a",
        "dataset_name": "set_a",
        "field_name": name,
        "verbose_name": label,
        "field_type": ftype,
        "has_formula_config": 0,
        "snapshot_metric": 0,
    }
    row.update(extra)
    return row


def test_label_only_duplicate_merged_with_alt_names():
    """形态一：纯标签差异的双注册合并为一行，中文展示名优先，旧标签进 alt。"""
    adapter = MetadataAdapter(
        _dup_payload(
            # 英文占位标签的旧注册在前，中文标签注册在后 → 主行仍应取中文标签
            _dup_field("development_type", "development_type", "dimension"),
            _dup_field("development_type", "开发类型", "dimension"),
        )
    )
    rows = adapter.fields_rows()
    assert len(rows) == 1
    assert rows[0]["verbose_name"] == "开发类型"
    assert rows[0]["alt_verbose_names"] == ["development_type"]


def test_formula_vs_plain_duplicate_prefers_formula():
    """形态二：公式 vs 裸指标双注册优先采纳公式口径（均值/比率不可再累加）。"""
    adapter = MetadataAdapter(
        _dup_payload(
            _dup_field("avg_price_cny", "销售价", "metric"),
            _dup_field(
                "avg_price_cny",
                "平均交易价",
                "metric",
                summary_expression="ROUND(SUM(price) / SUM(order_qty), 4)",
                detail_expression="ROUND(price / order_qty, 4)",
                has_formula_config=1,
            ),
        )
    )
    rows = adapter.fields_rows()
    assert len(rows) == 1
    assert rows[0]["has_formula_config"] == "1"
    assert rows[0]["verbose_name"] == "平均交易价"
    # 裸注册的旧标签保留为备选名，供点名解析与打分识别
    assert rows[0]["alt_verbose_names"] == ["销售价"]


def test_conflicting_duplicate_kept_for_downstream_hard_fail():
    """形态外冲突（维度 vs 指标）不合并，下游唯一性校验仍硬失败。"""
    adapter = MetadataAdapter(
        _dup_payload(
            _dup_field("mixed_field", "标签甲", "dimension"),
            _dup_field("mixed_field", "标签乙", "metric"),
        )
    )
    rows = adapter.fields_rows()
    assert len(rows) == 2
    with pytest.raises(ValueError, match="duplicate_dataset_field"):
        dataset_guidance._validated_dataset_fields(
            rows, {"dataset_alias": "ds_a", "dataset_name": "set_a"}
        )


def test_identical_duplicate_rows_deduplicated():
    """完全相同的重复行静默去重（发布管线幂等导出的兜底）。"""
    adapter = MetadataAdapter(
        _dup_payload(
            _dup_field("channel_name", "渠道", "dimension"),
            _dup_field("channel_name", "渠道", "dimension"),
        )
    )
    rows = adapter.fields_rows()
    assert len(rows) == 1
    assert "alt_verbose_names" not in rows[0]


def test_alt_labels_participate_in_matching():
    """打分与点名解析覆盖 alt_verbose_names（旧标签查询不丢命中）。"""
    field = {
        "field_name": "price_ds",
        "verbose_name": "销售额(自发货)",
        "alt_verbose_names": ["交易额(自发货)"],
    }
    query = dataset_guidance._normalize("近7天交易额(自发货)按渠道汇总")
    score = dataset_guidance._field_score(field, query, dataset_guidance._tokens(query))
    assert score >= 90
    selected, unknown = dataset_guidance._resolve_requested_fields(
        [field], ["交易额(自发货)"]
    )
    assert selected == {"price_ds"}
    assert unknown == []


def test_ambiguous_alt_label_triggers_clarification():
    """同一旧标签挂在多个字段上时点名进入澄清而非静默择一。"""
    fields = [
        {
            "field_name": "avg_price_cny",
            "verbose_name": "平均交易价",
            "alt_verbose_names": ["销售价"],
        },
        {
            "field_name": "avg_original_price_cny",
            "verbose_name": "平均原价",
            "alt_verbose_names": ["销售价"],
        },
    ]
    selected, unknown = dataset_guidance._resolve_requested_fields(fields, ["销售价"])
    assert selected == set()
    assert unknown == ["销售价"]


def test_requested_field_preserves_case_sensitive_technical_identity():
    """同表 SPU/spu 技术字段先按原始大小写精确匹配，不被 casefold 合并。"""
    fields = [
        {"field_name": "SPU", "verbose_name": "SPU"},
        {"field_name": "spu", "verbose_name": "spu"},
    ]
    assert dataset_guidance._resolve_requested_fields(fields, ["SPU"]) == ({"SPU"}, [])
    assert dataset_guidance._resolve_requested_fields(fields, ["spu"]) == ({"spu"}, [])


def test_exact_label_precedes_casefolded_technical_name():
    """VCPM 展示名精确命中优先于另一字段 vcpm 的大小写不敏感技术名。"""
    fields = [
        {"field_name": "vcpm", "verbose_name": "VCPM(原币)"},
        {"field_name": "vcpm_cny", "verbose_name": "VCPM"},
    ]
    assert dataset_guidance._resolve_requested_fields(fields, ["VCPM"]) == (
        {"vcpm_cny"},
        [],
    )
    assert dataset_guidance._resolve_requested_fields(fields, ["vcpm"]) == ({"vcpm"}, [])
