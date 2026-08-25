"""规划器主编排移植：adapter + 注入回调 → query_plan_model_contract_v2。

验证 query_plan 迁入内核后：
- build_query_plan/build_model_query_plan 数据源改为 MetadataAdapter；
- 元数据未就绪触发注入的 refresh_fn（替代 subprocess skills upgrade）；
- 平台/组件枚举走注入的 enum_fn（替代 subprocess opscli query simple）。
"""

import pytest

from opscli.query.services.planner.metadata_adapter import MetadataAdapter
from opscli.query.services.planner import agent_query_planner, plan_integrity, query_plan


def _sales_payload():
    """一个通过就绪判定的销售数据集（含维度/日期/指标）。"""
    return {
        "datasets": [
            {
                "table_id": 100,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "dataset_category": "normal",
                "description": "即时综合数据集",
                "remarks": "销售 库存 广告 综合",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 100,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "field_name": "stat_date",
                "verbose_name": "统计日期",
                "global_alias": "f_d",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 100,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "field_name": "sales_amount",
                "verbose_name": "销售额",
                "global_alias": "f_sa",
                "field_type": "metric",
                "summary_expression": "sum(sales_amount)",
                "detail_expression": "sales_amount",
                "has_formula_config": 1,
            },
        ],
    }


def test_build_model_query_plan_contract_shape():
    """就绪 adapter + 请求 → 模型合同 v2，顶层键齐全。"""
    adapter = MetadataAdapter(_sales_payload())
    contract = query_plan.build_model_query_plan(
        adapter, "查询销售额 近7天", enum_fn=lambda *a, **k: []
    )
    assert contract["contract"] == "query_plan_model_contract_v2"
    assert contract["data_state"] == "ready"
    assert "model_view" in contract
    assert "execution_ref" in contract
    assert "status" in contract


def test_single_currency_intent_is_bound_into_query_template():
    """单币种意图必须写入完整性绑定模板，不能在调用服务端前静默丢失。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_sales_payload()),
        "使用欧元查询2026-07-22至2026-08-20的销售额合计",
        enum_fn=lambda *a, **k: [],
    )

    assert contract["status"] == "planned"
    assert contract["execution_ref"]["query_template"]["globalCurrency"] == "EUR"
    assert "query_templates" not in contract["execution_ref"]
    assert plan_integrity.verify(contract) is True


def test_multi_currency_intent_emits_integrity_bound_templates():
    """多币种请求必须生成除币种外同口径的独立模板并一起纳入摘要。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_sales_payload()),
        "分别使用人民币和加拿大元查询近7天销售额",
        enum_fn=lambda *a, **k: [],
    )

    assert contract["status"] == "planned"
    execution = contract["execution_ref"]
    assert execution["requested_global_currencies"] == ["CNY", "CAD"]
    assert [item["globalCurrency"] for item in execution["query_templates"]] == [
        "CNY",
        "CAD",
    ]
    assert execution["query_template"] == execution["query_templates"][0]
    cny_scope = {
        key: value
        for key, value in execution["query_templates"][0].items()
        if key != "globalCurrency"
    }
    cad_scope = {
        key: value
        for key, value in execution["query_templates"][1].items()
        if key != "globalCurrency"
    }
    assert cny_scope == cad_scope
    assert plan_integrity.verify(contract) is True


def test_refresh_fn_invoked_when_metadata_empty():
    """空 adapter → 触发 refresh_fn 重取全量，就绪后正常产出内部合同。"""
    calls = {"n": 0}

    def refresh_fn():
        calls["n"] += 1
        return _sales_payload()

    internal = query_plan.build_query_plan(
        MetadataAdapter({"datasets": [], "fields": []}),
        "查询销售额",
        refresh_fn=refresh_fn,
    )
    assert calls["n"] == 1
    assert internal["data_state"] == "ready"
    assert internal["upgrade_performed_this_call"] is True


def test_refresh_failed_contract_when_still_empty():
    """refresh 后仍空 → 返回带 recovery_command 的刷新合同（不阻塞）。"""
    internal = query_plan.build_query_plan(
        MetadataAdapter({"datasets": [], "fields": []}),
        "查询销售额",
        refresh_fn=lambda: {"datasets": [], "fields": []},
    )
    assert internal["next_action"] == "refresh_authorized_metadata"
    assert internal["recovery_state"] == "refresh_failed"
    # 恢复命令须指向内核入口，不得残留旧 Skill 脚本路径
    assert "scripts/query_plan.py" not in internal["recovery_command"]


