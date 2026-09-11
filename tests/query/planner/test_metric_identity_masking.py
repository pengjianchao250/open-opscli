"""精确指标优先级与数据集身份遮蔽的合同级回归。"""

from __future__ import annotations

from opscli.query.services.planner import query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


def _field(name: str, label: str, field_type: str, *, snapshot: bool = False) -> dict:
    return {
        "table_id": 1,
        "dataset_alias": "ds_finance",
        "dataset_name": "finance_detail",
        "field_name": name,
        "verbose_name": label,
        "global_alias": f"f_{name}",
        "field_type": field_type,
        "snapshot_metric": 1 if snapshot else 0,
        "has_formula_config": 0,
    }


def _plan(description: str, fields: list[dict], query: str) -> dict:
    adapter = MetadataAdapter(
        {
            "datasets": [
                {
                    "table_id": 1,
                    "dataset_alias": "ds_finance",
                    "dataset_name": "finance_detail",
                    "dataset_category": "normal",
                    "description": description,
                    "remarks": "经营指标明细",
                    "select_columns": [],
                }
            ],
            "fields": [_field("date_id", "日期", "dimension"), *fields],
        }
    )
    return query_plan.build_model_query_plan(
        adapter,
        query,
        requested_fields=[],
        refresh_fn=None,
        enum_fn=lambda *_args, **_kwargs: [],
    )


def test_exact_long_metrics_do_not_request_contained_standard_aliases():
    fields = [
        _field("main_revenue", "主营业务收入", "metric"),
        _field("main_cost", "主营业务成本", "metric"),
    ]

    result = _plan(
        "净利分解数据集",
        fields,
        "在“净利分解数据集”里汇总主营业务收入、主营业务成本，看2026年8月",
    )

    assert result["status"] == "planned"
    assert [item["field_name"] for item in result["execution_ref"]["metrics"]] == [
        "main_revenue",
        "main_cost",
    ]
    assert "unknown_requested_fields" not in result["model_view"]


def test_dataset_title_metric_word_is_not_selected_as_a_metric():
    fields = [
        _field("rent_amount_cny", "仓租", "metric", snapshot=True),
        _field("avg_price", "平均单价(原币)", "metric"),
    ]

    result = _plan(
        "SKU仓租库龄明细",
        fields,
        "用“SKU仓租库龄明细”查看2026年8月平均单价(原币)趋势",
    )

    assert result["status"] == "planned"
    assert [item["field_name"] for item in result["execution_ref"]["metrics"]] == [
        "avg_price"
    ]


def test_metric_word_repeated_outside_dataset_title_is_still_selected():
    fields = [
        _field("rent_amount_cny", "仓租", "metric", snapshot=True),
        _field("avg_price", "平均单价(原币)", "metric"),
    ]

    result = _plan(
        "SKU仓租库龄明细",
        fields,
        "从“SKU仓租库龄明细”查看2026年8月末的仓租",
    )

    assert result["status"] == "planned"
    assert [item["field_name"] for item in result["execution_ref"]["metrics"]] == [
        "rent_amount_cny"
    ]


def test_action_suffix_does_not_create_an_extra_metric():
    fields = [
        _field("total_cost_days", "总周转天数", "metric"),
        _field("sell_cost_days", "周转天数(可售)", "metric", snapshot=True),
        _field(
            "sell_intransit_cost_days",
            "周转天数(可售+在途)",
            "metric",
            snapshot=True,
        ),
    ]

    result = _plan(
        "库存周转数据集",
        fields,
        "在“库存周转数据集”里汇总周转天数(可售)、周转天数(可售+在途)，范围为2026年8月",
    )

    assert result["status"] == "planned"
    assert [item["field_name"] for item in result["execution_ref"]["metrics"]] == [
        "sell_cost_days",
        "sell_intransit_cost_days",
    ]
    assert result["execution_ref"]["snapshot_policy"]["snapshot_day"] == "2026-08-31"


def test_unique_parenthetical_base_name_selects_the_metric():
    result = _plan(
        "海运在途SKU明细",
        [_field("shipment_turnaround_time", "上船时效(天)", "metric")],
        "从海运在途SKU明细按日期看2026年8月上船时效",
    )

    assert result["status"] == "planned"
    assert [item["field_name"] for item in result["execution_ref"]["metrics"]] == [
        "shipment_turnaround_time"
    ]


def test_ambiguous_parenthetical_base_name_requires_clarification():
    result = _plan(
        "库存周转数据集",
        [
            _field("sell_days", "周转天数(可售)", "metric"),
            _field("sell_intransit_days", "周转天数(可售+在途)", "metric"),
        ],
        "从库存周转数据集看2026年8月周转天数",
    )

    assert result["status"] == "clarify_required"
    assert "field_identity" in result["model_view"]["clarification_reason_codes"]


