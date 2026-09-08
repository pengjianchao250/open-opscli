"""规划器纯逻辑单元 + 静态资源移植测试。

覆盖 Task 1 的三个纯标准库单元（time_scope / plan_integrity / field_semantics）
与两个静态资源（intent_rules.json / query_plan.schema.json）迁入内核后的可用性。

历史说明：Skill 本地规划器移除前，本文件还负责与 Skill 版 data/ 目录下同名静态
资源逐字节对拍；规划器内核唯一后该对拍已无对象，相关用例删除。
"""

import json
from calendar import monthrange
from importlib.resources import files

import pytest


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


def test_sales_team_phrase_is_not_a_sales_person_request():
    from opscli.query.services.planner import field_semantics

    assert field_semantics.sales_person_dimension_requested("按销售小组看销售额") is False


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


def test_time_scope_leading_days_use_recent_window():
    """“前7天”按产品约定等同近7天，不能回落默认 30 天。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse("前7天各部门销量", today=date(2026, 9, 8))
    assert (scope["start"], scope["end"]) == ("2026-09-02", "2026-09-08")
    assert scope["is_default"] is False
    assert scope["label_zh"].startswith("近7天")


@pytest.mark.parametrize(
    ("wording", "expected_start"),
    [
        ("过去7天各部门销量", "2026-09-02"),
        ("过去2周各部门销量", "2026-08-26"),
        ("过去2个月各部门销量", "2026-07-11"),
    ],
)
def test_time_scope_past_windows_are_explicit(wording, expected_start):
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(wording, today=date(2026, 9, 8))
    assert (scope["start"], scope["end"]) == (expected_start, "2026-09-08")
    assert scope["is_default"] is False


@pytest.mark.parametrize("wording", ["2026-08", "2026/08", "2026.08"])
def test_time_scope_numeric_year_month_formats(wording):
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(wording, today=date(2026, 9, 8))
    assert (scope["start"], scope["end"]) == ("2026-08-01", "2026-08-31")
    assert scope["is_default"] is False


@pytest.mark.parametrize(
    "month, abbreviation, number",
    [
        ("January", "Jan", 1),
        ("February", "Feb", 2),
        ("March", "Mar", 3),
        ("April", "Apr", 4),
        ("May", "May", 5),
        ("June", "Jun", 6),
        ("July", "Jul", 7),
        ("August", "Aug", 8),
        ("September", "Sep", 9),
        ("October", "Oct", 10),
        ("November", "Nov", 11),
        ("December", "Dec", 12),
    ],
)
def test_time_scope_english_month_full_and_abbreviated_in_both_orders(
    month: str, abbreviation: str, number: int
) -> None:
    """十二个月全称/缩写及“月 年”“年 月”顺序都解析为自然月。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    expected = (
        f"2026-{number:02d}-01",
        f"2026-{number:02d}-{monthrange(2026, number)[1]:02d}",
    )
    for wording in (
        f"{month} 2026 sales",
        f"{abbreviation} 2026 sales",
        f"2026 {month} sales",
        f"2026 {abbreviation} sales",
    ):
        scope = time_scope.parse(wording, today=date(2026, 9, 8))
        assert (scope["start"], scope["end"]) == expected, wording
        assert scope["is_default"] is False, wording


def test_time_scope_english_month_explicit_comparison():
    """英文自然月同样支持显式主周期与对比周期。"""
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse("August 2026 vs Jul 2026 sales", today=date(2026, 9, 8))
    assert (scope["start"], scope["end"]) == ("2026-08-01", "2026-08-31")
    assert (scope["comparison"]["start"], scope["comparison"]["end"]) == (
        "2026-07-01",
        "2026-07-31",
    )


def test_time_scope_starts_new_clause_after_exclusion():
    """排除条件后的“后看/再看”开启新子句。

    后续自然月不能被否定跨度吞掉。
    """
    from datetime import date

    from opscli.query.services.planner import time_scope

    for query in (
        "排除加拿大后看8月各渠道销量",
        "不要亚马逊VC，再看8月份销售额",
        "去掉加拿大然后看8月各渠道销量",
        "排除加拿大之后查8月销量",
        "忽略加拿大接着统计8月销量",
    ):
        scope = time_scope.parse(query, today=date(2026, 9, 8))
        assert (scope["start"], scope["end"]) == ("2026-08-01", "2026-08-31")
        assert scope["is_default"] is False


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


