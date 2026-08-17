"""意图匹配器护栏透传回归：catalog 的业务约束不许在匹配层被静默丢弃。

为什么需要：catalog 里 36/41 条意图带 hard_constraints（如"库存快照字段只能用于
明细表"），此前 _intent_constraints 未透传这三个键，Agent 经 query intent 拿到的
候选会丢失全部防错数护栏——同一份数据走 local_fallback.py 却是带的，两条路径不一致。
"""
from opscli.query.services.intent_matcher import match_catalog_intents


def _catalog_with_guardrails() -> dict:
    return {
        "version": "v1.0.0",
        "intent_count": 1,
        "intents": [{
            "intent_code": "ops_comprehensive_monitoring",
            "intent_name": "综合运营监控",
            "table_id": 1,
            "dataset_alias": "ds_d35ac6f3910c",
            "dataset_name": "即时综合数据集",
            "keywords": ["经营大盘"],
            "use_cases": [],
            "scenario_description": "",
            "priority": 100,
            "hard_constraints": ["总库存属于库存快照字段，只能用于明细表或无聚合过滤条件"],
            "avoid_when": ["亚马逊广告活动明细深挖"],
            "clarify_when": ["用户只问单一业务域时需判断是否转专项数据集"],
        }],
    }


def test_intent_constraints_carry_guardrails():
    """hard_constraints / avoid_when / clarify_when 必须原样出现在候选约束里。"""
    result = match_catalog_intents(_catalog_with_guardrails(), "经营大盘")
    constraints = result["candidates"][0]["intent_constraints"]
    assert constraints["hard_constraints"] == ["总库存属于库存快照字段，只能用于明细表或无聚合过滤条件"]
    assert constraints["avoid_when"] == ["亚马逊广告活动明细深挖"]
    assert constraints["clarify_when"] == ["用户只问单一业务域时需判断是否转专项数据集"]


def test_intent_constraints_default_guardrails_to_empty_lists():
    """catalog 缺这三个键时给空列表，不得抛 KeyError。"""
    catalog = _catalog_with_guardrails()
    for key in ("hard_constraints", "avoid_when", "clarify_when"):
        del catalog["intents"][0][key]
    result = match_catalog_intents(catalog, "经营大盘")
    constraints = result["candidates"][0]["intent_constraints"]
    assert constraints["hard_constraints"] == []
    assert constraints["avoid_when"] == []
    assert constraints["clarify_when"] == []