def test_no_refresh_fn_returns_refresh_contract():
    """空 adapter 且未注入 refresh_fn → 直接返回刷新合同。"""
    internal = query_plan.build_query_plan(
        MetadataAdapter({"datasets": [], "fields": []}), "查询销售额"
    )
    assert internal["next_action"] == "refresh_authorized_metadata"


def test_platform_enum_wrapper_uses_injected_enum_fn():
    """平台枚举包装函数经注入 enum_fn 取值并去重；enum_fn 缺失时回落空。"""
    seen = {}

    def enum_fn(table_id, field_name, *, limit):
        seen["args"] = (table_id, field_name, limit)
        return ["amazon_sc", "amazon_vc", "amazon_sc"]

    values = query_plan._auto_enum_platform_values(enum_fn, 200)
    assert values == ["amazon_sc", "amazon_vc"]
    assert seen["args"] == (200, "platform_name", 100)
    # 未注入 enum_fn 时安全回落空列表（走手动枚举命令）
    assert query_plan._auto_enum_platform_values(None, 200) == []


def test_platform_scope_subtracts_explicit_vc_exclusion():
    """正向 Amazon 范围减去否定语境中的 Amazon VC 后，只能保留 SC。"""
    rules = query_plan._load_rules_resource()
    selection = {"slots": {"platform": ["amazon", "amazon_vc"]}}

    scope = query_plan._platform_scope(
        selection,
        rules,
        ["Amazon", "Amazon VC"],
        query="仅取platform_name=Amazon，排除 Amazon VC",
    )

    assert scope["requested_slots"] == ["amazon"]
    assert scope["excluded_slots"] == ["amazon_vc"]
    assert scope["semantic_members"] == ["amazon_sc"]
    assert scope["enum_resolution"]["resolved_filter_values"] == ["Amazon"]


# ── 澄清文案完备性（Agent 盲重试的直接诱因）──────────────────────────────────
#
# clarification_messages_zh 由 CLARIFICATION_MESSAGES.get(code, 兜底文案) 生成。
# 缺配文案的 code 会静默退化成「需要补充查询条件。」，不告诉调用方到底缺什么，
# Agent 只能反复改写请求盲重试（生产两周 76 次澄清落在缺文案的 code 上）。
# 本用例用 AST 提取选表器实际产出的全部 code，保证新增分支不会漏配文案。


def _planner_missing_information_codes() -> set[str]:
    """AST 提取 agent_query_planner 中 _result(...) 实际产出的 missing 值。"""
    import ast
    from pathlib import Path

    source = Path(agent_query_planner.__file__).read_text("utf-8")
    codes: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "_result"
            and node.args
        ):
            last = node.args[-1]
            if isinstance(last, ast.Constant) and isinstance(last.value, str):
                codes.add(last.value)
    return codes


def test_every_clarification_code_has_dedicated_message():
    """所有可能产出的澄清 code 都必须配有专属中文文案，不得落到兜底。"""
    # 合同层在选表 code 之外追加的确认类 code
    contract_level = {
        "field_identity",
        "time_scope_confirmation",
        "recommended_fields_confirmation",
        "default_dataset_confirmation",
        "time_comparison_unsupported",
    }
    produced = _planner_missing_information_codes() | contract_level
    missing = sorted(produced - set(query_plan.CLARIFICATION_MESSAGES))
    assert not missing, f"以下澄清 code 缺专属文案，会退化为兜底提示：{missing}"


def test_clarification_messages_are_actionable():
    """每条澄清文案须为非空中文，且不得与兜底文案雷同。"""
    for code, message in query_plan.CLARIFICATION_MESSAGES.items():
        assert isinstance(message, str) and message.strip(), f"{code} 文案为空"
        assert message != "需要补充查询条件。", f"{code} 文案与兜底雷同"
        assert any("一" <= ch <= "鿿" for ch in message), f"{code} 文案非中文"


