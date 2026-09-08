"""2026-09-07 多代理验收暴露的规划器缺陷回归（全部先红后绿）。

覆盖五类静默错答/漏澄清缺陷：
1. 请求点名指标（销售额）时，规划器选中没有该指标的数据集，且 metrics 为空仍 planned；
2. 币种词「加拿大元」里的「加拿大」被国家组件反查当成筛选值注入；
3. 「按日趋势/每天」未解析出日期维度，返回单行汇总；
4. 白名单外币种（港币）被静默忽略；
5. 组件筛选澄清不下发候选值与原因码。
"""

from __future__ import annotations

import pytest

from opscli.query.services.planner import query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


def _field(table_id, alias, name_zh, field_name, verbose_name, field_type):
    """构造一行后端 query-metadata 同形字段。"""
    return {
        "table_id": table_id,
        "dataset_alias": alias,
        "dataset_name": name_zh,
        "field_name": field_name,
        "verbose_name": verbose_name,
        "global_alias": f"f_{alias}_{field_name}",
        "field_type": field_type,
        "has_formula_config": 0,
    }


def _instant_dataset():
    """即时综合数据集：含日期、平台、国家、部门维度与标准销售指标，平台/国家/部门有组件。"""
    alias = "ds_instant"
    dataset = {
        "table_id": 1,
        "dataset_alias": alias,
        "dataset_name": "order_sale_trend_adv_traffic_inv_set",
        "dataset_category": "normal",
        "description": "即时综合数据集",
        "remarks": "销售 库存 广告 综合",
        "select_columns": [
            {"column_name": "platform_name", "verbose_name": "平台", "component_dataset_alias": "ds_platform"},
            {"column_name": "country_name", "verbose_name": "国家", "component_dataset_alias": "ds_country"},
            {"column_name": "dept_name", "verbose_name": "部门", "component_dataset_alias": "ds_dept"},
        ],
    }
    fields = [
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "date_id", "日期", "dimension"),
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "platform_name", "平台", "dimension"),
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "country_name", "国家", "dimension"),
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "dept_name", "部门", "dimension"),
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "team_username", "销售", "dimension"),
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "price", "销售额", "metric"),
        _field(1, alias, "order_sale_trend_adv_traffic_inv_set", "order_qty", "销量", "metric"),
    ]
    return dataset, fields


def _traffic_dataset():
    """亚马逊SC设备流量转化率：只有分摊口径销售额与流量指标，平台可筛选。"""
    alias = "ds_traffic"
    dataset = {
        "table_id": 21,
        "dataset_alias": alias,
        "dataset_name": "custom_type_asin_sales_traffic",
        "dataset_category": "normal",
        "description": "亚马逊SC设备流量转化率",
        "remarks": "亚马逊 SC ASIN 流量 转化率",
        "select_columns": [
            {"column_name": "platform_name", "verbose_name": "平台", "component_dataset_alias": "ds_platform"},
        ],
    }
    fields = [
        _field(21, alias, "custom_type_asin_sales_traffic", "date_id", "日期", "dimension"),
        _field(21, alias, "custom_type_asin_sales_traffic", "platform_name", "平台", "dimension"),
        _field(21, alias, "custom_type_asin_sales_traffic", "team_username", "销售", "dimension"),
        _field(21, alias, "custom_type_asin_sales_traffic", "type_ordered_product_sales_cny", "销售额(分摊)", "metric"),
        _field(21, alias, "custom_type_asin_sales_traffic", "sessions", "流量", "metric"),
    ]
    return dataset, fields


def _component_datasets():
    """平台/国家/部门三张权限枚举组件表。"""
    datasets = []
    fields = []
    for table_id, alias, column, label in (
        (7, "ds_platform", "platform_name", "平台"),
        (8, "ds_country", "country_name", "国家"),
        (9, "ds_dept", "dept_name", "部门"),
    ):
        datasets.append(
            {
                "table_id": table_id,
                "dataset_alias": alias,
                "dataset_name": f"component_{column}",
                "dataset_category": "query_component",
                "description": f"{label}组件",
                "remarks": "",
                "select_columns": [],
            }
        )
        fields.append(_field(table_id, alias, f"component_{column}", column, label, "dimension"))
    return datasets, fields


def _adapter(*dataset_builders):
    datasets, fields = [], []
    for builder in dataset_builders:
        ds, fs = builder()
        datasets.append(ds)
        fields.extend(fs)
    component_datasets, component_fields = _component_datasets()
    return MetadataAdapter({"datasets": datasets + component_datasets, "fields": fields + component_fields})


ENUMS = {
    "platform_name": ["Amazon", "Temu"],
    "country_name": ["加拿大", "美国"],
    "dept_name": ["项目二部", "项目六部"],
}


