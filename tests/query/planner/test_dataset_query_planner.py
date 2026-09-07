"""规划器组合入口（query_plan.build_model_query_plan）的业务语义回归测试。

历史说明：本文件原属 tests/skills，验证 Skill 版本地规划器（CSV 数据目录 +
run_query 执行器 + CLI main()）。Skill 本地规划器移除后只保留内核仍实现、且
tests/query/planner 其他文件尚未覆盖的业务语义用例：图表 UUID 路由、组件筛选
匹配策略合同、默认条件投影、授权字段作用域、显式字段去重、粒度披露的两条
边界路径与币种识别。数据源统一改为 MetadataAdapter。

已删除的部分（内核无对应物或已被其他文件覆盖）：
- run_query 执行器绑定校验、plan-file、exit code、CLI main() 错误包装；
- data_dir 本地目录/只读挂载回退、VERSION.json 占位判定、skills upgrade 自动升级；
- 与 test_query_plan.py / test_selection.py / test_guidance.py 重复的选表、
  平台语义、部门枚举、时间口径、多币种模板用例。
"""

from __future__ import annotations

import json
from importlib.resources import files

import jsonschema
import pytest

from opscli.query.services.planner import query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter

CHART_UUID = "e49a7298-67d7-4abb-a11f-284673297661"

# 严格模型合同 Schema：内核化后随包分发，不再从 Skill data 目录读取
SCHEMA = json.loads(
    (files("opscli.query.services.planner.resources") / "query_plan.schema.json").read_text(
        encoding="utf-8"
    )
)

# 字段级默认条件（后端下发形态）：ds_ads.date_type 配 required QUARTER
_ENABLED_FILTER_CONFIG = {
    "type": "required",
    "enabled": True,
    "operator": "equals",
    "filter_type": "enum",
    "enum_value": ["QUARTER"],
    "value": None,
    "filter_agg": "none",
}


def _field(
    table_id: int,
    alias: str,
    dataset_name: str,
    field_name: str,
    label: str,
    field_type: str,
    **extra,
) -> dict:
    """构造一行字段元数据（同形于 MetadataAdapter 消费的 fields 项）。"""
    row = {
        "table_id": table_id,
        "dataset_alias": alias,
        "dataset_name": dataset_name,
        "field_name": field_name,
        "verbose_name": label,
        "global_alias": f"f_{field_name}",
        "field_type": field_type,
        "has_formula_config": 0,
        "snapshot_metric": 0,
    }
    row.update(extra)
    return row


def _ready_payload(*, with_filter_config: bool = False) -> dict:
    """最小就绪元数据：SP广告数据集（公式指标 ACOS）+ 库存数据集（快照指标）。"""
    fields = [
        _field(1, "ds_ads", "广告数据集", "date_id", "日期", "dimension"),
        _field(
            1,
            "ds_ads",
            "广告数据集",
            "acos",
            "ACOS",
            "metric",
            summary_expression="ads_cost / sales",
            description="广告成本销售比",
            has_formula_config=1,
        ),
        _field(2, "ds_inv", "库存数据集", "sku", "SKU", "dimension"),
        _field(
            2, "ds_inv", "库存数据集", "stock_qty", "库存量", "metric", snapshot_metric=1
        ),
    ]
    if with_filter_config:
        fields.insert(
            0,
            _field(
                1,
                "ds_ads",
                "广告数据集",
                "date_type",
                "日期类型",
                "dimension",
                filter_config=dict(_ENABLED_FILTER_CONFIG),
            ),
        )
    return {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_ads",
                "dataset_name": "广告数据集",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "SP广告数据集",
                "remarks": "",
                "select_columns": [
                    {
                        "column_name": "platform_name",
                        "verbose_name": "平台",
                        "component_dataset_alias": "ds_ads",
                    }
                ],
            },
            {
                "table_id": 2,
                "dataset_alias": "ds_inv",
                "dataset_name": "库存数据集",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "库存快照数据集",
                "remarks": "",
                "select_columns": [],
            },
        ],
        "fields": fields,
    }


