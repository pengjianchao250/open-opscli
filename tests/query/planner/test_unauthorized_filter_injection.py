"""未授权组件筛选值的注入防护回归测试（组件语义值注入 filters 前须与权限枚举求交集）。

QA 实测事故形态：用户查询含国家/品牌词（如"德国站""某品牌"）时，规划器把语义命中的
组件值当作用户点名的筛选集合处理，若该组件值不在当前账号的权限枚举内，执行入口
仍会原样执行不含用户筛选意图的模板，等同于把"只查德国"悄悄放行成"查全部国家"；
线上曾观测到执行器 precheck 硬拒（precheck_failed: country_name unauthorized filter，
2026-08 实测 8+ 条），也观测到无任何披露的静默全范围放行。

根因定位（详见任务报告 task-C2-report.md）：
_resolve_enum_component_filter 反查分支——当用户显式点名一组值（"国家为德国、法国"，
_labeled_value_match 判定 enumerated=True）但反查在授权枚举 values 里零命中时，
原实现直接 `return contract`，与"原文完全没提这个字段"的静默放行走同一条路径，
不区分"没提"和"提了但都不在授权范围内"，因此既不阻断也不披露。

修复：反查零命中且 `requested`（用户显式点名的首个值）非空时，改为阻断
（clarify_required）并在 clarification_messages_zh 披露具体表述；`requested` 为空
（原文确实没提该字段）时继续保留原有静默放行，不引入多余噪音。

历史说明：本文件原先同时对拍 Skill 版与内核版；Skill 本地规划器移除后只保留内核半边。
"""

from __future__ import annotations

from opscli.query.services.planner import query_plan

# 当前账号可见的国家授权原值：不含"德国""法国"，用于复现 QA 事故的权限缺口
COUNTRY_VALUES = ["美国", "加拿大"]


def _country_contract() -> dict:
    """构造一个待解析国家筛选的 planned 合同骨架。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": "country_name",
                    "label_zh": "国家",
                    "component_dataset_alias": "ds_country",
                    "component_table_id": 9,
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


def _resolve(query: str, enum_values: list) -> dict:
    """调用内核组件筛选解析（枚举经 enum_fn 注入），返回处理后的合同。"""

    def enum_fn(_table_id, _field_name, *, limit):
        return enum_values

    return query_plan._resolve_component_filters(
        _country_contract(), query, enum_fn, auto_enum=True
    )


def _country_filters(contract: dict) -> list:
    template = (contract.get("execution_ref") or {}).get("query_template") or {}
    return [
        item for item in template.get("filters") or [] if item.get("field") == "country_name"
    ]


def test_unauthorized_enumerated_values_are_not_injected_and_disclosed():
    """语义命中组件值"德国"（country_name），账号枚举只有[美国,加拿大]：无交集。

    不得注入 filters（否则执行器 precheck 硬拒，QA 实测形态
    precheck_failed: country_name unauthorized filter），且必须向用户披露识别到
    的表述与未注入的事实，不能悄悄放行成不含筛选条件的全范围查询。
    """
    contract = _resolve("国家为德国、法国的销量", COUNTRY_VALUES)

    assert not any(f.get("field") == "country_name" for f in _country_filters(contract))
    assert "query_template" not in contract["execution_ref"]
    assert contract["status"] == "clarify_required"
    messages = contract["model_view"]["clarification_messages_zh"]
    assert any("德国" in message for message in messages)


def test_single_unauthorized_labeled_value_still_blocks():
    """单值显式点名且未授权（既有行为的回归锚点，非标签枚举分支不应被本次改动破坏）。"""
    contract = _resolve("国家是德国的销量", COUNTRY_VALUES)

    assert contract["status"] == "clarify_required"
    assert "query_template" not in contract["execution_ref"]
    message = " ".join(contract["model_view"]["clarification_messages_zh"])
    assert "德国" in message


def test_partial_overlap_injects_only_authorized_values():
    """点名一组值时若存在交集，按交集放行（不因新增阻断分支而误伤已授权命中）。"""
    contract = _resolve("国家为德国、美国的销量", COUNTRY_VALUES)

    assert contract["status"] == "planned"
    assert _country_filters(contract) == [
        {"field": "country_name", "operator": "=", "value": "美国"}
    ]


def test_query_without_country_mention_passes_through():
    """原文完全没提国家筛选时继续静默放行，不因本次改动新增多余澄清噪音。"""
    contract = _resolve("查国家和ASIN的明细", COUNTRY_VALUES)

    assert contract["status"] == "planned"
    assert _country_filters(contract) == []


def test_bare_value_mention_of_unauthorized_country_is_blocked_with_known_values():
    """原文提到"德国站"但不含"国家"/"站点"标签词，且"德国"不在授权枚举里。

    反查机制（_reverse_lookup_component_matches）只拿"授权枚举原值"反过来在原文里找，
    天生看不见"原文提到了一个不在授权枚举里的国家"。2026-09-07 第二轮 E2E 验收把它
    定为 P0（「近7天销售额 只看德国」被放行成全部国家），随后给国家字段接入了常见国家
    词表（_KNOWN_COUNTRY_VALUES）：反查零命中时再用词表识别原文点名的未授权国家，
    转 component_filter_unauthorized 澄清并下发当前账号可见的国家候选，不注入、不放行。
    """
    contract = _resolve("查德国站近7天销量", COUNTRY_VALUES)

    assert contract["status"] == "clarify_required"
    assert _country_filters(contract) == []
    assert "query_template" not in contract["execution_ref"]
    assert "component_filter_unauthorized" in contract["model_view"]["clarification_reason_codes"]
    assert "德国" in " ".join(contract["model_view"]["clarification_messages_zh"])