def _enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001 —— 与内核 enum_fn 签名一致
    del _table_id, limit
    return list(ENUMS.get(field_name, []))


def _plan(adapter, query):
    return query_plan.build_model_query_plan(
        adapter, query, requested_fields=[], refresh_fn=None, enum_fn=_enum_fn
    )


# ── 0. 默认数据集直通与收入别名 ─────────────────────────────────────────────────


def test_unspecified_dataset_auto_selects_recommendation_for_income_query():
    """未点名数据集时直接采用推荐表；“收入”稳定映射为“销售额”并生成模板。"""
    contract = _plan(_adapter(_instant_dataset), "查询8月的收入情况")

    assert contract["status"] == "planned"
    assert contract["model_view"]["dataset_name_zh"] == "即时综合数据集"
    assert contract["model_view"]["metrics"] == ["销售额"]
    recommendation = contract["model_view"]["default_dataset_recommendation_zh"]
    assert recommendation["auto_selected"] is True
    assert recommendation["confirmation_required"] is False
    assert "default_dataset_confirmation" not in contract["model_view"][
        "clarification_reason_codes"
    ]
    assert contract["execution_ref"]["query_template"]["metrics"] == [
        {"field": "price", "alias": "price", "aggregation": "SUM"}
    ]


def test_multi_metric_alias_request_clarifies_when_only_part_is_available():
    """“收入及毛利”不能因收入已命中就静默丢掉当前表缺失的毛利。"""
    contract = _plan(_adapter(_instant_dataset), "查询8月的收入及毛利情况")

    assert contract["status"] == "clarify_required"
    assert contract["model_view"]["metrics"] == ["销售额"]
    assert "metric_not_in_dataset" in contract["model_view"]["clarification_reason_codes"]
    assert "毛利" in contract["model_view"]["unknown_requested_fields"]
    assert "query_template" not in contract["execution_ref"]


def test_vague_query_only_clarifies_fields_after_default_dataset_auto_selection():
    """请求没有查询字段时可以追问字段，但不得再次要求确认推荐数据集。"""
    contract = _plan(_adapter(_instant_dataset), "查询8月的数据")

    assert contract["status"] == "clarify_required"
    recommendation = contract["model_view"]["default_dataset_recommendation_zh"]
    assert recommendation["auto_selected"] is True
    assert recommendation["confirmation_required"] is False
    reasons = contract["model_view"]["clarification_reason_codes"]
    assert "recommended_fields_confirmation" in reasons
    assert "default_dataset_confirmation" not in reasons


# ── 1. 点名指标必须进入选表与 planned 门禁 ─────────────────────────────────────


def test_named_metric_prefers_dataset_that_has_the_metric():
    """「亚马逊SC 近7天销售额」：有精确「销售额」的即时综合数据集必须胜过只有分摊口径的流量表。"""
    contract = _plan(_adapter(_instant_dataset, _traffic_dataset), "亚马逊SC 近7天销售额")
    assert contract["status"] == "planned"
    assert contract["model_view"]["dataset_name_zh"] == "即时综合数据集"
    assert contract["model_view"]["metrics"] == ["销售额"]
    # 「销售额」里的「销售」不得被当成销售人员维度
    assert "销售" not in contract["model_view"]["dimensions"]


def test_named_metric_missing_in_only_dataset_clarifies_instead_of_planned():
    """只有流量表可选时：请求的「销售额」不存在，必须澄清并给出近似字段，不得空指标 planned。"""
    contract = _plan(_adapter(_traffic_dataset), "亚马逊SC 近7天销售额")
    assert contract["status"] == "clarify_required"
    assert "metric_not_in_dataset" in contract["model_view"]["clarification_reason_codes"]
    assert "query_template" not in contract["execution_ref"]
    assert contract["model_view"]["metrics"] == []
    assert "销售" not in contract["model_view"]["dimensions"]
    suggestions = contract["model_view"].get("field_suggestions_zh") or []
    assert any(
        item.get("requested") == "销售额" and "销售额(分摊)" in item.get("candidates_zh", [])
        for item in suggestions
    ), suggestions


# ── 2. 币种词不得被当成国家筛选 ─────────────────────────────────────────────────


def test_currency_words_are_not_reused_as_country_filter():
    """「分别用人民币和加拿大元」：加拿大元是币种，不能变成 country_name=加拿大。"""
    contract = _plan(_adapter(_instant_dataset), "分别用人民币和加拿大元查近7天各平台销售额")
    assert contract["status"] == "planned"
    execution = contract["execution_ref"]
    assert execution["requested_global_currencies"] == ["CNY", "CAD"]
    for template in execution["query_templates"]:
        assert not [item for item in template["filters"] if item["field"] == "country_name"]
    assert not execution.get("resolved_component_filters")