# ── 组件枚举失败的可重试性区分（避免 Agent 徒劳重试）────────────────────────
#
# 部门枚举失败时合同一律给出 retry_component_permission_enum + "请原样重试一次"。
# 但实测 QA 组件表 custom_dept_set（table_id=48）在后端元数据里字段数为 0，
# dept_name 是 _derived_component_fields 从 select_columns 派生猜测出来的，
# 后端直接报"字段不存在: dept_name"——这是配置类故障，重试多少次都不会成功。
# 客户端无法猜出后端认什么字段名（根因在后端），但必须把"重试无用"如实告知，
# 否则 Agent 会按 next_action 反复重试。


def _dept_contract() -> dict:
    """构造一个待解析部门筛选的 planned 合同骨架。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "filter_components": [
                {
                    "field_name": "dept_name",
                    "label_zh": "部门",
                    "component_dataset_alias": "ds_dept",
                    "component_table_id": 48,
                }
            ],
            "query_template": {"tableId": 1, "dimensions": [], "metrics": [], "filters": []},
        },
    }


def test_component_enum_remote_error_is_not_advertised_as_retryable():
    """枚举调用本身报错（组件表未暴露该字段）时不得建议原样重试。"""

    def enum_fn(_table_id, _field_name, *, limit):
        raise RuntimeError("字段不存在: dept_name")

    contract = query_plan._resolve_component_filters(
        _dept_contract(), "查询项目二部的销量", enum_fn, auto_enum=True
    )
    view = contract["model_view"]
    assert contract["status"] == "blocked"
    # 仍须阻断查询，绝不放大为全范围
    assert "query_template" not in contract["execution_ref"]
    assert view["next_action"] != "retry_component_permission_enum"
    message = " ".join(view["clarification_messages_zh"])
    assert "重试" not in message or "重试无效" in message or "重试无用" in message
    # 真实错误必须透出，便于定位与报障
    assert "字段不存在" in message


def test_component_enum_empty_result_keeps_retry_semantics():
    """枚举调用成功但返回空（当前账号无授权部门）时保留原有重试语义。"""
    contract = query_plan._resolve_component_filters(
        _dept_contract(), "查询项目二部的销量", lambda *_a, **_k: [], auto_enum=True
    )
    view = contract["model_view"]
    assert contract["status"] == "blocked"
    assert view["next_action"] == "retry_component_permission_enum"
    assert "query_template" not in contract["execution_ref"]


def test_component_enum_success_still_resolves_filter():
    """枚举成功且唯一等值命中时照常写入筛选条件（成功路径不受影响）。"""
    contract = query_plan._resolve_component_filters(
        _dept_contract(),
        "查询项目二部的销量",
        lambda *_a, **_k: ["项目二部", "项目九部"],
        auto_enum=True,
    )
    assert contract["status"] == "planned"
    filters = contract["execution_ref"]["query_template"]["filters"]
    assert {"field": "dept_name", "operator": "=", "value": "项目二部"} in filters


# ── 部门筛选的枚举驱动识别（反查兜裸值 + 宽后缀候选转澄清）────────────────────
#
# 真实部门名形态任意（宁波/泛泰克/孵化部/经营管理团队），原有三条窄正则
# 抽不到值时会被当成「没有筛选意图」直接放行——静默放大为全量查询。
# 修法：dept_name 开启 reverse_lookup 用授权枚举原值反查原文兜住真实部门；
# 再加一条宽后缀「X部」候选正则，候选枚举零命中时走既有 clarify 分支，
# 拦住虚构部门（E2E T5-3「魔法部」静默全量的回归锚点）。

# 当前账号授权的部门枚举：混合编号部门、无后缀地名部门、品牌型名与带后缀特殊名
DEPT_ENUM_VALUES = ["项目二部", "项目九部", "宁波", "泛泰克", "孵化部"]


def _resolve_dept(query: str) -> dict:
    """用固定部门枚举跑一遍组件筛选解析。"""
    return query_plan._resolve_component_filters(
        _dept_contract(), query, lambda *_a, **_k: DEPT_ENUM_VALUES, auto_enum=True
    )


def test_bare_department_value_resolved_by_reverse_lookup():
    """无后缀部门裸值（「宁波」）必须由授权枚举反查兜住，不得静默全量。"""
    contract = _resolve_dept("近7天宁波的订单量")
    assert contract["status"] == "planned"
    filters = contract["execution_ref"]["query_template"]["filters"]
    assert {"field": "dept_name", "operator": "=", "value": "宁波"} in filters


def test_brandlike_department_value_resolved_by_reverse_lookup():
    """品牌型无后缀部门名（「泛泰克」）同样由反查唯一锁定。"""
    contract = _resolve_dept("近7天泛泰克的订单量")
    assert contract["status"] == "planned"
    filters = contract["execution_ref"]["query_template"]["filters"]
    assert {"field": "dept_name", "operator": "=", "value": "泛泰克"} in filters


def test_suffixed_department_after_time_words_resolves():
    """宽后缀候选必须剥掉紧邻的时间词（「近7天孵化部」→「孵化部」）再等值匹配。"""
    contract = _resolve_dept("近7天孵化部的订单量")
    assert contract["status"] == "planned"
    filters = contract["execution_ref"]["query_template"]["filters"]
    assert {"field": "dept_name", "operator": "=", "value": "孵化部"} in filters


def test_unknown_suffixed_department_requires_clarification():
    """虚构部门「魔法部」不在授权枚举中：必须转澄清，不得静默放大为全量查询。

    E2E T5-3 回归锚点：原先宽后缀形态抽不到候选，「魔法部」被当成没有
    筛选意图直接放行，查询悄悄变成全部门口径。
    """
    contract = _resolve_dept("近7天魔法部的订单量")
    assert contract["status"] == "clarify_required"
    assert "query_template" not in contract["execution_ref"]
    message = " ".join(contract["model_view"]["clarification_messages_zh"])
    assert "魔法部" in message


def test_generic_suffix_words_do_not_trigger_department_clarify():
    """「全部」这类以「部」结尾的通用词在停用词表内，不得误判成部门候选。"""
    contract = _resolve_dept("近7天全部渠道的订单量")
    assert contract["status"] == "planned"
    filters = contract["execution_ref"]["query_template"]["filters"]
    assert not [item for item in filters if item.get("field") == "dept_name"]


# ── 固定槽位多覆盖的强制披露（Task 8 内核镜像）────────────────────────────────
#
# Skill 版有同名端到端回归（tests/skills/test_dataset_query_planner.py），
# 内核版是另一条独立的调用链（MetadataAdapter + 注入回调），必须各自守一遍：
# 只在 Skill 侧加测试，内核侧的候选构造路径漏补覆盖信息时不会有任何红灯。


def _grain_surplus_payload():
    """grain 固定为 keyword+search_term 的数据集：用户只要搜索词级，数据集更细。"""
    return {
        "datasets": [
            {
                "table_id": 300,
                "dataset_alias": "ds_kw_st",
                "dataset_name": "关键词搜索词双维度表",
                "dataset_category": "normal",
                "description": "用于分析亚马逊消费者搜索词与关键词维度下的转化情况，支持选品优化。",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 300,
                "dataset_alias": "ds_kw_st",
                "dataset_name": "关键词搜索词双维度表",
                "field_name": "date_id",
                "verbose_name": "日期",
                "global_alias": "f_kw_date",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 300,
                "dataset_alias": "ds_kw_st",
                "dataset_name": "关键词搜索词双维度表",
                "field_name": "conv_rate",
                "verbose_name": "转化率",
                "global_alias": "f_conv_rate",
                "field_type": "metric",
                "has_formula_config": 0,
            },
        ],
    }


def _ad_type_surplus_payload():
    """ad_type 固定为 SP+SD+SB 且无「广告类型」筛选字段的数据集：多余类型筛不掉。"""
    return {
        "datasets": [
            {
                "table_id": 310,
                "dataset_alias": "ds_spsdsb",
                "dataset_name": "合并广告表",
                "dataset_category": "normal",
                "description": "亚马逊SP、SD、SB广告汇总数据集",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 310,
                "dataset_alias": "ds_spsdsb",
                "dataset_name": "合并广告表",
                "field_name": "date_id",
                "verbose_name": "日期",
                "global_alias": "f_ad_date",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 310,
                "dataset_alias": "ds_spsdsb",
                "dataset_name": "合并广告表",
                "field_name": "ad_cost",
                "verbose_name": "广告花费",
                "global_alias": "f_ad_cost",
                "field_type": "metric",
                "has_formula_config": 0,
            },
        ],
    }


def test_grain_disclosure_survives_explicit_dataset_reference():
    """用户点名数据集（走显式命中路径）时强制披露不能消失。

    审查实测：点名数据集名后披露变 None，只说业务诉求反而有披露——
    「说得越具体反而越危险」被搬到了披露层。
    """
    for query in (
        "近7天搜索词的转化率",  # 语义打分路径（原本就有披露）
        "关键词搜索词双维度表 近7天搜索词的转化率",  # 显式中文名命中
        "ds_kw_st 近7天搜索词的转化率",  # 显式技术标识命中
    ):
        contract = query_plan.build_model_query_plan(
            MetadataAdapter(_grain_surplus_payload()), query, enum_fn=lambda *a, **k: []
        )
        disclosures = contract["model_view"].get("grain_disclosure_zh") or []
        assert any("关键词" in item for item in disclosures), f"披露丢失：{query}"
        assert all(
            item in contract["answer_contract"]["required_disclosures_zh"]
            for item in disclosures
        ), query
        # 内部标识不得泄露到面向用户的中文披露句
        assert not any("keyword" in item or "grain" in item for item in disclosures), query


def test_ad_type_surplus_disclosure_says_cannot_filter():
    """ad_type 多覆盖时必须说「筛不掉、是合计」，不能说「粒度更细」。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_ad_type_surplus_payload()),
        "查询近7天SP广告的广告花费",
        enum_fn=lambda *a, **k: [],
    )
    text = "".join(contract["model_view"]["grain_disclosure_zh"])
    assert "无法按广告类型筛选" in text
    assert "不得当作纯 SP 的数据汇报" in text
    assert "粒度比请求更细" not in text
    assert "ad_type" not in text


