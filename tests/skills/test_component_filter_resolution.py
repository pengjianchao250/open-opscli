"""组件筛选值解析的回归测试（渠道走授权枚举，ASIN 走字面格式）。

守住的核心行为：规划器绝不下发「用户要了筛选、模板里却没有该筛选」的可执行合同。
线上事故形态：查「渠道是傲彼瑞的所有ASIN」返回了傲创-美国、莱福特-美国的数据——
筛选值从未写入 query_template，而 query_flow 在 status=planned 时原样执行模板。

Skill 版与内核版同源，逐条对齐；两版内部签名不同（内核用注入的 enum_fn），
由 _resolve 适配后统一断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_ROOT = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_plan as skill_query_plan  # noqa: E402

from opscli.query.services.planner import query_plan as kernel_query_plan  # noqa: E402

# 当前账号可见的渠道授权原值：「傲彼瑞」是两个地区渠道的共同前缀，
# 用户口语里的「傲彼瑞」因此不该被任何一个单独承接
CHANNEL_VALUES = ["傲彼瑞-美国", "傲彼瑞-加拿大", "傲创-美国", "莱福特-美国"]


def _channel_contract() -> dict:
    """构造一个待解析渠道筛选的 planned 合同骨架。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": "channel_name",
                    "label_zh": "渠道",
                    "component_dataset_alias": "ds_channel",
                    "component_table_id": 7,
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


def _resolve(module, query: str, enum_values, monkeypatch) -> dict:
    """按两版各自的内部签名调用组件筛选解析，返回处理后的合同。"""
    contract = _channel_contract()
    if module is kernel_query_plan:
        def enum_fn(_table_id, _field_name, *, limit):
            if isinstance(enum_values, Exception):
                raise enum_values
            return enum_values

        return module._resolve_component_filters(
            contract, query, enum_fn, auto_enum=True
        )

    def fake_enum(*_args, **_kwargs):
        if isinstance(enum_values, Exception):
            return []
        return enum_values

    def fake_group(_table_id, field_names, **_kwargs):
        # 批量枚举同样要打桩，否则反查路径会真的发起网络请求
        if isinstance(enum_values, Exception):
            return {}
        return {name: (enum_values if name == "channel_name" else []) for name in field_names}

    monkeypatch.setattr(skill_query_plan, "_auto_enum_component_values", fake_enum)
    monkeypatch.setattr(skill_query_plan, "_auto_enum_component_field_group", fake_group)
    return module._resolve_component_filters(contract, query, auto_enum=True)


BOTH_VERSIONS = pytest.mark.parametrize(
    "module",
    [skill_query_plan, kernel_query_plan],
    ids=["skill", "kernel"],
)


def _channel_filters(contract: dict) -> list:
    template = (contract.get("execution_ref") or {}).get("query_template") or {}
    return [
        item for item in template.get("filters") or [] if item.get("field") == "channel_name"
    ]


@BOTH_VERSIONS
def test_exact_channel_value_is_written_into_template(module, monkeypatch):
    """完整等值唯一命中时把授权原值写入模板，正常放行。"""
    contract = _resolve(
        module, "查渠道是傲彼瑞-美国的所有ASIN", CHANNEL_VALUES, monkeypatch
    )
    assert contract["status"] == "planned"
    assert _channel_filters(contract) == [
        {"field": "channel_name", "operator": "=", "value": "傲彼瑞-美国"}
    ]


@BOTH_VERSIONS
def test_ambiguous_channel_value_blocks_execution(module, monkeypatch):
    """「傲彼瑞」对应两个地区渠道：必须澄清，且不得下发可执行模板。"""
    contract = _resolve(
        module, "查渠道是傲彼瑞的所有ASIN", CHANNEL_VALUES, monkeypatch
    )
    assert contract["status"] == "clarify_required"
    assert "query_template" not in contract["execution_ref"]
    message = " ".join(contract["model_view"]["clarification_messages_zh"])
    assert "傲彼瑞-美国" in message and "傲彼瑞-加拿大" in message