def _plan(payload: dict, query: str, **kwargs) -> dict:
    """按内核签名走一次规划：枚举默认打桩为空，避免测试触网（铁律8）。"""
    kwargs.setdefault("enum_fn", lambda *_a, **_k: [])
    return query_plan.build_model_query_plan(MetadataAdapter(payload), query, **kwargs)


# ---------------------------------------------------------------------------
# 图表 UUID 路由：在读取数据集元数据前确定性分流
# ---------------------------------------------------------------------------


def test_chart_uuid_data_request_bypasses_dataset_metadata():
    """图表数据请求应在读取元数据前分流，并生成可执行 Chart 命令。"""
    # 空 adapter：该路由必须完全不依赖数据集元数据
    result = _plan({}, f"查询图表ID：{CHART_UUID} 的数据")

    assert result["query_mode"] == "chart_uuid"
    assert result["data_state"] == "not_required"
    assert result["status"] == "planned"
    assert result["execution_ref"] == {
        "user_visible": False,
        "chart_uuid": CHART_UUID,
        "chart_action": "run",
        "query_command": f"opscli query chart --uuid {CHART_UUID} --run --pretty",
        "run": True,
        "dry_run": False,
    }


def test_chart_uuid_plans_structure_dry_run_and_document():
    """图表入口应按用户原文区分结构、SQL 和文档三种非数据执行动作。"""
    cases = [
        ("只获取图表 UUID {uuid} 的查询结构，不执行", "structure", "query chart", "--run"),
        ("图表 UUID {uuid} 只生成SQL", "dry_run", "--dry-run", "--run"),
        ("为图表 UUID {uuid} 生成API文档", "document", "query chart-doc", "--run"),
    ]
    for prompt, action, command_marker, absent_marker in cases:
        result = _plan({}, prompt.format(uuid=CHART_UUID))
        command = result["execution_ref"]["query_command"]
        assert result["execution_ref"]["chart_action"] == action
        assert command_marker in command
        assert absent_marker not in command


def test_chart_uuid_multiple_candidates_require_clarification():
    """同一请求含多个图表 UUID 时不得静默选择。"""
    second_uuid = "11111111-2222-4333-8444-555555555555"
    result = _plan({}, f"对比图表 {CHART_UUID} 和图表 {second_uuid} 的数据")

    assert result["query_mode"] == "chart_uuid"
    assert result["status"] == "clarify_required"
    assert result["execution_ref"]["chart_uuid_candidates"] == [CHART_UUID, second_uuid]
    assert "query_command" not in result["execution_ref"]


def test_chart_uuid_contract_matches_strict_schema():
    """图表规划结果必须通过与普通规划共用的严格模型合同 Schema。"""
    result = _plan({}, f"执行图表 chart_uuid: {CHART_UUID} 的数据")
    jsonschema.Draft202012Validator(SCHEMA).validate(result)


# ---------------------------------------------------------------------------
# 组件筛选值匹配策略：精确成员匹配，禁止名称包含式扩展
# ---------------------------------------------------------------------------


def test_filter_component_contract_requires_exact_enum_member_match():
    """普通筛选组件必须禁止把精确成员扩展到仅名称包含的其他成员。"""
    result = _plan(_ready_payload(), "SP 广告数据集近7天按平台分析ACOS", auto_enum=False)

    assert result["execution_ref"]["filter_components"]
    policy = result["execution_ref"]["filter_value_match_policy"]
    assert policy["strategy"] == "exact_normalized_then_clarify"
    assert policy["exact_match_is_exclusive"] is True
    assert policy["exact_match_confirmation_required"] is False
    assert policy["substring_match_allowed"] is False
    assert policy["no_exact_match_action"] == "clarify_required"
    assert "department_arabic_chinese_numeral_equivalence" in policy["normalizations"]
    assert "9部”只匹配“九部" in policy["rule_zh"]
    assert "范泰克”不匹配“范泰克体系外" in policy["rule_zh"]
    assert any(
        "仅因名称包含" in message
        for message in result["answer_contract"]["forbidden_outputs_zh"]
    )


