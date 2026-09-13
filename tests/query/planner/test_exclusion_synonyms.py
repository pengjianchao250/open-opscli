"""排除同义词与多场景筛选的回归测试（2026-09-10 同义词复测）。

事故形态：
1. 「扣除/刨除/排掉/拿掉/不算/除去/抛开」「除了X」「除X外」「X以外」不在排除词表里，
   已锁定的组件值和平台值被当成包含条件——「各部门销售额，扣除九部」下发成
   dept_name=九部，返回的恰好是用户要去掉的那部分。
2. 品类、平台类目不开原文反查，「剔除家居」的排除条件被静默丢弃；「品类排除家居」
   这类字段后接排除词的写法也抽不到值。
3. 「排除美国只看加拿大」不带标点时，排除区间吞掉了随后的正向限定。
4. 「排除九部，只看十部」只锁定第一个部门，第二个部门被静默丢弃。
5. 「不包括九部在内」被指标列举门禁误判为缺指标；「包括九部在内」被收窄成只看九部。
"""

from __future__ import annotations

import pytest

from opscli.query.services.planner import query_plan
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


ENUMS = {
    "dept_name": ["一部", "九部", "十一部", "项目二部", "项目六部"],
    "country_name": ["美国", "加拿大", "英国"],
    "brand_name": ["ALLEWIE", "OHWILL"],
    "team_name": ["一部-B组", "九部-A组"],
    "category": ["家居", "家居类", "户外", "家居-窗户锁", "家居-休闲椅", "办公-休闲椅"],
}

COMPONENTS = (
    ("dept_name", "部门"),
    ("country_name", "国家"),
    ("brand_name", "品牌"),
    ("team_name", "销售小组"),
    ("category", "品类"),
)


def _contract() -> dict:
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_reason_codes": [], "clarification_messages_zh": []},
        "answer_contract": {"required_disclosures_zh": []},
        "execution_ref": {
            "query_template": {"filters": []},
            "filter_components": [
                {"field_name": field_name, "label_zh": label, "component_table_id": index}
                for index, (field_name, label) in enumerate(COMPONENTS, start=1)
            ],
        },
    }


# 数据集字段元数据：真实流程靠这些标签识别「剔除退款」这类指标口径说法
ADAPTER = MetadataAdapter(
    {
        "datasets": [],
        "fields": [
            {"table_id": 1, "dataset_alias": "ds_test", "field_name": "price",
             "verbose_name": "销售额", "field_type": "metric"},
            {"table_id": 1, "dataset_alias": "ds_test", "field_name": "refund_amount",
             "verbose_name": "退款金额", "field_type": "metric"},
        ],
    }
)


def _resolve(query: str, calls: list | None = None) -> dict:
    def enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001
        if calls is not None:
            calls.append(field_name)
        return list(ENUMS.get(field_name, []))

    contract = _contract()
    contract["execution_ref"]["dataset_alias"] = "ds_test"
    return query_plan._resolve_component_filters(
        contract, query, enum_fn, auto_enum=True, adapter=ADAPTER
    )


def _filters(result: dict) -> list[dict]:
    template = (result.get("execution_ref") or {}).get("query_template") or {}
    return list(template.get("filters") or [])


@pytest.mark.parametrize(
    "query",
    [
        "近7天各部门销售额，扣除九部",
        "近7天各部门销售额，刨除九部",
        "近7天各部门销售额，排掉九部",
        "近7天各部门销售额，拿掉九部",
        "近7天各部门销售额，不算九部",
        "近7天各部门销售额，除去九部",
        "近7天各部门销售额，抛开九部",
        "近7天各部门销售额，除了九部",
        "近7天除九部外各部门销售额",
        "近7天九部以外的各部门销售额",
        "近7天各部门销售额，不包括九部在内",
    ],
)
def test_exclusion_synonyms_keep_exclude_polarity(query):
    """口语排除说法一律按排除处理，不得反转成包含。"""
    result = _resolve(query)

    assert result["status"] == "planned"
    assert _filters(result) == [{"field": "dept_name", "operator": "!=", "value": "九部"}]


def test_additive_chu_le_does_not_become_exclusion():
    """「除了九部还要看十一部」是加合句式，九部不能被排除。"""
    result = _resolve("近7天除了九部还要看十一部的销售额")

    operators = {(item["field"], item["operator"]) for item in _filters(result)}
    assert ("dept_name", "!=") not in operators
    assert ("dept_name", "not_in") not in operators