@pytest.mark.parametrize(
    "wording",
    [
        "查询2026年7月和2026年8月对比",
        "查询2026年7月比2026年8月",
    ],
)
def test_explicit_comparison_supports_common_month_connectors(wording):
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(wording, today=date(2026, 9, 8))
    assert (scope["start"], scope["end"]) == ("2026-07-01", "2026-07-31")
    assert (scope["comparison"]["start"], scope["comparison"]["end"]) == (
        "2026-08-01",
        "2026-08-31",
    )


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("2026Q3环比", ("2026-04-01", "2026-06-30")),
        ("2026Q1环比", ("2025-10-01", "2025-12-31")),
        ("2024年环比", ("2023-01-01", "2023-12-31")),
    ],
)
def test_natural_period_comparison_uses_previous_calendar_period(wording, expected):
    from datetime import date

    from opscli.query.services.planner import time_scope

    scope = time_scope.parse(wording, today=date(2026, 9, 8))
    assert (scope["comparison"]["start"], scope["comparison"]["end"]) == expected


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


def test_exact_authorized_metric_labels_protect_contained_short_aliases():
    """完整指标名中的短别名不构成第二个指标诉求。"""
    from opscli.query.services.planner import field_semantics

    assert field_semantics.requested_canonical_fields(
        "主营业务收入、营业外收入",
        protected_terms=("主营业务收入", "营业外收入"),
    ) == {}
    assert field_semantics.requested_canonical_fields(
        "市场总销量和市场总销售额(原币)",
        protected_terms=("市场总销量", "市场总销售额(原币)"),
    ) == {}


def test_short_alias_outside_exact_metric_label_remains_requested():
    """长标签之外另写的短别名仍是独立诉求。"""
    from opscli.query.services.planner import field_semantics

    assert field_semantics.requested_canonical_fields(
        "主营业务收入和收入",
        protected_terms=("主营业务收入",),
    ) == {"price": "收入"}


def test_field_term_cannot_start_inside_query_action_word():
    """动作词尾部不得与后续文本跨边界拼成字段标签。"""
    from opscli.query.services.planner import field_semantics

    assert not field_semantics.has_standalone_term_occurrence(
        "总周转天数", "汇总周转天数(可售)"
    )
    assert field_semantics.has_standalone_term_occurrence(
        "总周转天数", "汇总总周转天数"
    )


def test_field_semantics_broad_sales_business_terms_select_standard_metrics():
    """“销售情况”是经营指标意图，必须映射标准销售指标而非销售人员。"""
    from opscli.query.services.planner import field_semantics

    for query in ("查询销售情况", "查看销售表现", "分析销售业绩"):
        matched = field_semantics.requested_canonical_fields(query)
        assert {"price", "order_qty", "orders"}.issubset(matched)


def test_field_semantics_broad_sales_conversational_terms_select_standard_metrics():
    """短口语经营问法也应映射销售指标，而不是销售人员维度。"""
    from opscli.query.services.planner import field_semantics

    for query in ("这个月销售怎么样", "销售如何", "销售好不好"):
        assert field_semantics.has_broad_sales_metric_intent(query)
        matched = field_semantics.requested_canonical_fields(query)
        assert {"price", "order_qty", "orders"}.issubset(matched)
        assert not field_semantics.sales_person_dimension_requested(query)


def test_field_semantics_sales_dataset_name_is_not_broad_metric_intent():
    """数据集名称中的“销售数据集”只用于选表，不得凭子串追加销售指标组。"""
    from opscli.query.services.planner import field_semantics

    assert not field_semantics.has_broad_sales_metric_intent("使用即时销售数据集")


def test_field_semantics_distinguishes_sales_person_dimension_context():
    """只有明确人员/分组/筛选表达时，“销售”才表示销售人员维度。"""
    from opscli.query.services.planner import field_semantics

    assert not field_semantics.sales_person_dimension_requested("各部门的销售情况")
    assert field_semantics.sales_person_dimension_requested("按销售人员汇总销售情况")
    assert field_semantics.sales_person_dimension_requested("销售是张三，查询销售情况")