def test_grain_disclosure_survives_default_dataset_recommendation():
    """默认「即时综合数据集」推荐路径（第三条候选构造路径）也必须带强制披露。"""
    payload = _grain_surplus_payload()
    dataset = payload["datasets"][0]
    # dataset_name 命中默认表身份，description 仍提供 keyword+search_term 两个 grain 取值
    dataset["dataset_name"] = "即时综合数据集"
    dataset["description"] = "亚马逊消费者搜索词与关键词维度的即时综合明细，含转化情况。"
    for field in payload["fields"]:
        field["dataset_name"] = "即时综合数据集"

    contract = query_plan.build_model_query_plan(
        MetadataAdapter(payload), "近7天搜索词的转化率", enum_fn=lambda *a, **k: []
    )

    assert contract["model_view"]["default_dataset_recommendation_zh"]
    disclosures = contract["model_view"].get("grain_disclosure_zh") or []
    assert any("关键词" in item for item in disclosures), "默认表推荐路径丢失强制披露"
    assert all(
        item in contract["answer_contract"]["required_disclosures_zh"] for item in disclosures
    )


# ── 无日期字段数据集的时间口径一致性（F3）──────────────────────────────────
#
# _build_query_template 只在 date_fields 非空时才落日期过滤，但 time_scope 是按
# 用户原文独立解析的。两者不一致时合同会声明一个根本没生效的时间窗，Agent 按
# SKILL.md 把它当权威口径讲给用户，数字却是全表历史累计——无异常、无阻断、无披露。
# 这是唯一会产出「看起来完全正常的错误答案」的路径，必须由合同层收敛。