@BOTH_VERSIONS
def test_bare_channel_value_is_caught_by_reverse_lookup(module, monkeypatch):
    """原文不含「渠道」二字的裸值同样要被拦住。

    这是线上事故的真实形态：标签正则抽不到值，若不做枚举反查就会被当成
    「没有筛选意图」直接放行，静默返回全部渠道的数据。
    """
    contract = _resolve(module, "查傲彼瑞的所有ASIN", CHANNEL_VALUES, monkeypatch)
    assert contract["status"] == "clarify_required"
    assert "query_template" not in contract["execution_ref"]


@BOTH_VERSIONS
def test_unique_bare_channel_value_resolves(module, monkeypatch):
    """裸值唯一命中授权原值时直接锁定，不必多问一轮。"""
    contract = _resolve(module, "查莱福特-美国的所有ASIN", CHANNEL_VALUES, monkeypatch)
    assert contract["status"] == "planned"
    assert _channel_filters(contract) == [
        {"field": "channel_name", "operator": "=", "value": "莱福特-美国"}
    ]


@BOTH_VERSIONS
def test_query_without_channel_value_passes_through(module, monkeypatch):
    """原文没有任何渠道值时正常放行，不制造多余澄清。"""
    contract = _resolve(module, "查渠道和ASIN的明细", CHANNEL_VALUES, monkeypatch)
    assert contract["status"] == "planned"
    assert _channel_filters(contract) == []


@BOTH_VERSIONS
def test_enum_failure_is_fail_closed(module, monkeypatch):
    """枚举拿不到授权原值时一律阻断，绝不放行成全范围查询。"""
    contract = _resolve(module, "查渠道是傲彼瑞的所有ASIN", [], monkeypatch)
    assert contract["status"] == "blocked"
    assert "query_template" not in contract["execution_ref"]
    assert contract["model_view"]["component_filter_state"] in {
        "enum_unavailable",
        "enum_failed",
    }


@BOTH_VERSIONS
@pytest.mark.parametrize(
    "query, expected",
    [
        # 标准 Amazon ASIN：B + 9 位
        ("查 B0FWR9Y2NV 的销量", ["B0FWR9Y2NV"]),
        # TEMU 等平台的纯数字商品 ID（实测 10/11/14 位都存在于 asin 列）
        ("查 61594716002 的销量", ["61594716002"]),
        ("查 48657686364417 的销量", ["48657686364417"]),
        # 多个值一并锁定，并统一大写
        ("查 b0fwr9y2nv 和 61594716002", ["B0FWR9Y2NV", "61594716002"]),
        # 年份、数量、limit 这类普通数字不得被误吃
        ("近30天销量，2026 年，limit 1000", []),
    ],
)
def test_asin_shapes_are_recognized(module, query: str, expected: list):
    """商品 ID 形态不是固定的 B0+8 位，写死会漏值并退化成静默全量。"""
    assert module._extract_asin_values(query) == expected


@BOTH_VERSIONS
def test_channel_label_does_not_swallow_trailing_words(module, monkeypatch):
    """标签抽取必须在助词处收住，不能把「傲彼瑞的所有ASIN」整段当成筛选值。"""
    terms = ("渠道", "channel")
    assert module._extract_labeled_value("查渠道是傲彼瑞的所有ASIN", terms) == "傲彼瑞"
    assert module._extract_labeled_value("渠道为傲彼瑞-美国，近7天", terms) == "傲彼瑞-美国"
    # 维度点名不是筛选值
    assert module._extract_labeled_value("查渠道和ASIN", terms) == ""


@BOTH_VERSIONS
def test_longer_label_wins_over_prefix(module):
    """「渠道SKU」不能被「渠道」抢先匹配掉——标签必须按长度降序尝试。"""
    value = module._extract_labeled_value(
        "查渠道SKU是ON-OB-JL-007-68157的销量", ("渠道", "渠道sku")
    )
    assert value == "ON-OB-JL-007-68157"


