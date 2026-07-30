"""路由质量三层评测：数据集正确性、字段严格召回、可执行性。

为什么拆三层：研究结论（EDBT'26、AutoLink）是「漏一个必需字段就必然失败」，
而端到端成功率会把选表错误与字段漏选混在一起，改动无法归因。本文件补的是
「字段严格召回」这一层——数据集是否选对已由 test_local_fallback.py 的
21 条历史用例单独回归。

字段级测试隔离说明：
    每条用例的 data_dir 只放入其 expected_dataset 对应的单一数据集卡片
    （见 _write_isolated_dataset），不引入其余数据集造成路由竞争噪声，
    使本层只衡量「给定正确数据集后，字段是否被规划器召回」，与数据集
    选择正确性解耦。字段中文名（verbose_name）及数据集 description/remarks
    均取自当前生产环境真实元数据，已于 2026-07-30 通过
    ~/.claude/skills/ops-dataset-query/data/dataset_fields.csv 逐条核对
    存在性（核对方法：按 table_id 过滤后核对 verbose_name 是否出现）；
    field_name/global_alias/dataset_alias/table_id 为测试合成标识，不代表
    真实后端标识。

基线记录（2026-07-30 首次运行，Step 3）：
    FIELD_CASES 共 4 条（case_018 因所属数据集 物控版库存周转
    在当前生产 dataset_fields.csv 中查无字段——画像已与后端不同步，
    expected_fields 留空，未进入本层测试，见 routing_eval_cases.json 的 note）。
    首轮结果：1 passed（case_014），3 failed（case_001 / case_004 / case_020）。
    3 条失败逐一核实为真实规划器行为（非 data_dir 未就绪等基础设施问题），
    已标记 strict xfail，成因见 FIELD_RECALL_GAPS。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = (
    Path(__file__).parents[2] / "opscli" / "skills" / "templates" / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_plan as skill_query_plan  # noqa: E402

EVAL_CASES = json.loads(
    (Path(__file__).parent / "data" / "routing_eval_cases.json").read_text(encoding="utf-8")
)["cases"]

FIELD_CASES = [case for case in EVAL_CASES if case.get("expected_fields")]

# 每条严格召回用例对应数据集的最小可运行字段清单：(verbose_name, field_type)。
# 取值均为该数据集在生产环境 default_dimensions/default_metrics 画像中、
# 且已核对在当前生产 dataset_fields.csv 中真实存在的字段（不存在的画像字段
# 已剔除，例如广告费数据集画像里的"小组"、流量转化率数据集画像里的"SKU"
# 在当前后端已不存在，属于另一条已知的画像腐烂问题，不在本任务处理范围）。
_FIELD_RECALL_DATASETS: dict[str, dict] = {
    "case_001": {
        "description": "即时综合数据集",
        "remarks": "整合销售、广告、流量、库存核心指标，可高效进行日常经营数据分析。",
        "fields": [
            ("日期", "dimension"), ("部门", "dimension"), ("大组", "dimension"),
            ("销售小组", "dimension"), ("销售", "dimension"), ("开发", "dimension"),
            ("平台", "dimension"), ("国家", "dimension"), ("渠道", "dimension"),
            ("ASIN", "dimension"), ("公司SKU", "dimension"), ("渠道SKU", "dimension"),
            ("SPU", "dimension"),
            ("销售额", "metric"), ("销量", "metric"), ("订单数", "metric"),
            ("毛利", "metric"), ("毛利率", "metric"), ("广告费", "metric"),
            ("广告销售额", "metric"), ("ACOS", "metric"), ("点击量", "metric"),
            ("曝光量", "metric"), ("平均CPC", "metric"), ("流量", "metric"),
            ("转化率", "metric"), ("总库存", "metric"),
        ],
    },
    "case_004": {
        "description": "广告费数据集",
        "remarks": "用于汇总和分析不同平台的广告支出，支持按平台、渠道、产品等维度查看费用结构。",
        "fields": [
            ("日期", "dimension"), ("平台", "dimension"), ("国家", "dimension"),
            ("渠道", "dimension"), ("部门", "dimension"), ("销售", "dimension"),
            ("开发", "dimension"), ("ASIN", "dimension"), ("公司SKU", "dimension"),
            ("渠道SKU", "dimension"),
            ("广告费", "metric"), ("广告销售额", "metric"), ("广告销量", "metric"),
            ("点击量", "metric"), ("曝光量", "metric"), ("ACOS", "metric"),
            ("点击率", "metric"), ("平均CPC", "metric"), ("CPC转化率", "metric"),
            ("总销售额", "metric"), ("总销量", "metric"),
        ],
    },
    "case_014": {
        "description": "流量转化率数据集",
        "remarks": "分析流量转化漏斗、转化率表现。",
        "fields": [
            ("日期", "dimension"), ("国家", "dimension"), ("平台", "dimension"),
            ("ASIN", "dimension"), ("渠道", "dimension"), ("部门", "dimension"),
            ("销售额", "metric"), ("销量", "metric"), ("流量", "metric"),
            ("浏览量", "metric"), ("转化率", "metric"),
        ],
    },
    "case_020": {
        "description": "活动数据集",
        "remarks": "用于分析亚马逊SC促销活动期间的销售、流量及推广表现，支持活动效果评估与复盘。",
        "fields": [
            ("活动ID", "dimension"), ("活动标题", "dimension"), ("活动状态", "dimension"),
            ("活动类型", "dimension"), ("促销类型", "dimension"), ("平台", "dimension"),
            ("国家", "dimension"), ("渠道", "dimension"), ("部门", "dimension"),
            ("ASIN", "dimension"),
            ("秒杀数量", "metric"), ("售出量", "metric"), ("浏览量", "metric"),
        ],
    },
}

# 仍失败用例的成因（strict xfail，逐条实测得出，禁止凭猜）。
FIELD_RECALL_GAPS = {
    "case_001": (
        "用户原文「销售广告库存流量一起看」未使用与字段中文名完全一致的写法，"
        "规划器按逐字子串匹配无法召回「销售额/广告费/总库存」；"
        "且「销售」误命中同数据集下的销售负责人维度字段（而非销售额指标），"
        "实测只选中 流量、销售 两个字段，漏选 销售额/广告费/总库存。"
    ),
    "case_004": (
        "「ACOS」未登记在 intent_rules.json 的全局 metric_terms 词表中，"
        "且「各平台」未命中具体平台槽位取值，触发 agent_query_planner.plan_query "
        "中 has_metric=False 且 domains<=1 的早停规则，规划器直接返回 "
        "business_scope 澄清、不产出任何候选数据集，实测 0 个字段被选中。"
    ),
    "case_020": (
        "用户原文只写「活动」未出现「类型」二字，规划器逐字子串匹配未命中"
        "「活动类型」维度字段；数据集本身选对（活动数据集），「售出量」正确"
        "命中，实测只漏「活动类型」一个字段。"
    ),
}


def _write_isolated_dataset(
    data_dir: Path, fields: list[tuple[str, str]], description: str, remarks: str
) -> None:
    """写入只含单一数据集的 ready 元数据。

    为什么只放一个数据集：本层测试的目标是「给定正确数据集后字段是否被
    召回」，数据集选对与否是另一条独立指标（见 test_local_fallback.py 的
    21 条历史路由用例），混在一起会让两种失败原因无法归因。
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps(
            {"name": "ops-dataset-query", "version": "v-field-recall-eval", "data_state": "ready"}
        ),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        f"1,ds_field_recall_eval,field_recall_eval_set,normal,0,{description},{remarks}\n",
        encoding="utf-8",
    )
    field_lines = "\n".join(
        f"1,ds_field_recall_eval,field_recall_eval_set,f{i},{verbose_name},"
        f"f_alias_{i},{field_type},,,,,0,0,"
        for i, (verbose_name, field_type) in enumerate(fields)
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config,"
        "filter_config\n" + field_lines + "\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n",
        encoding="utf-8",
    )


def _field_case_params() -> list:
    params = []
    for case in FIELD_CASES:
        marks = []
        if case["id"] in FIELD_RECALL_GAPS:
            marks.append(pytest.mark.xfail(reason=FIELD_RECALL_GAPS[case["id"]], strict=True))
        params.append(pytest.param(case, marks=marks, id=case["id"]))
    return params


@pytest.mark.parametrize("case", _field_case_params())
def test_strict_field_recall(case: dict, tmp_path: Path):
    """严格召回：期望字段必须全部出现在规划结果里，漏一个即失败。"""
    fixture = _FIELD_RECALL_DATASETS[case["id"]]
    data_dir = tmp_path / "data"
    _write_isolated_dataset(data_dir, fixture["fields"], fixture["description"], fixture["remarks"])

    result = skill_query_plan.build_model_query_plan(
        case["user_query"], auto_upgrade=False, auto_enum=False, data_dir=data_dir
    )
    view = result.get("model_view") or {}
    selected = set(view.get("dimensions") or []) | set(view.get("metrics") or [])
    missing = [name for name in case["expected_fields"] if name not in selected]
    assert not missing, f"{case['id']} 漏选字段 {missing}，实际选中 {sorted(selected)}"