def _no_date_field_payload():
    """一个没有任何日期字段的数据集（如实时库存快照）。"""
    return {
        "datasets": [
            {
                "table_id": 200,
                "dataset_alias": "ds_stock",
                "dataset_name": "custom_realtime_inventory_set",
                "dataset_category": "normal",
                "description": "实时库存明细",
                "remarks": "库存 缺货 履约",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 200,
                "dataset_alias": "ds_stock",
                "dataset_name": "custom_realtime_inventory_set",
                "field_name": "ed_sku",
                "verbose_name": "公司SKU",
                "global_alias": "f_sku",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 200,
                "dataset_alias": "ds_stock",
                "dataset_name": "custom_realtime_inventory_set",
                "field_name": "total_qty",
                "verbose_name": "总库存",
                "global_alias": "f_tq",
                "field_type": "metric",
                "has_formula_config": 0,
            },
        ],
    }


def test_no_date_field_never_declares_an_effective_time_window():
    """无日期字段时不得声明具体日期窗：模板落不下过滤，声明即误导。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_no_date_field_payload()),
        "实时库存明细近7天的总库存",
        enum_fn=lambda *a, **k: [],
    )
    scope = contract["execution_ref"]["time_scope"]
    assert scope["unbounded"] is True
    assert scope["start"] is None and scope["end"] is None
    scope_zh = contract["model_view"]["time_scope_zh"]
    assert "2026" not in scope_zh and "~" not in scope_zh, f"仍在声明日期窗：{scope_zh}"
    assert "没有日期字段" in scope_zh
    template = contract["execution_ref"].get("query_template") or {}
    assert not template.get("filters"), "无日期字段却落了过滤条件"


def test_no_date_field_forces_disclosure_of_dropped_time_scope():
    """时间窗被收敛为全时段时必须强制披露，否则 Agent 不会向用户交代差异。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_no_date_field_payload()),
        "实时库存明细近7天的总库存",
        enum_fn=lambda *a, **k: [],
    )
    disclosures = contract["answer_contract"]["required_disclosures_zh"]
    assert any("无法作为查询条件生效" in item for item in disclosures), disclosures


