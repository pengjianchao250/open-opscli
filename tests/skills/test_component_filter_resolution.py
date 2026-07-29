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

    monkeypatch.setattr(skill_query_plan, "_auto_enum_component_values", fake_enum)
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
def test_channel_label_does_not_swallow_trailing_words(module, monkeypatch):
    """标签抽取必须在助词处收住，不能把「傲彼瑞的所有ASIN」整段当成筛选值。"""
    assert module._extract_requested_channel_value("查渠道是傲彼瑞的所有ASIN") == "傲彼瑞"
    assert module._extract_requested_channel_value("渠道为傲彼瑞-美国，近7天") == "傲彼瑞-美国"
    # 维度点名不是筛选值
    assert module._extract_requested_channel_value("查渠道和ASIN") == ""