@BOTH_VERSIONS
@pytest.mark.parametrize(
    "field_name, query, expected",
    [
        ("sell_sku", "查 ON-OB-JL-007-68157 的销量", "ON-OB-JL-007-68157"),
        ("pmc_code", "查 32.002946 的库存", "32.002946"),
        ("spu", "查 BKC-107 的销量", "BKC-107"),
        ("model", "查 COT-135-WA 的销量", "COT-135-WA"),
    ],
)
def test_code_shaped_bare_values_are_extracted(module, field_name, query, expected):
    """编码型字段的裸值靠形态抽取兜底（这些字段基数太大，不适合枚举反查）。"""
    spec = next(
        item for item in module._ENUM_COMPONENT_SPECS if item["field_name"] == field_name
    )
    assert module._extract_patterned_value(query, spec["value_pattern"]) == expected


# ---------------------------------------------------------------------------
# 二期：其余组件字段（sell_sku / 国家 / 品牌 / 销售 等）
# ---------------------------------------------------------------------------


@BOTH_VERSIONS
def test_all_value_component_fields_are_covered(module):
    """17 个值类组件字段必须全部纳入 specs——漏一个就是一条静默漏筛的路径。

    date_id 归时间口径、platform_name 归平台范围逻辑，两者不在此表内。
    """
    covered = {item["field_name"] for item in module._ENUM_COMPONENT_SPECS}
    expected = {
        "dept_name", "channel_name", "country_name", "brand_name",
        "team_username", "develop_username", "team_name", "large_team_name",
        "category", "amazon_cat", "sell_sku", "ed_sku", "model",
        "pmc_code", "spu", "product_name",
    }
    assert expected - covered == set(), f"未覆盖的组件字段：{expected - covered}"


@BOTH_VERSIONS
def test_only_low_cardinality_fields_use_reverse_lookup(module):
    """反查只给低基数字段开：高基数字段枚举不完整，反查会给出错误的「无命中」。

    实测基数：渠道 9 / 国家 2 / 品牌 3 / 销售 12 属低基数；
    公司SKU 466、产品名称 376、渠道SKU 152 属高基数，改用形态抽取。
    """
    reverse = {
        item["field_name"]
        for item in module._ENUM_COMPONENT_SPECS
        if item.get("reverse_lookup")
    }
    high_cardinality = {"sell_sku", "ed_sku", "product_name", "model", "pmc_code", "spu", "asin"}
    assert reverse & high_cardinality == set(), f"高基数字段不应开反查：{reverse & high_cardinality}"
    assert "channel_name" in reverse


@BOTH_VERSIONS
@pytest.mark.parametrize(
    "query, field_name, expected",
    [
        ("查渠道SKU是ON-OB-JL-007-68157的销量", "sell_sku", "ON-OB-JL-007-68157"),
        ("查国家为美国的销量", "country_name", "美国"),
        ("查品牌是OHWILL的销量", "brand_name", "OHWILL"),
        ("查销售是史子涵的业绩", "team_username", "史子涵"),
        ("查大组为OR-C的销量", "large_team_name", "OR-C"),
        ("查物控编码是32.002946的库存", "pmc_code", "32.002946"),
    ],
)
def test_labeled_values_across_component_fields(module, query, field_name, expected):
    """各组件字段的标签形态都要能抽出值，抽不到就等于静默漏筛。"""
    spec = next(
        item for item in module._ENUM_COMPONENT_SPECS if item["field_name"] == field_name
    )
    assert module._spec_extract(spec, query) == expected


@BOTH_VERSIONS
def test_spec_extract_prefers_label_over_pattern(module):
    """同时命中标签与形态时以标签为准，避免形态误抽走用户明确指定的值。"""
    spec = next(
        item for item in module._ENUM_COMPONENT_SPECS if item["field_name"] == "sell_sku"
    )
    assert module._spec_extract(spec, "查渠道SKU是ON-OB-JL-007-68157的销量") == "ON-OB-JL-007-68157"


