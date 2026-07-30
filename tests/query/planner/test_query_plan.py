"""规划器主编排移植：adapter + 注入回调 → query_plan_model_contract_v2。

验证 query_plan 迁入内核后：
- build_query_plan/build_model_query_plan 数据源改为 MetadataAdapter；
- 元数据未就绪触发注入的 refresh_fn（替代 subprocess skills upgrade）；
- 平台/组件枚举走注入的 enum_fn（替代 subprocess opscli query simple）。
"""

from opscli.query.services.planner.metadata_adapter import MetadataAdapter
from opscli.query.services.planner import agent_query_planner, query_plan


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
