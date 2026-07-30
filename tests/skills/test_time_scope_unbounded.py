"""全时段（不加日期筛选）与否定语境的回归测试。

覆盖三条行为，Skill 版与内核版必须完全一致：
1. 用户明确要求全时段（历史以来/所有时间/不限时间）→ 空窗口，不注入日期筛选；
2. 否定语境里的时间口径不得被当成显式请求（「拒绝默认近30天」曾被识别成要近30天）；
3. 只查维度不查指标时，原文未给时间口径也不加日期筛选（去重维度全集不该被卡 30 天）。

第 3 条依赖组件筛选值解析（_resolve_component_filters）兜底：跳过时间确认门后，
带筛选值的请求由「锁定 / 澄清 / 阻断」三态保证不会执行未带筛选的模板。
"""

from __future__ import annotations

import json
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
import time_scope as skill_time_scope  # noqa: E402

from opscli.query.services.planner import time_scope as kernel_time_scope  # noqa: E402

RULES_PATH = SKILL_ROOT / "data" / "intent_rules.json"

# 两版规划器同源，任何时间口径行为都必须逐条对齐
BOTH_VERSIONS = pytest.mark.parametrize(
    "module",
    [skill_time_scope, kernel_time_scope],
    ids=["skill", "kernel"],
)


@BOTH_VERSIONS
@pytest.mark.parametrize(
    "query",
    [
        "查询历史以来全部数据",
        "查所有时间的数据",
        "不限时间，全部ASIN",
        "不添加任何日期或时间筛选",
        "全时段的渠道明细",
    ],
)
def test_all_time_phrases_return_unbounded_window(module, query: str):
    """明确要求全时段时返回空窗口，且不算默认口径（不该再追问时间）。"""
    scope = module.parse(query)
    assert scope["unbounded"] is True
    assert scope["start"] is None and scope["end"] is None
    assert scope["is_default"] is False


@BOTH_VERSIONS
def test_negated_time_phrase_is_not_treated_as_explicit(module):
    """「拒绝默认近30天」不能被当成用户显式要求近30天。

    这是线上实际踩过的坑：用户越强调不要近30天，越会因为句中出现「近30天」
    被识别为显式口径，连确认都不弹就按 30 天执行。
    """
    scope = module.parse("用户已明确拒绝默认近30天")
    assert scope["is_default"] is True, "否定语境应回落默认口径并触发确认"
    assert scope["unbounded"] is False


@BOTH_VERSIONS
def test_negation_masking_stops_at_punctuation(module):
    """否定屏蔽只作用到最近的标点，后半句的真实时间表述仍要生效。"""
    scope = module.parse("不要近30天，查上月")
    assert scope["label_zh"].startswith("上月")
    assert scope["is_default"] is False
    assert scope["unbounded"] is False


@BOTH_VERSIONS
def test_generic_all_wording_is_not_all_time(module):
    """「全部ASIN」是维度泛指，不能被误判成不限时间。"""
    scope = module.parse("查傲彼瑞的全部ASIN")
    assert scope["unbounded"] is False
    assert scope["is_default"] is True


@BOTH_VERSIONS
@pytest.mark.parametrize(
    "query, expected_prefix",
    [
        ("近7天的销量", "近7天"),
        ("本月的销量", "本月"),
        ("2026-07-01 至 2026-07-15 的数据", "明确日期范围"),
    ],
)
def test_explicit_windows_are_unaffected(module, query: str, expected_prefix: str):
    """显式时间口径不受本次改动影响。"""
    scope = module.parse(query)
    assert scope["unbounded"] is False
    assert scope["start"] is not None
    assert scope["label_zh"].startswith(expected_prefix)


@BOTH_VERSIONS
@pytest.mark.parametrize("query", ["历史以来的数据，环比", "所有时间的数据，同比"])
def test_unbounded_window_has_no_comparison(module, query: str):
    """空窗口没有对比基准，不能凭空造出环比/同比周期。"""
    assert module.parse(query)["comparison"] is None


def _write_dimension_only_metadata(data_dir: Path) -> None:
    """写入一套 ready 元数据：渠道、ASIN 两个维度 + 一个销量指标。"""
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.2.3", "data_state": "ready"}),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,SP广告数据集,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "1,ds_ads,广告数据集,date_id,日期,f_date_id,dimension,,,,,0,0\n"
        "1,ds_ads,广告数据集,asin,ASIN,f_asin,dimension,,,,,0,0\n"
        "1,ds_ads,广告数据集,sales,销量,f_sales,metric,,,,,0,0\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_ads,platform_name,平台,ds_ads\n",
        encoding="utf-8",
    )


def _date_filters(result: dict) -> list:
    """取出执行模板里的日期筛选条件。"""
    template = (result.get("execution_ref") or {}).get("query_template") or {}
    return [
        item
        for item in template.get("filters") or []
        if "date" in str(item.get("field"))
    ]


def test_dimension_only_query_without_time_is_unbounded(tmp_path: Path):
    """只查维度不查指标时不加日期筛选，也不再就时间口径追问。

    这类请求要的是去重维度全集（如某渠道下全部 ASIN），
    卡近 30 天只会漏掉更早出现过的值。
    """
    data_dir = tmp_path / "data"
    _write_dimension_only_metadata(data_dir)

    result = skill_query_plan.build_model_query_plan(
        "广告数据集 ASIN",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "planned"
    assert result["execution_ref"]["time_scope"]["unbounded"] is True
    assert _date_filters(result) == []
    assert "不加日期筛选" in result["model_view"]["time_scope_zh"]


def test_metric_query_without_time_still_confirms_default_window(tmp_path: Path):
    """带指标且未给时间口径时，仍保留默认近30天 + 用户确认门。"""
    data_dir = tmp_path / "data"
    _write_dimension_only_metadata(data_dir)

    result = skill_query_plan.build_model_query_plan(
        "广告数据集 ASIN 销量",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "clarify_required"
    assert "time_scope_confirmation" in result["model_view"]["clarification_reason_codes"]