def test_positive_restriction_ends_exclusion_span():
    """「排除美国只看加拿大」不带标点时，加拿大仍按包含处理。"""
    result = _resolve("近7天排除美国只看加拿大的销售额")

    assert result["status"] == "planned"
    assert {"field": "country_name", "operator": "=", "value": "加拿大"} in _filters(result)
    assert {"field": "country_name", "operator": "!=", "value": "美国"} in _filters(result)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("近7天各品类销售额，品类排除家居", {"field": "category", "operator": "!=", "value": "家居"}),
        ("近7天各品类销售额，品类里剔除家居", {"field": "category", "operator": "!=", "value": "家居"}),
        (
            "近7天各销售小组销售额，销售小组排除一部-B组",
            {"field": "team_name", "operator": "!=", "value": "一部-B组"},
        ),
        ("近7天各品牌销售额，品牌不看ALLEWIE", {"field": "brand_name", "operator": "!=", "value": "ALLEWIE"}),
    ],
)
def test_label_followed_by_exclusion_verb_extracts_value(query, expected):
    """字段标签后接排除词时，值要单独抽出来，不能连排除词一起吞进值里。"""
    result = _resolve(query)

    assert result["status"] == "planned"
    assert expected in _filters(result)


@pytest.mark.parametrize(
    "query",
    [
        "近7天各品类销售额，剔除家居",
        "近7天各品类销售额，除了家居",
        "近7天各品类销售额，家居除外",
        "近7天各品类销售额，扣除家居",
    ],
)
def test_bare_category_exclusion_is_applied(query):
    """品类裸值被明确排除时要落成排除条件，不能静默丢弃。"""
    result = _resolve(query)

    assert result["status"] == "planned"
    assert _filters(result) == [{"field": "category", "operator": "!=", "value": "家居"}]


def test_bare_category_exclusion_list_uses_not_in():
    result = _resolve("近7天各品类销售额，剔除家居和户外")

    assert result["status"] == "planned"
    assert _filters(result) == [
        {"field": "category", "operator": "not_in", "value": ["家居", "户外"]}
    ]


def test_bare_category_exclusion_with_only_partial_match_clarifies():
    """「窗户锁」只是某个品类值的片段：转澄清并把近似成员放在候选最前面。"""
    result = _resolve("近7天各品类销售额，剔除窗户锁")

    assert result["status"] == "clarify_required"
    assert "component_filter_value_unmatched" in result["model_view"]["clarification_reason_codes"]
    candidates = result["model_view"]["component_candidates_zh"][0]["values_zh"]
    assert candidates[0] == "家居-窗户锁"
    assert result["execution_ref"].get("query_template") is None


def test_category_suffix_variant_lists_base_value_as_candidate():
    """授权值里没有「家具类」时，「家具」这类被包含的授权值也作为近似成员提示。"""
    enums = dict(ENUMS, category=["家具", "家具-柜子"])

    def enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001
        return list(enums.get(field_name, []))

    result = query_plan._resolve_component_filters(
        _contract(), "近7天各品类销售额，剔除家具类", enum_fn, auto_enum=True
    )

    assert result["status"] == "clarify_required"
    message = "".join(result["model_view"]["clarification_messages_zh"])
    assert "“家具”" in message


@pytest.mark.parametrize(
    "query",
    ["近7天各平台销售额，不要小计", "近7天剔除退款后的销售额", "近7天各平台销售额，剔除异常订单"],
)
def test_non_value_exclusion_objects_skip_category_enumeration(query):
    """报表形态词、指标口径词不是取值，不应为此枚举高基数品类。"""
    calls: list = []
    result = _resolve(query, calls)

    assert result["status"] == "planned"
    assert "category" not in calls
    assert not [item for item in _filters(result) if item["field"] == "category"]


def test_inclusive_mention_does_not_narrow_scope():
    """「包括九部在内的各部门」范围不变，不能收窄成只看九部。"""
    result = _resolve("近7天包括九部在内的各部门销售额")

    assert result["status"] == "planned"
    assert not [item for item in _filters(result) if item["field"] == "dept_name"]


def test_separately_mentioned_departments_keep_own_polarity():
    """分句点名的两个部门都要保留，并各自按所在语段判定极性。"""
    result = _resolve("近7天排除九部，只看十一部的销售额")

    assert result["status"] == "planned"
    assert {"field": "dept_name", "operator": "=", "value": "十一部"} in _filters(result)
    assert {"field": "dept_name", "operator": "!=", "value": "九部"} in _filters(result)