# ---------------------------------------------------------------------------
# 默认条件投影（R5）：只披露、不预填模板
# ---------------------------------------------------------------------------


def test_query_plan_projects_default_filters():
    """配置了 filter_config 的数据集：规划结果必须携带默认条件与中文披露。"""
    result = _plan(_ready_payload(with_filter_config=True), "SP 广告数据集 近7天 ACOS")

    assert result["status"] == "planned"
    defaults = result["execution_ref"]["default_filters"]
    assert defaults[0]["field_name"] == "date_type"
    assert defaults[0]["operator"] == "equals"
    assert defaults[0]["values"] == ["QUARTER"]
    assert defaults[0]["type"] == "required"
    # 用户可见层中文披露
    assert any("QUARTER" in text for text in result["model_view"]["default_filters_zh"])
    # 回答合同强制披露
    assert any("默认条件" in text for text in result["answer_contract"]["required_disclosures_zh"])
    # query_template 不预填默认条件：服务端是唯一权威注入方，模型不得手动加入
    # 注：date_type 可能作为时间维度合法出现在日期范围过滤（>=/<= scope），
    # 但不应出现 equals/in + QUARTER 这类枚举型默认条件
    template_filters = result["execution_ref"]["query_template"].get("filters", [])
    assert not any(
        f.get("field") == "date_type" and f.get("value") == "QUARTER"
        for f in template_filters
    ), "query_template.filters 不应含 date_type=QUARTER 默认条件（由服务端自动应用）"


def test_query_plan_no_default_filters_key_when_unconfigured():
    """未配置默认条件：execution_ref 不带 default_filters 键，行为与现状一致。"""
    result = _plan(_ready_payload(), "SP 广告数据集 ACOS")

    assert "default_filters" not in result["execution_ref"]
    assert "default_filters_zh" not in result["model_view"]
    # 未配置时回答合同不得注入默认条件披露
    assert not any(
        "默认条件" in text
        for text in result["answer_contract"]["required_disclosures_zh"]
    )


def test_model_contract_schema_accepts_projected_default_filters():
    """严格 Schema 必须覆盖规划器已投影的默认条件两处字段。"""
    result = _plan(
        _ready_payload(with_filter_config=True), "SP 广告数据集 ACOS", auto_enum=False
    )
    jsonschema.Draft202012Validator(SCHEMA).validate(result)


# ---------------------------------------------------------------------------
# 授权字段作用域与显式字段去重
# ---------------------------------------------------------------------------


def test_authorized_query_labels_are_scoped_to_selected_dataset():
    """外部数据集字段标签不得污染当前表，更不能产生无 field_name 的假执行字段。"""
    payload = _ready_payload()
    payload["fields"].append(
        _field(2, "ds_inv", "库存数据集", "days_sold", "已售天数", "metric")
    )
    result = _plan(payload, "SP 广告数据集 已售天数", auto_enum=False)

    assert "已售天数" not in result["model_view"]["metrics"]
    assert all(
        item.get("field_name") != "days_sold"
        for item in result["execution_ref"].get("metrics", [])
    )


def test_explicit_fields_survive_label_dedup_and_containment():
    """显式物理字段不因同标签或长短标签包含关系从 execution_ref 消失。"""
    fields = [
        {"field_name": "sales", "verbose_name": "销售额", "selection_source": "explicit"},
        {
            "field_name": "ad_sales",
            "verbose_name": "广告销售额",
            "selection_source": "explicit",
        },
        {
            "field_name": "sales_copy",
            "verbose_name": "销售额",
            "selection_source": "explicit",
        },
    ]
    selected = query_plan._longest_unique_labels(fields)
    assert [item["field_name"] for item in selected] == [
        "sales",
        "ad_sales",
        "sales_copy",
    ]