def test_no_date_field_rejects_period_comparison():
    """没有日期字段就无从做环比/同比，必须澄清而不是静默丢掉对比期。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_no_date_field_payload()),
        "实时库存明细近7天的总库存，和上一个周期做环比",
        enum_fn=lambda *a, **k: [],
    )
    assert contract["status"] == "clarify_required"
    assert "time_comparison_unsupported" in contract["model_view"]["clarification_reason_codes"]
    scope = contract["execution_ref"]["time_scope"]
    assert scope["comparison_type"] is None
    assert "对比期" not in contract["model_view"]["time_scope_zh"]


def test_dataset_with_date_field_keeps_its_time_window():
    """有日期字段的数据集不受该闸影响：时间窗与日期过滤都要照常下发。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_sales_payload()),
        "查询即时综合数据集近7天的销售额",
        enum_fn=lambda *a, **k: [],
    )
    scope = contract["execution_ref"]["time_scope"]
    assert scope["unbounded"] is False
    assert scope["start"] and scope["end"]
    fields = {f["field"] for f in contract["execution_ref"]["query_template"]["filters"]}
    assert "stat_date" in fields


# ── 平台词表完备性（F4）────────────────────────────────────────────────────
#
# slots.platform 识别 10 个平台，platform_scope.members 却只定义了 3 个。
# 槽位抽取成功但展开为空成员时，_resolve_platform_enum 返回 not_applicable，
# _next_action 判成 block_platform_scope_unsupported——对只授权 Temu 的账号而言，
# 任何带平台筛选的自然语言取数都被直接阻断（矩阵实测 D9 维度 0/44 可规划）。
# 这类漂移必须在规则校验期暴露，而不是在用户面前。


def test_every_recognized_platform_can_be_expanded():
    """slots.platform 里的每个平台都必须能展开成语义成员，不允许识别得到却用不了。"""
    rules = query_plan._load_rules_resource()
    recognized = set(rules["slots"]["platform"])
    expandable = set(rules["platform_scope"]["members"])
    assert recognized == expandable, (
        f"识别得到却无法展开的平台：{sorted(recognized - expandable)}；"
        f"定义了成员却不被识别的平台：{sorted(expandable - recognized)}"
    )


def test_every_semantic_member_has_filter_values():
    """每个语义成员都必须配枚举别名，否则永远无法与服务端授权值对上。"""
    rules = query_plan._load_rules_resource()
    members = {m for values in rules["platform_scope"]["members"].values() for m in values}
    assert set(rules["platform_scope"]["filter_values"]) == members


def test_validate_rules_rejects_unexpandable_platform():
    """校验器必须拒绝「识别得到但 members 缺条目」的规则文件（防止漂移复发）。"""
    import copy

    from opscli.query.services.planner import typed_schema_linking

    broken = copy.deepcopy(query_plan._load_rules_resource())
    broken["platform_scope"]["members"].pop("temu")
    broken["platform_scope"]["filter_values"].pop("temu")
    with pytest.raises(ValueError, match="bad_platform_scope_values"):
        typed_schema_linking.validate_rules(broken)