@BOTH_VERSIONS
def test_consumed_value_is_not_reclaimed_by_pattern_of_another_field(module):
    """一个值只能被一个字段消费：SPU 的形态不得从渠道SKU 里抠子串再澄清一次。

    实测形态：「渠道SKU是ON-OB-JL-007-68157」被 SPU 的 `[A-Z]{2,}-[0-9]{2,}`
    抠出「JL-007」，二次澄清还会撤掉已经生成的模板。
    """
    spu = next(
        item for item in module._ENUM_COMPONENT_SPECS if item["field_name"] == "spu"
    )
    consumed = {module._normalize_component_value("ON-OB-JL-007-68157")}
    assert module._spec_extract(
        spu, "查渠道SKU是ON-OB-JL-007-68157的销量", consumed=consumed
    ) == ""
    # 未被消费时仍要能抽出
    assert module._spec_extract(spu, "查 BKC-107 的销量", consumed=set()) == "BKC-107"


@BOTH_VERSIONS
def test_reverse_lookup_prefers_exact_value_over_base_segment(module):
    """原文写了完整枚举值就锁定它，不因主段同时命中多个成员而退化成澄清。"""
    values = ["傲彼瑞-美国", "傲彼瑞-加拿大", "傲彼瑞-tiktok"]
    hits = module._reverse_lookup_component_values(
        "查傲彼瑞-加拿大的所有ASIN", values, module._normalize_component_value
    )
    assert hits == ["傲彼瑞-加拿大"]


@BOTH_VERSIONS
def test_reverse_lookup_skips_values_contained_in_consumed_ones(module):
    """渠道锁定「傲彼瑞-加拿大」后，其中的「加拿大」不该再被国家反查抓走。"""
    consumed = {module._normalize_component_value("傲彼瑞-加拿大")}
    assert module._value_already_consumed(
        module._normalize_component_value("加拿大"), consumed
    )
    assert not module._value_already_consumed(
        module._normalize_component_value("美国"), consumed
    )


@BOTH_VERSIONS
def test_empty_enum_without_requested_value_does_not_block(module, monkeypatch):
    """字段在当前账号下无授权值时跳过即可，不能把所有查询都阻断。

    「开发」在部分账号下枚举就是 0 条；早期实现把「枚举成功但为空」当成
    「枚举失败」，导致每一条查询都返回 blocked。
    """
    contract = _resolve(module, "查渠道和ASIN的明细", [], monkeypatch)
    # 渠道字段有显式值时才阻断；此处原文无任何筛选值，应正常放行
    assert contract["status"] == "planned"


# ---------------------------------------------------------------------------
# Task 10：枚举反查排除通用业务词主段（修复「亚马逊」被当成销售小组）
# ---------------------------------------------------------------------------


@BOTH_VERSIONS
def test_reverse_lookup_skips_generic_platform_base(module):
    """枚举值主段是平台名时不得靠主段命中。

    实测缺陷：销售小组授权值形如「亚马逊-运营C组」，主段是「亚马逊」，
    于是任何提到亚马逊的查询都会被当成指定了销售小组，
    真实元数据下已观察到 team_name 被注入 filters。
    """
    teams = ["亚马逊-运营C组", "亚马逊-运营A组", "沃尔玛-运营B组"]
    hits = module._reverse_lookup_component_values(
        "查亚马逊近7天的销售额", teams, module._normalize_component_value
    )
    assert hits == []


@BOTH_VERSIONS
def test_reverse_lookup_keeps_business_specific_base(module):
    """主段是业务专名时主段匹配必须保留——这是反查存在的理由。

    「傲彼瑞」不在任何槽位词表里，应继续命中三个地区渠道并转澄清。
    """
    channels = ["傲彼瑞-美国", "傲彼瑞-加拿大", "傲彼瑞-tiktok", "莱福特-美国"]
    hits = module._reverse_lookup_component_values(
        "查傲彼瑞的所有ASIN", channels, module._normalize_component_value
    )
    assert set(hits) == {"傲彼瑞-美国", "傲彼瑞-加拿大", "傲彼瑞-tiktok"}


