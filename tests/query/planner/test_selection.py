"""选表引擎移植对拍：adapter → 决策卡片 → 选表结果。

验证 scoped_metadata_index.build_cards 与 agent_query_planner.plan_query 迁入内核后
签名改为消费 MetadataAdapter，选表语义（候选就绪/需澄清）保持不变。
"""

import json
from importlib.resources import files

from opscli.query.services.planner.metadata_adapter import MetadataAdapter
from opscli.query.services.planner import scoped_metadata_index, agent_query_planner


def _rules():
    """从内核静态资源加载领域意图规则。"""
    return json.loads(
        (files("opscli.query.services.planner.resources") / "intent_rules.json").read_text(
            "utf-8"
        )
    )


def test_build_cards_from_adapter():
    """build_cards 从 adapter 聚合出含目标数据集的决策卡片。"""
    payload = {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "dataset_category": "normal",
                "description": "销售即时综合",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [],
    }
    cards = scoped_metadata_index.build_cards(MetadataAdapter(payload))
    assert any(c.get("dataset_alias") == "ds_sales" for c in cards)


def test_plan_query_selects_sales_dataset():
    """给出销售额诉求 → 选表引擎给出候选或澄清（非硬失败）。"""
    payload = {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "dataset_category": "normal",
                "description": "销售即时综合数据集",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 1,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "field_name": "sales_amount",
                "verbose_name": "销售额",
                "global_alias": "f_s",
                "field_type": "metric",
                "summary_expression": "sum(x)",
                "detail_expression": "x",
                "has_formula_config": 0,
            }
        ],
    }
    adapter = MetadataAdapter(payload)
    cards = agent_query_planner.load_authorized_cards(adapter)
    # 真实签名：plan_query(query, cards, rules, top_n=3, ...)
    sel = agent_query_planner.plan_query("查销售额", cards, _rules())
    # 返回 planner_contract_v2，选表结果在 planner_status
    assert sel.get("contract") == "planner_contract_v2"
    assert sel.get("planner_status") in ("candidate_ready", "clarify_required")


# ── 领域覆盖判定的字段证据回退（生产 dataset_constraints 误判）────────────────
#
# 背景：数据集的 profile["domains"] 只由 description 文本匹配 description_patterns
# 推出。"即时综合数据集"这类说明只能命中 sales，但其真实覆盖范围体现在字段上
# （表里确有 advertising_fee 等广告字段）。当用户请求包含派生比例词（毛利率/
# 广告占比/采购成本占比——表中无同名字段，故不会被候选身份剥离逻辑消掉）时，
# 语义层会提取出 advertising 领域，纯 domain 判定即误判为"数据集不覆盖"，
# 把已唯一定位到的数据集打回澄清（生产两周 229 次 dataset_constraints，
# 其中 93 次是这种"单候选仍澄清"，Agent 只能反复改写请求形成澄清死循环）。


def _instant_all_payload(with_ad_fields: bool = True) -> dict:
    """构造"说明只写即时综合、覆盖能力体现在字段"的授权元数据。

    with_ad_fields=False 时移除全部广告类字段，用于验证修复不是无脑放宽：
    字段里确实没有广告证据的数据集仍必须被判为不覆盖。
    """

    def _field(field_name: str, verbose_name: str, field_type: str = "metric") -> dict:
        return {
            "table_id": 1,
            "dataset_alias": "ds_all",
            "dataset_name": "instant_all_set",
            "field_name": field_name,
            "verbose_name": verbose_name,
            "global_alias": "",
            "field_type": field_type,
            "summary_expression": "",
            "detail_expression": "",
            "has_formula_config": 0,
        }

    fields = [
        _field("price", "销售额"),
        _field("order_qty", "订单销量"),
        _field("gross_profit", "毛利"),
        _field("purchase_cost", "采购成本"),
        _field("asin", "ASIN", "dimension"),
    ]
    if with_ad_fields:
        # 广告覆盖能力只体现在字段，description 里没有任何广告字样
        fields.insert(0, _field("advertising_fee", "广告花费"))
    return {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_all",
                "dataset_name": "instant_all_set",
                "dataset_category": "normal",
                "description": "即时综合数据集",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": fields,
    }