def test_authorized_non_amazon_platform_resolves_to_filter_value():
    """非亚马逊平台（如账号唯一授权的 Temu）必须能解析成可用的筛选值。"""
    rules = query_plan._load_rules_resource()
    scope = query_plan._platform_scope(
        {"slots": {"platform": ["temu"]}}, rules, ["Temu"], query="近30天Temu平台的销售额"
    )
    assert scope["semantic_members"] == ["temu"]
    assert scope["enum_resolution"]["status"] == "resolved"
    assert scope["enum_resolution"]["resolved_filter_values"] == ["Temu"]


# ── 阻断态必须自带可执行材料（F5）──────────────────────────────────────────
#
# answer_contract 会强制要求「说明当前查询被阻断的原因」，但合同里从来没有原因文本、
# 没有 recovery_command、也不说当前账号实际授权了什么。要求解释却不提供解释材料，
# Agent 只能泛泛而谈或违反 no-guess 政策去猜。更糟的是阻断时还留着
# 「本次默认按亚马逊SC + 亚马逊VC处理」这句完成态披露——本次根本没有处理。


def test_every_block_action_has_a_reason_message():
    """_next_action 产出的每个 block_* 都必须配中文原因，不得只留空要求。"""
    import ast
    from pathlib import Path

    source = Path(query_plan.__file__).read_text("utf-8")
    produced = {
        node.value.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.startswith("block_")
    }
    missing = sorted(produced - set(query_plan.BLOCK_REASON_MESSAGES))
    assert not missing, f"以下阻断动作缺中文原因，Agent 无法向用户交代：{missing}"


def test_blocked_contract_carries_reason_in_disclosures():
    """任一阻断分支都要把中文原因同时放进 model_view 与强制披露。"""
    contract = query_plan.build_model_query_plan(
        MetadataAdapter(_sales_payload()),
        "查询即时综合数据集近30天亚马逊平台的销售额",
        enum_fn=lambda *a, **k: ["Temu"],
    )
    if contract["status"] != "blocked":
        pytest.skip("该 fixture 未进入平台阻断分支")
    reason = contract["model_view"].get("block_reason_zh")
    assert reason, "阻断合同没有中文原因，Agent 无法向用户交代"
    assert reason in contract["answer_contract"]["required_disclosures_zh"]


def test_authorized_enum_values_are_kept_for_alternatives():
    """枚举到的授权原值必须留在 scope 上，阻断时才能回填成可选项。"""
    scope = query_plan._platform_scope(
        {"slots": {"platform": ["amazon"]}},
        query_plan._load_rules_resource(),
        ["Temu"],
        query="近30天亚马逊平台的销售额",
    )
    # 请求亚马逊、账号只授权 Temu → 无交集，这正是要给出可选项的场景
    assert scope["enum_resolution"]["status"] == "no_authorized_overlap"
    assert scope["authorized_enum_values"] == ["Temu"]


def test_blocked_platform_does_not_claim_default_handling():
    """阻断时不得保留「本次默认按亚马逊SC + 亚马逊VC处理」这类完成态披露。"""
    scope = {
        "requested_slots": ["amazon"],
        "excluded_semantic_members": [],
        "enum_resolution": {"status": "no_authorized_overlap"},
    }
    blocked = _joined(query_plan._platform_scope_disclosures(scope, blocked=True))
    assert "默认按亚马逊SC + 亚马逊VC处理" not in blocked
    assert "被阻断" in blocked
    # 非阻断路径的原有披露必须保留
    normal = _joined(query_plan._platform_scope_disclosures(scope))
    assert "默认按亚马逊SC + 亚马逊VC处理" in normal


def _joined(items) -> str:
    return "".join(items or [])


# ── 澄清话术与同名候选区分（F7 / F8）──────────────────────────────────────
#
# business_dataset 同时承接「命中权限枚举组件」与「命中多个同名数据集」两种成因，
# 共用一句笼统文案时 Agent 无从追问：7 张组件表在 14 个维度上全部卡死，
# 两张同名的「用户仪表盘分享明细」也因候选卡片 name_zh 完全相同而无法被选中。


