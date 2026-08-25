"""规划器纯逻辑单元 + 静态资源移植测试。

覆盖 Task 1 的三个纯标准库单元（time_scope / plan_integrity / field_semantics）
与两个静态资源（intent_rules.json / query_plan.schema.json）迁入内核后的可用性。
断言字段对照 scripts/ 下原脚本的真实返回结构补齐。
"""

import json
from importlib.resources import files
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DATA = REPO_ROOT / "opscli/skills/templates/ops-dataset-query/data"


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


def test_skill_and_kernel_static_planning_resources_are_identical():
    """双主线共享的意图规则和合同 Schema 必须逐字段一致，防止再次单边演进。"""
    kernel_resources = files("opscli.query.services.planner.resources")
    for name in ("intent_rules.json", "query_plan.schema.json"):
        skill_data = json.loads((SKILL_DATA / name).read_text("utf-8"))
        kernel_data = json.loads((kernel_resources / name).read_text("utf-8"))
        assert kernel_data == skill_data, f"双主线静态资源漂移：{name}"


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


def test_time_scope_age_threshold_does_not_shadow_today():
    """库龄“超6月”不是自然月；后文“当天”才是本次查询时间口径。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(
        "超6月采购金额按181天以上库龄计算，当天查询销售",
        today=date(2026, 7, 30),
    )
    assert (scope["start"], scope["end"]) == ("2026-07-30", "2026-07-30")
    assert scope["label_zh"] == "今天"


# ── 显式对比周期不得与主周期重合（生产环比失真）────────────────────────────
#
# "对比A与B" 结构里对比线索词位于主周期之前，_explicit_comparison 从线索词之后
# 取第一个日期区间时会取到主周期自身，导致对比期 == 主周期、环比恒为 0 且不报错
# （静默出错数）。对比期必须跳过与主周期重合的区间，取下一个候选。


def test_explicit_comparison_skips_primary_window_absolute():
    """对比线索词在主周期之前时，绝对区间对比期须取到第二个区间。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(
        "项目二部，按ASIN对比6月(2026-06-01~2026-06-30)与5月(2026-05-01~2026-05-31)的销量变化",
        today=date(2026, 7, 26),
    )
    assert (scope["start"], scope["end"]) == ("2026-06-01", "2026-06-30")
    comparison = scope["comparison"]
    assert comparison is not None
    assert (comparison["start"], comparison["end"]) == ("2026-05-01", "2026-05-31")
    # 对比期与主周期重合即为失真，必须显式拒绝
    assert (comparison["start"], comparison["end"]) != (scope["start"], scope["end"])


def test_explicit_comparison_skips_primary_window_natural_month():
    """自然月写法下同样跳过主周期月份，取真正的对比月。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse("对比6月与5月的销量", today=date(2026, 7, 26))
    assert (scope["start"], scope["end"]) == ("2026-06-01", "2026-06-30")
    comparison = scope["comparison"]
    assert comparison is not None
    assert (comparison["start"], comparison["end"]) == ("2026-05-01", "2026-05-31")


def test_explicit_comparison_keeps_existing_trailing_forms():
    """线索词在主周期之后的既有写法不得因本次修复改变结论。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    trailing = time_scope.parse(
        "查询2026-06-25至2026-07-24的销售额，对比2026-05-26至2026-06-24",
        today=date(2026, 7, 26),
    )
    assert (trailing["start"], trailing["end"]) == ("2026-06-25", "2026-07-24")
    assert (trailing["comparison"]["start"], trailing["comparison"]["end"]) == (
        "2026-05-26",
        "2026-06-24",
    )

    month_form = time_scope.parse("查询2026年6月与2026年5月的销售额对比", today=date(2026, 7, 26))
    assert (month_form["start"], month_form["end"]) == ("2026-06-01", "2026-06-30")
    assert (month_form["comparison"]["start"], month_form["comparison"]["end"]) == (
        "2026-05-01",
        "2026-05-31",
    )


def test_explicit_comparison_absent_when_only_primary_window_present():
    """句中只有主周期一个区间时不得伪造对比期（无第二区间可用）。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(
        "对比查询2026-06-01~2026-06-30的销量", today=date(2026, 7, 26)
    )
    assert (scope["start"], scope["end"]) == ("2026-06-01", "2026-06-30")
    comparison = scope["comparison"] or {}
    assert (comparison.get("start"), comparison.get("end")) != (
        scope["start"],
        scope["end"],
    )


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
