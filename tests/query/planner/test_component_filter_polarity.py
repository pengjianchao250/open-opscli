"""组件筛选正负极性的通用回归测试。

事故形态：规划器已通过授权枚举锁定“范泰克-体系外”，但丢失了值所在语段的
排除极性，最终把“排除该部门”写成 ``dept_name = ...``，查询结果只剩本应剔除
的部门。极性判断必须适用于所有组件字段，而不是为某个部门名打补丁。
"""

from __future__ import annotations

import pytest

from opscli.query.services.planner import query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


ENUMS = {
    "dept_name": ["范泰克", "范泰克-体系外"],
    "country_name": ["美国", "加拿大"],
    "channel_name": ["傲彼瑞-美国", "傲彼瑞-加拿大"],
    "brand_name": ["OHWILL", "AUKEY"],
}


def _contract() -> dict:
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_reason_codes": [], "clarification_messages_zh": []},
        "execution_ref": {
            "query_template": {"filters": []},
            "filter_components": [
                {
                    "field_name": field_name,
                    "label_zh": label,
                    "component_table_id": index,
                }
                for index, (field_name, label) in enumerate(
                    (
                        ("dept_name", "部门"),
                        ("country_name", "国家"),
                        ("channel_name", "渠道"),
                        ("brand_name", "品牌"),
                    ),
                    start=1,
                )
            ],
        },
    }


def _resolve(query: str) -> dict:
    def enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001
        return list(ENUMS.get(field_name, []))

    return query_plan._resolve_component_filters(
        _contract(), query, enum_fn, auto_enum=True
    )


@pytest.mark.parametrize(
    ("query", "field", "value"),
    [
        ("按部门汇总，排除部门：范泰克-体系外", "dept_name", "范泰克-体系外"),
        ("查询各国家销售额，国家不等于加拿大", "country_name", "加拿大"),
        ("剔除渠道傲彼瑞-加拿大后汇总", "channel_name", "傲彼瑞-加拿大"),
        ("查询各品牌毛利，OHWILL 除外", "brand_name", "OHWILL"),
        ("查询除美国之外的各国家销售额", "country_name", "美国"),
        ("query sales where brand not in OHWILL", "brand_name", "OHWILL"),
    ],
)
def test_single_component_exclusion_uses_not_equal(query, field, value):
    result = _resolve(query)

    assert result["status"] == "planned"
    assert {"field": field, "operator": "!=", "value": value} in result[
        "execution_ref"
    ]["query_template"]["filters"]
    resolved = next(
        item
        for item in result["execution_ref"]["resolved_component_filters"]
        if item["field_name"] == field
    )
    assert resolved["polarity"] == "exclude"
    assert resolved["operator"] == "!="


def test_multiple_component_exclusions_use_not_in():
    result = _resolve("排除渠道傲彼瑞-美国、傲彼瑞-加拿大后汇总销售额")

    assert result["status"] == "planned"
    assert {
        "field": "channel_name",
        "operator": "not_in",
        "value": ["傲彼瑞-美国", "傲彼瑞-加拿大"],
    } in result["execution_ref"]["query_template"]["filters"]


def test_positive_component_filter_keeps_existing_include_operator():
    result = _resolve("只看部门是范泰克-体系外的销售额")

    assert {"field": "dept_name", "operator": "=", "value": "范泰克-体系外"} in result[
        "execution_ref"
    ]["query_template"]["filters"]


def test_long_exact_value_does_not_expand_to_shorter_enum_prefix():
    result = _resolve("部门不等于范泰克-体系外")

    filters = result["execution_ref"]["query_template"]["filters"]
    assert filters == [
        {"field": "dept_name", "operator": "!=", "value": "范泰克-体系外"}
    ]


def test_cancelled_exclusion_does_not_turn_into_include_filter():
    result = _resolve("不排除部门范泰克-体系外，查询各部门销售额")

    assert result["status"] == "planned"
    assert not [
        item
        for item in result["execution_ref"]["query_template"]["filters"]
        if item.get("field") == "dept_name"
    ]


def test_same_value_with_both_polarities_fails_closed():
    result = _resolve("保留加拿大，后又排除加拿大的国家数据")

    assert result["status"] == "clarify_required"
    assert "component_filter_polarity_conflict" in result["model_view"][
        "clarification_reason_codes"
    ]
    assert "query_template" not in result["execution_ref"]


def test_real_incident_query_keeps_all_metrics_and_excludes_department():
    """真实事故句式必须同时保留指标集合、对比窗口和排除极性。"""
    business_alias = "ds_instant"
    dept_alias = "ds_dept"
    datasets = [
        {
            "table_id": 1,
            "dataset_alias": business_alias,
            "dataset_name": "instant_sales",
            "dataset_category": "normal",
            "description": "即时综合数据集",
            "remarks": "销售、毛利综合数据",
            "select_columns": [
                {
                    "column_name": "dept_name",
                    "verbose_name": "部门",
                    "component_dataset_alias": dept_alias,
                }
            ],
        },
        {
            "table_id": 2,
            "dataset_alias": dept_alias,
            "dataset_name": "department_component",
            "dataset_category": "query_component",
            "description": "部门组件",
            "remarks": "",
            "select_columns": [],
        },
    ]

    def field(table_id, alias, name, field_name, verbose_name, field_type):
        return {
            "table_id": table_id,
            "dataset_alias": alias,
            "dataset_name": name,
            "field_name": field_name,
            "verbose_name": verbose_name,
            "global_alias": f"f_{field_name}",
            "field_type": field_type,
            "has_formula_config": 0,
        }

    fields = [
        field(1, business_alias, "instant_sales", "date_id", "日期", "dimension"),
        field(1, business_alias, "instant_sales", "dept_name", "部门", "dimension"),
        field(1, business_alias, "instant_sales", "price", "销售额", "metric"),
        field(1, business_alias, "instant_sales", "gross_profit", "毛利", "metric"),
        field(2, dept_alias, "department_component", "dept_name", "部门", "dimension"),
    ]
    adapter = MetadataAdapter({"datasets": datasets, "fields": fields})

    def enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001
        return ["范泰克", "范泰克-体系外"] if field_name == "dept_name" else []

    result = query_plan.build_model_query_plan(
        adapter,
        "获取8月份各部门的收入及毛利情况，并环比7月数据，排除部门：范泰克-体系外",
        requested_fields=[],
        refresh_fn=None,
        enum_fn=enum_fn,
    )

    assert result["status"] == "planned"
    assert result["model_view"]["metrics"] == ["销售额", "毛利"]
    assert result["model_view"]["field_alias_mappings_zh"] == [
        {"requested": "收入", "field_zh": "销售额", "field_name": "price"}
    ]
    template = result["execution_ref"]["query_template"]
    assert [item["field"] for item in template["metrics"]] == ["price", "gross_profit"]
    assert {
        "field": "dept_name",
        "operator": "!=",
        "value": "范泰克-体系外",
    } in template["filters"]
    assert template["dataComparison"]["field"] == "date_id"