def test_component_hit_says_it_is_not_a_business_dataset():
    """命中权限枚举组件时必须点破「组件表不能当业务结果集」。"""
    message = query_plan._clarification_message(
        "business_dataset",
        {"dataset_candidates": [{"dataset_alias": "ds_c", "dataset_category": "query_component"}]},
        {"ds_c": "查询组件产品数据集"},
    )
    assert "权限枚举组件" in message
    assert message != "需要补充查询条件。"


def test_same_name_hit_says_it_is_a_name_conflict():
    """命中多个同名数据集时必须点破是同名冲突，并指引按序号选择。"""
    message = query_plan._clarification_message(
        "business_dataset",
        {
            "dataset_candidates": [
                {"dataset_alias": "ds_a", "dataset_category": "normal"},
                {"dataset_alias": "ds_b", "dataset_category": "normal"},
            ]
        },
        {"ds_a": "用户仪表盘分享明细", "ds_b": "用户仪表盘分享明细"},
    )
    assert "同名" in message
    assert message != "需要补充查询条件。"


def test_same_name_candidate_cards_are_distinguishable():
    """同名候选卡片必须带序号，否则 Agent 无法构造有效选项。"""
    cards = query_plan._candidate_cards_zh(
        {
            "dataset_candidates": [
                {"dataset_alias": "ds_a", "reasons": ["explicit_name"]},
                {"dataset_alias": "ds_b", "reasons": ["explicit_name"]},
            ]
        },
        {"ds_a": "用户仪表盘分享明细", "ds_b": "用户仪表盘分享明细"},
        {"ds_a": "9 个维度、1 个指标", "ds_b": "1 个维度、1 个指标"},
    )
    names = [card["name_zh"] for card in cards]
    assert len(names) == len(set(names)), f"同名候选无法区分：{names}"
    assert all("同名第" in name for name in names)


def test_unique_candidate_card_keeps_plain_name():
    """非同名候选不加序号后缀，避免给唯一候选制造多余噪声。"""
    cards = query_plan._candidate_cards_zh(
        {"dataset_candidates": [{"dataset_alias": "ds_a", "reasons": ["explicit_name"]}]},
        {"ds_a": "发货数据集"},
        {},
    )
    assert cards[0]["name_zh"] == "发货数据集"


# ── 嵌套字段标签的吞并边界（F6）────────────────────────────────────────────
#
# 「最长标签吞并」对「同一段文本同时命中两个标签」是对的（查"广告销售额"不该额外
# 产出"销售额"），但它无法区分「用户在两个不同位置分别说了两个字段」。
# 实测「本月的花费(原币)和花费」只绑定到 cost，cost_cny 被静默丢弃，
# 且 model_view.metrics 也只报一个，用户无从察觉少了一半（10/35 个多指标请求中招）。


def _metric(field_name: str, label: str) -> dict:
    return {"field_name": field_name, "verbose_name": label, "selection_source": "query"}


def test_separately_named_nested_labels_are_both_kept():
    """用户在不同位置分别点名两个嵌套标签时，两个都要保留。"""
    kept = query_plan._longest_unique_labels(
        [_metric("cost", "花费(原币)"), _metric("cost_cny", "花费")],
        query_plan._normalize("SP广告数据集本月的花费(原币)和花费"),
    )
    assert [item["field_name"] for item in kept] == ["cost", "cost_cny"]


def test_single_mention_still_swallows_shorter_label():
    """同一段文本命中两个标签时仍然只保留最长的，不产出重复结论。"""
    kept = query_plan._longest_unique_labels(
        [_metric("ads_sales", "广告销售额"), _metric("sales", "销售额")],
        query_plan._normalize("查询近7天的广告销售额"),
    )
    assert [item["field_name"] for item in kept] == ["ads_sales"]


def test_swallow_judgement_uses_spans_not_substring():
    """判据是命中区间：短标签只要在长标签区间之外出现过就不算被吞并。"""
    covered = query_plan._normalize("查询广告销售额")
    assert query_plan._is_swallowed("销售额", "广告销售额", covered) is True
    separate = query_plan._normalize("查询广告销售额和销售额")
    assert query_plan._is_swallowed("销售额", "广告销售额", separate) is False
