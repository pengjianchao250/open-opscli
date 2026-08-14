"""排序与行数（Top N）意图必须由规划期解析进模板的回归测试。

守住的核心行为：用户说过的排序和行数，要么落进 query_template，要么被强制披露；
绝不允许静默丢弃。

事故形态：`query_template` 的 orderBy/limit 曾恒为 None，而 SKILL.md 规定 Agent
不得改写模板、plan_integrity 又把模板哈希绑死——三条规则叠加的结果是「取前10名」
在自然语言主线上结构性不可能实现。端到端表现为用户要前 10 名、拿回全量 193 行按
主键自然序，且 truncated=false，没有任何一处提示 Top N 没生效（矩阵实测 0/384）。

Skill 版与内核版同源，但 orderBy 形态不同（Skill 用 {field,direction}，
内核用 {field,desc} 布尔），由 _direction_of 适配后统一断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_plan as skill_query_plan  # noqa: E402

from opscli.query.services.planner import query_plan as kernel_query_plan  # noqa: E402

MODULES = {"skill": skill_query_plan, "kernel": kernel_query_plan}


def _fields(*labels: str) -> list[dict]:
    """构造 execution_ref 形态的字段列表（field_name + label_zh）。"""
    return [
        {"field_name": f"f_{index}", "label_zh": label}
        for index, label in enumerate(labels)
    ]


def _direction_of(entry: dict) -> str:
    """把两版不同的 orderBy 形态归一为 DESC/ASC。"""
    if "direction" in entry:
        return str(entry["direction"])
    return "DESC" if entry.get("desc") else "ASC"


@pytest.fixture(params=sorted(MODULES))
def planner(request):
    return MODULES[request.param]


# ── 能解析出来的必须落进模板 ──────────────────────────────────────────────


def test_top_n_with_single_metric_resolves(planner):
    """「取前10名」+ 唯一指标 → 按该指标降序取 10 行（Top N 的常识语义）。"""
    order_by, limit, unresolved = planner._resolve_order_and_limit(
        "按渠道SKU统计发货数据集近7天的销售额，取前10名",
        _fields("渠道SKU"),
        _fields("销售额"),
    )
    assert limit == 10
    assert unresolved == ""
    assert order_by and order_by[0]["field"] == "f_0"
    assert _direction_of(order_by[0]) == "DESC"


def test_explicit_field_and_direction_resolve(planner):
    """「按X降序排列，只要前5行」→ 显式字段与方向都要生效。"""
    order_by, limit, unresolved = planner._resolve_order_and_limit(
        "发货数据集近7天按销售额降序排列，只要前5行，维度用渠道SKU",
        _fields("渠道SKU"),
        _fields("销售额", "退款金额"),
    )
    assert limit == 5
    assert unresolved == ""
    assert order_by and order_by[0]["field"] == "f_0"
    assert _direction_of(order_by[0]) == "DESC"


def test_ascending_wording_flips_direction(planner):
    """升序词优先于 Top N 的默认降序。"""
    order_by, _limit, _unresolved = planner._resolve_order_and_limit(
        "发货数据集近7天按销售额升序排列，前5名", _fields(), _fields("销售额")
    )
    assert order_by and _direction_of(order_by[0]) == "ASC"


def test_order_without_limit_still_applies(planner):
    """只说排序不说行数时，排序仍要下发，limit 保持不填。"""
    order_by, limit, unresolved = planner._resolve_order_and_limit(
        "发货数据集近7天的销售额，按销售额从高到低排列", _fields(), _fields("销售额")
    )
    assert order_by and _direction_of(order_by[0]) == "DESC"
    assert limit is None
    assert unresolved == ""


# ── 解析不出来时不得静默放行 ──────────────────────────────────────────────


def test_ambiguous_metric_refuses_silently_applying_limit(planner):
    """多指标又没点名排序字段时，不下发排序与行数，改为强制披露。

    此处必须同时不下发 limit：一个没排过序的 LIMIT 10 比不加 limit 更危险，
    用户会把任意 10 行当成 Top 10。
    """
    order_by, limit, unresolved = planner._resolve_order_and_limit(
        "发货数据集近7天的销售额和退款金额，取前10名",
        _fields(),
        _fields("销售额", "退款金额"),
    )
    assert order_by is None
    assert limit is None
    assert "未应用排序与行数限制" in unresolved


# ── 不能把时间表述误读成行数 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "查询发货数据集近7天的销售额",
        "查询发货数据集前7天的销售额",
        "查询发货数据集近30天的销售额",
        "查询发货数据集本月的销售额",
    ],
)
def test_time_expressions_are_not_row_limits(planner, query: str):
    """「前7天/近30天」是时间口径，绝不能被当成 limit。"""
    order_by, limit, unresolved = planner._resolve_order_and_limit(
        query, _fields(), _fields("销售额")
    )
    assert limit is None, f"时间表述被误读成行数：{query!r}"
    assert order_by is None
    assert unresolved == ""


def test_groupby_wording_is_not_a_sort_field(planner):
    """「按X统计」是分组维度，不构成排序诉求，不得凭空产出 orderBy。"""
    order_by, limit, unresolved = planner._resolve_order_and_limit(
        "按渠道SKU统计发货数据集近7天的销售额", _fields("渠道SKU"), _fields("销售额")
    )
    assert order_by is None and limit is None and unresolved == ""


# ── 端到端：合同层必须把解析结果写进模板 ──────────────────────────────────


def test_contract_template_carries_order_and_limit():
    """Skill 合同层：planned 模板必须带上解析出的 orderBy 与 limit。"""
    contract = skill_query_plan.build_model_query_plan(
        "按渠道SKU统计发货数据集近7天的销售额，取前10名"
    )
    if contract.get("status") != "planned":
        pytest.skip("本地元数据不满足该用例的选表条件")
    template = contract["execution_ref"]["query_template"]
    assert template["limit"] == 10
    assert template["orderBy"] and template["orderBy"][0]["direction"] == "DESC"


def test_contract_discloses_unresolved_order():
    """Skill 合同层：解析不出排序字段时必须写入强制披露。"""
    contract = skill_query_plan.build_model_query_plan(
        "发货数据集近7天的销售额和退款金额，取前10名"
    )
    if contract.get("status") != "planned":
        pytest.skip("本地元数据不满足该用例的选表条件")
    disclosures = contract["answer_contract"]["required_disclosures_zh"]
    assert any("未应用排序与行数限制" in item for item in disclosures), disclosures


# ── 证据合同必须带数据集中文名（F9）──────────────────────────────────────
#
# 结果分析的第一条要求就是「先说明数据集中文名」，但 evidence_contract 的
# _dataset_name 是到查询返回体里找 dataset* 键，而 opscli 的返回结构里根本没有这类键，
# 于是 dataset_name_zh 恒为空串——Agent 无法从结果侧独立核验本次到底查了哪张表
# （codex 端到端在 33 条反馈里重复提到这一点）。

import evidence_contract  # noqa: E402


def _query_response() -> dict:
    """一次典型的 opscli 查询返回（不含任何 dataset* 键）。"""
    return {
        "success": True,
        "data": {
            "payload": {"tableId": "2", "filters": []},
            "result": {"data": [{"price": "1.0"}], "meta": {"currency": "CNY"}},
        },
    }


def test_evidence_contract_uses_planned_dataset_name():
    """规划合同给出中文名时必须原样带入证据合同。"""
    contract = evidence_contract.build_evidence_contract(
        _query_response(), dataset_name_zh="发货数据集"
    )
    assert contract["dataset_name_zh"] == "发货数据集"


def test_evidence_contract_name_is_empty_without_plan_hint():
    """不传时才回落到旧的返回体扫描（旁路直连场景），从而暴露原缺陷形态。"""
    contract = evidence_contract.build_evidence_contract(_query_response())
    assert contract["dataset_name_zh"] == ""