# ---------------------------------------------------------------------------
# 粒度披露的两条边界路径（正例见 test_query_plan.py 的 grain 一节）
# ---------------------------------------------------------------------------


def test_grain_disclosure_survives_when_masking_eats_the_grain_word():
    """身份遮蔽把用户说出口的粒度词一起抹掉时，披露仍然必须存在。

    真实元数据形态（审查者实测的原案）：数据集中文说明是「亚马逊搜索词绩效」，
    字段里也有「搜索词」，于是 `_semantic_query_without_candidate_identity` 的全局
    replace 把 '亚马逊搜索词绩效 近7天搜索词的点击份额' 里第二个（用户真正说出口的）
    「搜索词」也一起抹掉 → 遮蔽后槽位为空 → 无请求可比 → 披露又消失。
    披露侧必须同时看未遮蔽的读法。
    """
    payload = {
        "datasets": [
            {
                "table_id": 50,
                "dataset_alias": "ds_sqp",
                "dataset_name": "custom_search_query_set",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                # description 即用户会报出的中文名，且自身含「搜索词」；
                # remarks 提供 keyword 覆盖，构造出「数据集比请求多覆盖一个粒度」
                "description": "亚马逊搜索词绩效",
                "remarks": "含关键词与搜索词双维度明细",
                "select_columns": [],
            }
        ],
        "fields": [
            _field(50, "ds_sqp", "custom_search_query_set", "date_id", "日期", "dimension"),
            # 字段里也有「搜索词」标签，遮蔽会连用户原话里的粒度词一起抹掉
            _field(
                50, "ds_sqp", "custom_search_query_set", "search_term", "搜索词", "dimension"
            ),
            _field(
                50, "ds_sqp", "custom_search_query_set", "click_share", "点击份额", "metric"
            ),
        ],
    }
    result = _plan(payload, "亚马逊搜索词绩效 近7天搜索词的点击份额", auto_enum=False)

    assert result["execution_ref"]["dataset_alias"] == "ds_sqp"
    disclosures = result["model_view"].get("grain_disclosure_zh") or []
    assert any("关键词" in item for item in disclosures), "身份遮蔽吃掉粒度词后披露丢失"
    assert all(
        item in result["answer_contract"]["required_disclosures_zh"] for item in disclosures
    )


def test_grain_exact_match_produces_no_disclosure_noise():
    """粒度正好相等（无多余覆盖）时，不产生披露，也不污染强制披露列表（反例）。"""
    payload = {
        "datasets": [
            {
                "table_id": 11,
                "dataset_alias": "ds_st_only",
                "dataset_name": "搜索词专表",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                # 说明文案只命中「搜索词」一个 grain 取值，与用户请求完全一致
                "description": "用于分析亚马逊消费者搜索词维度下的转化情况，支持选品优化。",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [
            _field(11, "ds_st_only", "搜索词专表", "date_id", "日期", "dimension"),
            _field(11, "ds_st_only", "搜索词专表", "conv_rate", "转化率", "metric"),
        ],
    }
    result = _plan(payload, "查询近7天搜索词的转化率", auto_enum=False)

    assert result["status"] == "planned"
    assert result["execution_ref"]["dataset_alias"] == "ds_st_only"
    assert "grain_disclosure_zh" not in result["model_view"]
    assert not any(
        "粒度比请求更细" in text
        for text in result["answer_contract"]["required_disclosures_zh"]
    )


# ---------------------------------------------------------------------------
# 币种识别
# ---------------------------------------------------------------------------


def test_currency_detection_preserves_order_and_avoids_keyword_overlap():
    """多币种按原文顺序去重，Canadian dollar 不得被通用 dollar 扩成 USD。"""
    assert query_plan._detect_global_currencies("分别使用加拿大元和人民币查询") == [
        "CAD",
        "CNY",
    ]
    assert query_plan._detect_global_currencies("人民币、CAD、人民币双币种") == [
        "CNY",
        "CAD",
    ]
    assert query_plan._detect_global_currencies("show in Canadian dollar") == ["CAD"]