def test_unauthorized_included_department_blocks_widened_scope():
    """正向点名的部门未授权时转澄清，不能只剩「排除九部」把范围放大。"""
    result = _resolve("近7天排除九部，只看十部的销售额")

    assert result["status"] == "clarify_required"
    assert "component_filter_unauthorized" in result["model_view"]["clarification_reason_codes"]
    assert "十部" in "".join(result["model_view"]["clarification_messages_zh"])


def test_unauthorized_department_in_list_is_disclosed():
    """「九部和十部」里十部未授权：按授权交集查询，并披露十部未纳入。"""
    result = _resolve("近7天九部和十部的销售额")

    assert result["status"] == "planned"
    assert _filters(result) == [{"field": "dept_name", "operator": "=", "value": "九部"}]
    disclosures = "".join(result["model_view"].get("component_filter_disclosures_zh") or [])
    assert "十部" in disclosures and "未纳入" in disclosures


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("近7天各部门销售额，一部分数据看九部", "九部"),
        ("近7天九部分析一下各国家销售额", "九部"),
    ],
)
def test_quantifier_yi_bu_fen_is_not_a_department(query, expected):
    """「一部分」是量词短语，「九部分析」里的「分」属于动词，两者都不能误判。"""
    result = _resolve(query)

    assert result["status"] == "planned"
    assert _filters(result) == [{"field": "dept_name", "operator": "=", "value": expected}]


def test_coordinated_project_departments_still_resolve_together():
    """「项目二部和项目六部分别」里的「六部分别」不能被当成量词短语。"""
    result = _resolve("近7天项目二部和项目六部分别的销售额")

    assert result["status"] == "planned"
    assert {
        "field": "dept_name",
        "operator": "in",
        "value": ["项目二部", "项目六部"],
    } in _filters(result)


@pytest.mark.parametrize(
    ("query", "excluded_slots"),
    [
        ("近7天各平台销售额，扣除亚马逊VC", ["amazon_vc"]),
        ("近7天各平台销售额，除了亚马逊VC", ["amazon_vc"]),
        ("近7天除亚马逊VC外各平台销售额", ["amazon_vc"]),
        ("近7天各平台销售额，不算Temu", ["temu"]),
    ],
)
def test_platform_scope_honours_exclusion_synonyms(query, excluded_slots):
    """平台范围同样识别口语排除说法，不能把被排除的平台读成"只看它"。"""
    rules = query_plan._load_rules_resource()
    selection = query_plan.schema.extract_query_semantics(query, rules)

    scope = query_plan._platform_scope(selection, rules, None, query=query)

    assert scope["excluded_slots"] == excluded_slots
    assert scope["requested_slots"] == []
    assert scope["polarity_conflict_slots"] == []


def test_platform_inclusive_mention_is_not_a_platform_scope():
    """「包括亚马逊在内的各平台」不构成平台范围。"""
    rules = query_plan._load_rules_resource()
    query = "近7天包括亚马逊在内的各平台销售额"
    selection = query_plan.schema.extract_query_semantics(query, rules)

    scope = query_plan._platform_scope(selection, rules, None, query=query)

    assert scope["requested_slots"] == []
    assert scope["excluded_slots"] == []


def test_negated_inclusion_intro_is_not_a_metric_enumeration():
    """「不包括九部在内」不能触发指标列举门禁。"""
    assert query_plan._unmatched_enumerated_metric_terms("近7天各部门销售额，不包括九部在内", ["销售额"]) == []
    assert query_plan._unmatched_enumerated_metric_terms("近7天各部门销售额，包括九部在内", ["销售额"]) == []


@pytest.mark.parametrize(
    ("query", "label"),
    [
        ("近7天各平台的销售额，品类排除家居类", "品类"),
        ("近7天各平台的销售额，销售小组不看一部-B组", "销售小组"),
        ("近7天各平台的销售额，品类里剔除家居", "品类"),
    ],
)
def test_filter_label_before_exclusion_verb_is_not_a_dimension(query, label):
    """「品类排除家居类」里的品类只表示筛选，不能再被选成分组维度。"""
    masked = query_plan._query_without_component_filter_labels(
        query, {"dimensions": [{"verbose_name": label}, {"verbose_name": "平台"}]}
    )

    assert label not in masked
    assert "平台" in masked


