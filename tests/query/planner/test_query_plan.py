"""规划器主编排移植：adapter + 注入回调 → query_plan_model_contract_v2。

验证 query_plan 迁入内核后：
- build_query_plan/build_model_query_plan 数据源改为 MetadataAdapter；
- 元数据未就绪触发注入的 refresh_fn（替代 subprocess skills upgrade）；
- 平台/组件枚举走注入的 enum_fn（替代 subprocess opscli query simple）。
"""

from opscli.query.services.planner.metadata_adapter import MetadataAdapter
from opscli.query.services.planner import query_plan


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