@BOTH_VERSIONS
def test_generic_slot_terms_covers_platform_not_business_name(module):
    """排除集必须来自 intent_rules.json 现有词表，且区分通用词与业务专名。"""
    generic = module._generic_slot_terms()
    assert module._normalize_component_value("亚马逊") in generic
    assert module._normalize_component_value("傲彼瑞") not in generic


# ---------------------------------------------------------------------------
# 部门筛选的枚举驱动识别（反查兜裸值 + 宽后缀候选转澄清，E2E T5-3 回归）
# ---------------------------------------------------------------------------

# 当前账号授权的部门枚举：混合编号部门、无后缀地名部门、品牌型名与带后缀特殊名
DEPT_ENUM_VALUES = ["项目二部", "项目九部", "宁波", "泛泰克", "孵化部"]


def _dept_contract() -> dict:
    """构造一个待解析部门筛选的 planned 合同骨架。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": "dept_name",
                    "label_zh": "部门",
                    "component_dataset_alias": "ds_dept",
                    "component_table_id": 48,
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


def _resolve_dept(module, query: str, monkeypatch) -> dict:
    """按两版各自的内部签名解析部门筛选，枚举固定返回 DEPT_ENUM_VALUES。"""
    contract = _dept_contract()
    if module is kernel_query_plan:
        return module._resolve_component_filters(
            contract, query, lambda *_a, **_k: DEPT_ENUM_VALUES, auto_enum=True
        )

    def fake_enum(*_args, **_kwargs):
        return DEPT_ENUM_VALUES

    def fake_group(_table_id, field_names, **_kwargs):
        return {
            name: (DEPT_ENUM_VALUES if name == "dept_name" else [])
            for name in field_names
        }

    monkeypatch.setattr(skill_query_plan, "_auto_enum_component_values", fake_enum)
    monkeypatch.setattr(skill_query_plan, "_auto_enum_component_field_group", fake_group)
    return module._resolve_component_filters(contract, query, auto_enum=True)


def _dept_filters(contract: dict) -> list:
    template = (contract.get("execution_ref") or {}).get("query_template") or {}
    return [
        item for item in template.get("filters") or [] if item.get("field") == "dept_name"
    ]


@BOTH_VERSIONS
def test_bare_department_value_resolved_by_reverse_lookup(module, monkeypatch):
    """无后缀部门裸值（「宁波」）必须由授权枚举反查兜住，不得静默全量。"""
    contract = _resolve_dept(module, "近7天宁波的订单量", monkeypatch)
    assert contract["status"] == "planned"
    assert _dept_filters(contract) == [
        {"field": "dept_name", "operator": "=", "value": "宁波"}
    ]


@BOTH_VERSIONS
def test_brandlike_department_value_resolved_by_reverse_lookup(module, monkeypatch):
    """品牌型无后缀部门名（「泛泰克」）同样由反查唯一锁定。"""
    contract = _resolve_dept(module, "近7天泛泰克的订单量", monkeypatch)
    assert contract["status"] == "planned"
    assert _dept_filters(contract) == [
        {"field": "dept_name", "operator": "=", "value": "泛泰克"}
    ]


@BOTH_VERSIONS
def test_unknown_suffixed_department_requires_clarification(module, monkeypatch):
    """虚构部门「魔法部」不在授权枚举中：必须转澄清，不得静默放大为全量。

    E2E T5-3 回归锚点：原先宽后缀形态抽不到候选，「魔法部」被当成没有
    筛选意图直接放行，查询悄悄变成全部门口径。
    """
    contract = _resolve_dept(module, "近7天魔法部的订单量", monkeypatch)
    assert contract["status"] == "clarify_required"
    assert "query_template" not in contract["execution_ref"]
    message = " ".join(contract["model_view"]["clarification_messages_zh"])
    assert "魔法部" in message


@BOTH_VERSIONS
def test_generic_suffix_words_do_not_trigger_department_clarify(module, monkeypatch):
    """「全部」这类以「部」结尾的通用词在停用词表内，不得误判成部门候选。"""
    contract = _resolve_dept(module, "近7天全部渠道的订单量", monkeypatch)
    assert contract["status"] == "planned"
    assert _dept_filters(contract) == []