def test_grouping_label_before_exclusion_verb_stays_a_dimension():
    """「各部门排除九部的销售额」里的「各部门」是分组诉求，不能被当成筛选左值遮蔽。"""
    masked = query_plan._query_without_component_filter_labels(
        "近7天各部门排除九部的销售额", {"dimensions": [{"verbose_name": "部门"}]}
    )

    assert "部门" in masked


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("近7天家居品类的销售额", [{"field": "category", "operator": "=", "value": "家居"}]),
        ("近7天看一下家居品类的销量", [{"field": "category", "operator": "=", "value": "家居"}]),
        (
            "近7天户外品类和家居品类的销售额",
            [{"field": "category", "operator": "in", "value": ["户外", "家居"]}],
        ),
        ("近7天所有品类的销售额", []),
        ("近7天各品类的销售额", []),
    ],
)
def test_postfix_category_label_value(query, expected):
    """「家居品类」这类值在前、标签在后的单值写法只在整值命中时落筛选，修饰语不触发。"""
    result = _resolve(query)

    assert result["status"] == "planned"
    assert [item for item in _filters(result) if item["field"] == "category"] == expected


def test_clause_comma_is_not_a_postfix_list():
    """「除了家居，其他品类」里的逗号分隔的是子句：按排除家居处理，不能误判成品类列表。"""
    result = _resolve("除了家居，近7天其他品类的销售额")

    assert result["status"] == "planned"
    assert _filters(result) == [{"field": "category", "operator": "!=", "value": "家居"}]


def test_time_clause_before_postfix_label_is_not_disclosed_as_value():
    """「上个月，傲彼瑞-美国渠道」里的「上个月」不是渠道值，不得出现「未纳入」披露。"""
    contract = _contract()
    contract["execution_ref"]["filter_components"].append(
        {"field_name": "channel_name", "label_zh": "渠道", "component_table_id": 9}
    )

    def enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001
        return {"channel_name": ["傲彼瑞-美国", "傲彼瑞-加拿大"]}.get(field_name, [])

    result = query_plan._resolve_component_filters(
        contract, "上个月，傲彼瑞-美国渠道的销售额", enum_fn, auto_enum=True
    )

    assert result["status"] == "planned"
    assert _filters(result) == [{"field": "channel_name", "operator": "=", "value": "傲彼瑞-美国"}]
    disclosures = "".join(result["model_view"].get("component_filter_disclosures_zh") or [])
    assert "上个月" not in disclosures


@pytest.mark.parametrize(
    "query",
    [
        "近7天各国家销售额，国家不用细分",
        "近7天销售额，部门不需要展开",
        "近7天各品牌销售额，品牌不看明细",
        "近7天各品类销售额，品类不要拆开看",
    ],
)
def test_presentation_words_after_label_are_not_values(query):
    """「国家不用细分」「部门不需要展开」说的是呈现方式，不能被读成筛选值而误报澄清。"""
    result = _resolve(query)

    assert result["status"] == "planned"
    assert _filters(result) == []


def test_value_sharing_action_prefix_is_still_a_value():
    """「显示器」这类以同样字开头的真实取值不受动作词判定影响。"""
    assert query_plan._is_non_value_candidate("显示器") is False
    assert query_plan._is_non_value_candidate("拆开看") is True


def test_postfix_include_and_bare_exclusion_on_same_field_both_apply():
    """「家居品类的销售额，剔除户外」：家居按包含、户外按排除，两个条件都要落下。"""
    result = _resolve("近7天家居品类的销售额，剔除户外")

    assert result["status"] == "planned"
    assert {"field": "category", "operator": "=", "value": "家居"} in _filters(result)
    assert {"field": "category", "operator": "!=", "value": "户外"} in _filters(result)


def test_bare_exclusion_list_split_by_ascii_comma_stays_excluded():
    """半角逗号截断了排除区间时，排除宾语仍按排除处理。"""
    result = _resolve("近7天各品类销售额，剔除家居,户外")

    assert result["status"] == "planned"
    assert _filters(result) == [
        {"field": "category", "operator": "not_in", "value": ["家居", "户外"]}
    ]


def test_label_inside_longer_field_label_is_not_masked_as_filter():
    """指标「平台移除数量」里的「平台」+「移除」不是筛选左值，不能被遮蔽切开。"""
    masked = query_plan._query_without_component_filter_labels(
        "即时综合数据集近30天的平台移除数量",
        {
            "dimensions": [{"verbose_name": "平台"}],
            "metrics": [{"verbose_name": "平台移除数量"}],
        },
    )

    assert "平台移除数量" in masked
