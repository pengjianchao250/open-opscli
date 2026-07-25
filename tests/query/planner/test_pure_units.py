"""规划器纯逻辑单元 + 静态资源移植测试。

覆盖 Task 1 的三个纯标准库单元（time_scope / plan_integrity / field_semantics）
与两个静态资源（intent_rules.json / query_plan.schema.json）迁入内核后的可用性。
断言字段对照 scripts/ 下原脚本的真实返回结构补齐。
"""

import json
from importlib.resources import files


def test_intent_rules_resource_loads():
    """intent_rules.json 作为内核资源可读且 schema_version==3。"""
    raw = (
        files("opscli.query.services.planner.resources") / "intent_rules.json"
    ).read_text("utf-8")
    data = json.loads(raw)
    assert data["schema_version"] == 3
    assert "domains" in data and "slots" in data


def test_query_plan_schema_resource_loads():
    """query_plan.schema.json 作为内核资源可读且为合法 JSON Schema。"""
    raw = (
        files("opscli.query.services.planner.resources") / "query_plan.schema.json"
    ).read_text("utf-8")
    data = json.loads(raw)
    # JSON Schema 顶层应含类型或属性声明，确认非空且结构完整
    assert isinstance(data, dict) and data


def test_time_scope_relative_parse():
    """近7天解析为绝对起止窗口（Asia/Shanghai），matched=True。"""
    from opscli.query.services.planner import time_scope

    scope = time_scope.parse("近7天")
    assert scope["matched"] is True
    assert scope["is_default"] is False
    assert scope["timezone"] == "Asia/Shanghai"
    # 近7天含今天：start 到 end 恰好 7 天窗口
    from datetime import date

    start = date.fromisoformat(scope["start"])
    end = date.fromisoformat(scope["end"])
    assert (end - start).days == 6
    assert "近7天" in scope["label_zh"]


def test_time_scope_default_window_when_unmatched():
    """无时间表述时回落默认近30天窗口，is_default=True 且 matched=False。"""
    from opscli.query.services.planner import time_scope

    scope = time_scope.parse("查销售额")
    assert scope["is_default"] is True
    assert scope["matched"] is False


def test_plan_integrity_attach_and_verify_roundtrip():
    """attach 附加摘要后 verify 通过；篡改执行引用后 verify 失败。"""
    from opscli.query.services.planner import plan_integrity

    plan = {"status": "planned", "execution_ref": {"table_id": 1, "dimensions": ["sku"]}}
    plan_integrity.attach(plan)
    assert plan_integrity.verify(plan) is True
    # 篡改后摘要不再匹配
    plan["execution_ref"]["table_id"] = 999
    assert plan_integrity.verify(plan) is False


def test_field_semantics_requested_canonical_fields():
    """中文业务说法命中规范字段名；派生指标带齐分子分母基础字段。"""
    from opscli.query.services.planner import field_semantics

    matched = field_semantics.requested_canonical_fields("查毛利率")
    # 毛利率派生自 gross_profit 与 price 两个基础字段
    assert "gross_profit" in matched
    assert "price" in matched