# 生产 conv=44289 请求原文的等价重构：显式点名数据集 + 派生比例词
_DERIVED_RATIO_QUERY = (
    "项目二部，即时综合数据集，按ASIN对比6月与5月的销量变化，"
    "同时查6月当月BI毛利率、广告占比、采购成本占比"
)


def test_field_evidence_covers_domain_missing_from_description():
    """字段含广告证据时，说明未写广告不得把唯一候选打回澄清。"""
    cards = agent_query_planner.load_authorized_cards(
        MetadataAdapter(_instant_all_payload())
    )
    sel = agent_query_planner.plan_query(_DERIVED_RATIO_QUERY, cards, _rules())
    assert sel["planner_status"] == "candidate_ready", (
        f"字段中存在 advertising_fee，不应判为领域不覆盖；"
        f"实际 missing={sel['missing_information']}"
    )
    assert sel["missing_information"] == []
    assert [c["dataset_name"] for c in sel["dataset_candidates"]] == ["instant_all_set"]


def test_domain_coverage_consistent_across_selection_paths():
    """同一卡片同一领域集：说明命中路径与默认推荐路径的覆盖判定必须一致。

    这是本次缺陷的判定性对照——补偿逻辑原先只存在于 _default_dataset_candidate，
    另两条判定缺失，导致同一事实在两条路径上结论相反。
    """
    rules_raw = _rules()
    rules = agent_query_planner._validate_rules(rules_raw)
    cards = agent_query_planner.load_authorized_cards(
        MetadataAdapter(_instant_all_payload())
    )
    profiles = [agent_query_planner._profile_card(card, rules) for card in cards]
    normalized = agent_query_planner._normalize(_DERIVED_RATIO_QUERY)
    candidates = agent_query_planner._description_candidates(normalized, profiles)
    semantic_query = agent_query_planner._semantic_query_without_candidate_identity(
        normalized, candidates, profiles
    )
    semantics = agent_query_planner.extract_query_semantics(semantic_query, rules)
    domains = set(semantics["domains"])
    slots = {name: set(values) for name, values in semantics["slots"].items()}
    # 前置条件：语义层确实提取出了 description 未覆盖的领域，否则本用例失去意义
    assert domains - profiles[0]["domains"], "用例前提失效：未产生 description 外的领域"

    covered = agent_query_planner._description_candidates_cover_constraints(
        candidates, profiles, domains, slots, rules
    )
    default_ok = agent_query_planner._default_dataset_candidate(
        profiles, domains, slots, list(semantics["metrics"]), rules
    )
    assert covered is True
    assert default_ok is not None
    assert bool(covered) == bool(default_ok)


def test_missing_field_evidence_still_blocks_uncovered_domain():
    """字段里确无广告证据时仍须判为不覆盖——修复不得退化为无条件放宽。"""
    rules_raw = _rules()
    rules = agent_query_planner._validate_rules(rules_raw)
    cards = agent_query_planner.load_authorized_cards(
        MetadataAdapter(_instant_all_payload(with_ad_fields=False))
    )
    profiles = [agent_query_planner._profile_card(card, rules) for card in cards]
    assert (
        agent_query_planner._covers(profiles[0], {"advertising"}, {}, rules) is False
    )
    assert (
        agent_query_planner._description_candidates_cover_constraints(
            [
                {
                    "dataset_alias": "ds_all",
                    "dataset_name": "instant_all_set",
                    "dataset_category": "normal",
                }
            ],
            profiles,
            {"advertising"},
            {},
            rules,
        )
        is False
    )


def test_covers_accepts_field_evidence_for_uncovered_domain():
    """阶段3 的 _covers 同样按字段证据回退，与说明命中路径口径统一。"""
    rules = agent_query_planner._validate_rules(_rules())
    cards = agent_query_planner.load_authorized_cards(
        MetadataAdapter(_instant_all_payload())
    )
    profiles = [agent_query_planner._profile_card(card, rules) for card in cards]
    assert "advertising" not in profiles[0]["domains"]
    assert agent_query_planner._covers(profiles[0], {"advertising"}, {}, rules) is True