def test_explicit_country_filter_still_resolves_next_to_currency_word():
    """币种词只屏蔽自身：原文另外点名「国家是加拿大」时国家筛选照常落地。"""
    contract = _plan(_adapter(_instant_dataset), "用加拿大元查近7天国家是加拿大的销售额")
    assert contract["status"] == "planned"
    filters = contract["execution_ref"]["query_template"]["filters"]
    assert {"field": "country_name", "operator": "=", "value": "加拿大"} in filters
    assert contract["execution_ref"]["query_template"]["globalCurrency"] == "CAD"


# ── 3. 趋势 / 按日 → 日期维度 ───────────────────────────────────────────────────


def test_daily_trend_wording_adds_date_dimension():
    """「按日趋势」「每天的」「趋势」都必须落到日期维度，返回时间序列而不是单行汇总。"""
    for query in ("近30天销售额 按日趋势", "近7天每天的销售额", "近7天销售额趋势", "近7天各平台每日销售额"):
        contract = _plan(_adapter(_instant_dataset), query)
        assert contract["status"] == "planned", query
        assert "日期" in contract["model_view"]["dimensions"], query
        template = contract["execution_ref"]["query_template"]
        assert {"field": "date_id", "alias": "date_id"} in template["dimensions"], query
        disclosures = " ".join(contract["answer_contract"]["required_disclosures_zh"])
        assert "日期" in disclosures, query


def test_negated_daily_wording_does_not_add_date_dimension():
    """「不按日拆分」是否定语境，不得反向加出日期维度。"""
    contract = _plan(_adapter(_instant_dataset), "近7天销售额，不按日拆分")
    assert contract["status"] == "planned"
    assert "日期" not in contract["model_view"]["dimensions"]


# ── 4. 白名单外币种 ─────────────────────────────────────────────────────────────


def test_unsupported_currency_requires_clarification():
    """「用港币查」：HKD 不在白名单，必须澄清而不是静默按默认币种执行。"""
    contract = _plan(_adapter(_instant_dataset), "用港币查近7天销售额")
    assert contract["status"] == "clarify_required"
    assert "unsupported_currency" in contract["model_view"]["clarification_reason_codes"]
    assert contract["model_view"]["unsupported_currencies"] == ["HKD"]
    assert "query_template" not in contract["execution_ref"]
    messages = " ".join(contract["model_view"]["clarification_messages_zh"])
    assert "USD/GBP/CAD/EUR/JPY/CNY" in messages


def test_supported_currency_alone_is_not_flagged():
    """美元属白名单，不得误报为不支持币种。"""
    contract = _plan(_adapter(_instant_dataset), "用美元查近7天销售额")
    assert contract["status"] == "planned"
    assert "unsupported_currencies" not in contract["model_view"]
    assert contract["execution_ref"]["query_template"]["globalCurrency"] == "USD"


# ── 5. 组件筛选澄清必须带候选值与原因码 ────────────────────────────────────────


def test_component_filter_clarify_carries_candidates_and_reason_code():
    """「九部」不在授权枚举：澄清合同要下发当前账号可见的部门候选与原因码。"""
    contract = _plan(_adapter(_instant_dataset), "九部 近7天销售额")
    assert contract["status"] == "clarify_required"
    assert "component_filter_value_unmatched" in contract["model_view"]["clarification_reason_codes"]
    candidates = contract["model_view"]["component_candidates_zh"]
    assert candidates == [{"field_zh": "部门", "values_zh": ["项目二部", "项目六部"], "total": 2}]
    assert "query_template" not in contract["execution_ref"]


@pytest.mark.parametrize(
    ("department", "sales_teams"),
    [
        ("十一部", ["一部-B组", "一部-Temu组"]),
        ("十二部", ["二部-A组"]),
        ("项目十一部", ["一部-Ohwill"]),
        ("22部", ["2部-A组"]),
        ("项目二十二部", ["二部-C组"]),
    ],
)
def test_department_token_is_not_reused_as_sales_team_substring(department, sales_teams):
    """完整编号部门优先；销售小组枚举也不能拿其中短编号作主段匹配。"""
    contract = {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": "team_name",
                    "label_zh": "销售小组",
                    "component_dataset_alias": "ds_team",
                    "component_table_id": 10,
                }
            ],
            "query_template": {
                "tableId": 1,
                "dimensions": [],
                "metrics": [],
                "filters": [],
            },
        },
    }

    result = query_plan._resolve_component_filters(
        contract,
        (
            f"查询部门等于{department}在2026年8月1日至2026年8月31日的收入情况；"
            "仅按部门筛选，不筛选销售小组；收入按销售额口径。"
        ),
        lambda *_args, **_kwargs: sales_teams,
        auto_enum=True,
    )

    assert result["status"] == "planned"
    assert result["execution_ref"]["query_template"]["filters"] == []
    assert not result["execution_ref"].get("resolved_component_filters")