def test_unbound_technical_metric_in_natural_language_requires_clarification():
    result = _plan(
        "即时综合数据集",
        [_field("price", "销售额", "metric")],
        "即时综合数据集2026年8月按部门看price",
    )

    assert result["status"] == "clarify_required"
    assert "recommended_fields_confirmation" in result["model_view"][
        "clarification_reason_codes"
    ]
    assert "price" in result["model_view"]["unknown_requested_fields"]
    assert "query_template" not in result["execution_ref"]
    assert "--field" in " ".join(result["model_view"]["pending_confirmations_zh"])


def test_natural_label_equal_to_technical_name_is_not_blocked():
    result = _plan(
        "ASIN明细",
        [_field("asin", "ASIN", "dimension"), _field("price", "销售额", "metric")],
        "从ASIN明细按ASIN看2026年8月销售额",
    )

    assert result["status"] == "planned"


def test_base_name_inside_longer_exact_metric_does_not_add_another_metric():
    result = _plan(
        "广告数据集",
        [
            _field("sales", "销售额(原币)", "metric"),
            _field("ad_sales", "广告销售额", "metric"),
        ],
        "从广告数据集看2026年8月广告销售额",
    )

    assert result["status"] == "planned"
    assert [item["field_name"] for item in result["execution_ref"]["metrics"]] == [
        "ad_sales"
    ]


def test_component_matching_masks_full_technical_dataset_identity():
    adapter = MetadataAdapter(
        {
            "datasets": [
                {
                    "table_id": 1,
                    "dataset_alias": "ds_sales",
                    "dataset_name": "order_sale_trend_adv_traffic_inv_set",
                    "dataset_category": "normal",
                    "description": "即时综合数据集",
                    "remarks": "",
                    "select_columns": [],
                }
            ],
            "fields": [],
        }
    )
    contract = {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {
            "dataset_name_zh": "即时综合数据集",
            "clarification_reason_codes": [],
            "clarification_messages_zh": [],
        },
        "execution_ref": {
            "dataset_alias": "ds_sales",
            "table_id": 1,
            "metrics": [
                {"field_name": "star", "label_zh": "星级"}
            ],
            "query_template": {"filters": []},
            "filter_components": [
                {
                    "field_name": "large_team_name",
                    "label_zh": "大组",
                    "component_table_id": 11,
                }
            ],
        },
    }

    result = query_plan._resolve_component_filters(
        contract,
        "使用数据集 order_sale_trend_adv_traffic_inv_set 查询销售额",
        lambda *_args, **_kwargs: ["OR-A", "OR-B"],
        auto_enum=True,
        adapter=adapter,
    )

    assert result["status"] == "planned"
    assert result["execution_ref"]["query_template"]["filters"] == []


def test_component_matching_masks_selected_metric_technical_identity():
    adapter = MetadataAdapter(
        {
            "datasets": [
                {
                    "table_id": 1,
                    "dataset_alias": "ds_sales",
                    "dataset_name": "traffic_set",
                    "dataset_category": "normal",
                    "description": "流量数据集",
                    "remarks": "",
                    "select_columns": [],
                }
            ],
            "fields": [],
        }
    )
    contract = {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {
            "dataset_name_zh": "流量数据集",
            "clarification_reason_codes": [],
            "clarification_messages_zh": [],
        },
        "execution_ref": {
            "dataset_alias": "ds_sales",
            "table_id": 1,
            "metrics": [
                {"field_name": "ordered_product_sales", "label_zh": "销售额(原币)"}
            ],
            "query_template": {"filters": []},
            "filter_components": [
                {
                    "field_name": "large_team_name",
                    "label_zh": "大组",
                    "component_table_id": 11,
                },
                {
                    "field_name": "brand_name",
                    "label_zh": "品牌",
                    "component_table_id": 12,
                },
            ],
        },
    }

    result = query_plan._resolve_component_filters(
        contract,
        "用 traffic_set 查询指标 ordered_product_sales",
        lambda _table_id, field_name, **_kwargs: (
            ["OR-A", "OR-B"] if field_name == "large_team_name" else ["R", "LES"]
        ),
        auto_enum=True,
        adapter=adapter,
    )

    assert result["status"] == "planned"
    assert result["execution_ref"]["query_template"]["filters"] == []


def test_component_technical_field_name_keeps_explicit_filter_semantics():
    contract = {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {
            "dataset_name_zh": "销售数据集",
            "clarification_reason_codes": [],
            "clarification_messages_zh": [],
        },
        "execution_ref": {
            "dataset_alias": "ds_sales",
            "table_id": 1,
            "query_template": {"filters": []},
            "filter_components": [
                {
                    "field_name": "brand_name",
                    "label_zh": "品牌",
                    "component_table_id": 7,
                }
            ],
        },
    }

    result = query_plan._resolve_component_filters(
        contract,
        "查询销售数据集，brand_name=R",
        lambda *_args, **_kwargs: ["R", "LES"],
        auto_enum=True,
    )

    assert result["status"] == "planned"
    assert result["execution_ref"]["query_template"]["filters"] == [
        {"field": "brand_name", "operator": "=", "value": "R"}
    ]
