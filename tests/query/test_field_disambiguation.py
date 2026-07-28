"""query_simple 同名双注册字段消歧（与规划器口径对齐）。

e2e 验收发现：数据集存在同一物理字段的英中双名 / 公式vs裸指标同名双注册，
后端按 field_name 稳定解析（形态二命中公式口径），但 query_simple 的
_resolve_simple_field 曾一律报歧义并建议改用 global_alias——而后端不接受
global_alias，导致这些字段无法查询。修复后与规划器 _merge_duplicate_field_rows
口径一致地消歧。
"""

import pytest

from opscli.query.services.manager import QueryManager
from opscli.query.domain.exceptions import InvalidPayloadError


def _mgr():
    return QueryManager()


def _dim(name, ga, verbose):
    return {"field_name": name, "global_alias": ga, "verbose_name": verbose,
            "field_type": "dimension", "snapshot_metric": None,
            "has_formula_config": 0, "summary_expression": None, "detail_expression": None}


def _metric(name, ga, formula=0, summary=None):
    return {"field_name": name, "global_alias": ga, "verbose_name": name,
            "field_type": "metric", "snapshot_metric": None,
            "has_formula_config": formula, "summary_expression": summary, "detail_expression": None}


def test_form1_english_chinese_double_name_resolves():
    """形态一：同名维度英中双名（执行等价）→ 任取其一，不报歧义。"""
    fields = [
        _dim("development_type", "f_en", "development_type"),
        _dim("development_type", "f_zh", "开发类型"),
    ]
    r = _mgr()._resolve_simple_field(fields, "development_type", field_type="dimension", context="dimension")
    assert r["field_name"] == "development_type"


def test_form2_formula_vs_plain_prefers_formula():
    """形态二：公式 vs 裸指标同名 → 采纳公式注册（正确聚合口径）。"""
    fields = [
        _metric("avg_price_cny", "f_plain", formula=0, summary=None),
        _metric("avg_price_cny", "f_formula", formula=1, summary="ROUND(SUM(price)/SUM(order_qty),4)"),
    ]
    r = _mgr()._resolve_simple_field(fields, "avg_price_cny", field_type="metric", context="metric")
    assert str(r.get("has_formula_config")) == "1"
    assert r["global_alias"] == "f_formula"


def test_genuine_multi_formula_conflict_still_raises():
    """真口径冲突：同名多个不同公式表达式 → 仍报歧义。"""
    fields = [
        _metric("x", "f_a", formula=1, summary="SUM(a)/SUM(b)"),
        _metric("x", "f_b", formula=1, summary="SUM(c)/SUM(d)"),
    ]
    with pytest.raises(InvalidPayloadError):
        _mgr()._resolve_simple_field(fields, "x", field_type="metric", context="metric")


def test_ambiguity_message_no_longer_recommends_global_alias():
    """歧义提示不再误导用户改用 global_alias（后端不接受 global_alias）。"""
    fields = [
        _metric("x", "f_a", formula=1, summary="SUM(a)/SUM(b)"),
        _metric("x", "f_b", formula=1, summary="SUM(c)/SUM(d)"),
    ]
    with pytest.raises(InvalidPayloadError) as ei:
        _mgr()._resolve_simple_field(fields, "x", field_type="metric", context="metric")
    assert "请改用唯一的 global_alias" not in str(ei.value)


def test_unique_field_name_still_resolves():
    """唯一 field_name 正常解析（无回归）。"""
    fields = [_dim("sell_sku", "f_1", "渠道SKU"), _metric("star", "f_2")]
    assert _mgr()._resolve_simple_field(fields, "sell_sku", field_type="dimension", context="d")["field_name"] == "sell_sku"
    assert _mgr()._resolve_simple_field(fields, "star", field_type="metric", context="m")["field_name"] == "star"
