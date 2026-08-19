"""K4: 金样对照回归 —— 内核 flow（run_plan/run_flow）与 skill 主线（query_plan/run_query）对照。

背景：K1-K3 把 skill `opscli/skills/templates/ops-dataset-query/scripts/` 的选表/规划/
执行/证据合同逐条搬进内核 `opscli.query.services.planner`，每条迁移点都在各自任务里做了
单元级验证，但从未有一份端到端测试用同一份元数据、同一句用户原文，同时喂给两条主线，
核对最终产出的合同关键字段是否一致——本文件补上这道回归，防止"单元测试各自绿、组合起来
有落差"的搬家事故。

对照范围（严格对齐 task-K4-brief.md 的 Interfaces 定义）：
- 选表 table_id；query_template 的 dimensions/metrics/filters 集合；status；澄清消息键集
- 执行段（result_disclosures/evidence_contract）键集

对照方法：`_write_and_build` 用同一份 Python 字面量规格，同时物化 skill 侧需要的
data_dir CSV 三件套（datasets.csv/dataset_fields.csv/dataset_select_columns.csv +
VERSION.json）与 kernel 侧 `MetadataAdapter` 需要的 payload dict，从根上保证两侧输入
等价（不是分别手写两份、靠人工誊抄对齐）。

白名单机制：架构性差异（数据来源、执行通道形状不同导致的字段/取值差异）逐条列出裁决
依据；白名单外任何差异都会让断言失败。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_ROOT = (
    Path(__file__).parents[3]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import evidence_contract as skill_evidence_contract  # noqa: E402
import query_plan as skill_query_plan  # noqa: E402
import run_query as skill_run_query  # noqa: E402

from opscli.query.services.planner import entry as kernel_entry  # noqa: E402
from opscli.query.services.planner import evidence_contract as kernel_evidence_contract  # noqa: E402
from opscli.query.services.planner import query_plan as kernel_query_plan  # noqa: E402
from opscli.query.services.planner.metadata_adapter import MetadataAdapter  # noqa: E402

RULES_PATH = SKILL_ROOT / "data" / "intent_rules.json"


# ---------------------------------------------------------------------------
# 共享元数据构造：单一 Python 数据源同时派生 skill CSV 与 kernel payload dict
# ---------------------------------------------------------------------------


_DATASET_COLUMNS = (
    "table_id", "dataset_alias", "dataset_name", "dataset_category",
    "inner_where_enabled", "description", "remarks",
)
_FIELD_COLUMNS = (
    "table_id", "dataset_alias", "dataset_name", "field_name", "verbose_name",
    "global_alias", "field_type", "summary_expression", "detail_expression",
    "description", "remarks", "snapshot_metric", "has_formula_config",
)
_SELECT_COLUMN_COLUMNS = (
    "current_dataset_alias", "column_name", "verbose_name", "component_dataset_alias",
)


def _write_and_build(
    data_dir: Path,
    datasets: list[dict],
    fields: list[dict],
    select_columns: list[dict] = (),
) -> dict:
    """从同一份规格同时物化 skill 侧 CSV 三件套与 kernel 侧 payload dict。

    保证「输入等价」（K4 brief 前提）：两侧读的是同一批 Python 字面量，不是分别
    手写两份数据后靠人工誊抄对齐，避免因誊抄疏漏制造虚假的行为分歧。
    """
    select_columns = list(select_columns)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.0.0", "data_state": "ready"}),
        encoding="utf-8",
    )

    ds_lines = [",".join(_DATASET_COLUMNS)]
    for row in datasets:
        ds_lines.append(",".join(str(row.get(col, "")) for col in _DATASET_COLUMNS))
    (data_dir / "datasets.csv").write_text("\n".join(ds_lines) + "\n", encoding="utf-8")

    f_lines = [",".join(_FIELD_COLUMNS)]
    for row in fields:
        f_lines.append(",".join(str(row.get(col, "")) for col in _FIELD_COLUMNS))
    (data_dir / "dataset_fields.csv").write_text("\n".join(f_lines) + "\n", encoding="utf-8")

    sc_lines = [",".join(_SELECT_COLUMN_COLUMNS)]
    for row in select_columns:
        sc_lines.append(",".join(str(row.get(col, "")) for col in _SELECT_COLUMN_COLUMNS))
    (data_dir / "dataset_select_columns.csv").write_text(
        "\n".join(sc_lines) + "\n", encoding="utf-8"
    )

    select_by_alias: dict[str, list[dict]] = {}
    for row in select_columns:
        select_by_alias.setdefault(row["current_dataset_alias"], []).append(
            {
                "column_name": row["column_name"],
                "verbose_name": row.get("verbose_name", ""),
                "component_dataset_alias": row["component_dataset_alias"],
            }
        )
    payload_datasets = [
        {
            "table_id": row["table_id"],
            "dataset_alias": row["dataset_alias"],
            "dataset_name": row["dataset_name"],
            "dataset_category": row["dataset_category"],
            "inner_where_enabled": row.get("inner_where_enabled", 0),
            "description": row.get("description", ""),
            "remarks": row.get("remarks", ""),
            "select_columns": select_by_alias.get(row["dataset_alias"], []),
        }
        for row in datasets
    ]
    payload_fields = [{col: row.get(col, "") for col in _FIELD_COLUMNS} for row in fields]
    return {"datasets": payload_datasets, "fields": payload_fields}


# ── 场景 1-3/5 共用元数据：SP 广告数据集 + 库存数据集（对齐 tests/skills 既有
#    _write_ready_metadata 的字段口径，query 短语沿用同一批已验证可用的自然语言）──

_BASE_DATASETS = [
    {
        "table_id": 1, "dataset_alias": "ds_ads", "dataset_name": "广告数据集",
        "dataset_category": "normal", "inner_where_enabled": 0, "description": "SP广告数据集",
    },
    {
        "table_id": 2, "dataset_alias": "ds_inv", "dataset_name": "库存数据集",
        "dataset_category": "normal", "inner_where_enabled": 0, "description": "库存快照数据集",
    },
]
_BASE_FIELDS = [
    {
        "table_id": 1, "dataset_alias": "ds_ads", "dataset_name": "广告数据集",
        "field_name": "date_id", "verbose_name": "日期", "global_alias": "f_date_id",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 1, "dataset_alias": "ds_ads", "dataset_name": "广告数据集",
        "field_name": "sku", "verbose_name": "SKU", "global_alias": "f_sku",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 1, "dataset_alias": "ds_ads", "dataset_name": "广告数据集",
        "field_name": "acos", "verbose_name": "ACOS", "global_alias": "f_acos",
        "field_type": "metric", "summary_expression": "ads_cost / sales",
        "description": "广告成本销售比", "snapshot_metric": 0, "has_formula_config": 1,
    },
    {
        "table_id": 1, "dataset_alias": "ds_ads", "dataset_name": "广告数据集",
        "field_name": "sales_amount", "verbose_name": "销售额", "global_alias": "f_sales_amount",
        "field_type": "metric", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 2, "dataset_alias": "ds_inv", "dataset_name": "库存数据集",
        "field_name": "sku", "verbose_name": "SKU", "global_alias": "f_sku2",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 2, "dataset_alias": "ds_inv", "dataset_name": "库存数据集",
        "field_name": "stock_qty", "verbose_name": "库存量", "global_alias": "f_stock_qty",
        "field_type": "metric", "snapshot_metric": 1, "has_formula_config": 0,
    },
]

# ── 场景 4 专用元数据：即时综合 + SP 广告 + 平台查询组件（对齐 tests/skills 既有
#    _write_instant_comprehensive_metadata 的字段口径）──

_INSTANT_DATASETS = [
    {
        "table_id": 10, "dataset_alias": "ds_instant", "dataset_name": "sales_primary_set",
        "dataset_category": "normal", "inner_where_enabled": 0, "description": "即时综合数据集",
    },
    {
        "table_id": 11, "dataset_alias": "ds_ads2", "dataset_name": "ads_set",
        "dataset_category": "normal", "inner_where_enabled": 0, "description": "SP广告数据集",
    },
    {
        "table_id": 17, "dataset_alias": "ds_channel", "dataset_name": "query_channel_set",
        "dataset_category": "query_component", "inner_where_enabled": 0,
        "description": "查询组件渠道数据集",
    },
]
_INSTANT_FIELDS = [
    {
        "table_id": 10, "dataset_alias": "ds_instant", "dataset_name": "sales_primary_set",
        "field_name": "date_id", "verbose_name": "日期", "global_alias": "f_date_id",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 10, "dataset_alias": "ds_instant", "dataset_name": "sales_primary_set",
        "field_name": "sku", "verbose_name": "SKU", "global_alias": "f_sku",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 10, "dataset_alias": "ds_instant", "dataset_name": "sales_primary_set",
        "field_name": "sales_amount", "verbose_name": "销售额", "global_alias": "f_sales_amount",
        "field_type": "metric", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 11, "dataset_alias": "ds_ads2", "dataset_name": "ads_set",
        "field_name": "date_id", "verbose_name": "日期", "global_alias": "f_ads_date",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 11, "dataset_alias": "ds_ads2", "dataset_name": "ads_set",
        "field_name": "acos", "verbose_name": "ACOS", "global_alias": "f_acos2",
        "field_type": "metric", "summary_expression": "ads_cost / sales",
        "description": "广告成本销售比", "snapshot_metric": 0, "has_formula_config": 1,
    },
    {
        "table_id": 17, "dataset_alias": "ds_channel", "dataset_name": "query_channel_set",
        "field_name": "platform_name", "verbose_name": "平台", "global_alias": "f_platform",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
]
_INSTANT_SELECT_COLUMNS = [
    {
        "current_dataset_alias": "ds_instant", "column_name": "platform_name",
        "verbose_name": "平台", "component_dataset_alias": "ds_channel",
    },
    {
        "current_dataset_alias": "ds_ads2", "column_name": "platform_name",
        "verbose_name": "平台", "component_dataset_alias": "ds_channel",
    },
]

# ── 场景 5 专用元数据：同名数据集澄清（对齐 tests/skills 既有
#    test_clarify_contract_carries_candidate_cards 的字段口径）──

_CLARIFY_DATASETS = [
    {
        "table_id": 52, "dataset_alias": "ds_share_a", "dataset_name": "用户仪表盘分享明细",
        "dataset_category": "normal", "inner_where_enabled": 0, "description": "用户仪表盘分享明细",
    },
    {
        "table_id": 61, "dataset_alias": "ds_share_b", "dataset_name": "用户仪表盘分享明细",
        "dataset_category": "normal", "inner_where_enabled": 0,
        "description": "用户仪表盘分享明细(新版)",
    },
]
_CLARIFY_FIELDS = [
    {
        "table_id": 52, "dataset_alias": "ds_share_a", "dataset_name": "用户仪表盘分享明细",
        "field_name": "use_count", "verbose_name": "使用次数", "global_alias": "f_uc_a",
        "field_type": "metric", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 52, "dataset_alias": "ds_share_a", "dataset_name": "用户仪表盘分享明细",
        "field_name": "share_user", "verbose_name": "分享用户", "global_alias": "f_su_a",
        "field_type": "dimension", "snapshot_metric": 0, "has_formula_config": 0,
    },
    {
        "table_id": 61, "dataset_alias": "ds_share_b", "dataset_name": "用户仪表盘分享明细",
        "field_name": "view_count", "verbose_name": "查看次数", "global_alias": "f_vc_b",
        "field_type": "metric", "snapshot_metric": 0, "has_formula_config": 0,
    },
]


# ---------------------------------------------------------------------------
# 双主线调用封装 + 对照断言
# ---------------------------------------------------------------------------


def _run_kernel(payload: dict, query: str, **kwargs) -> dict:
    kwargs.setdefault("enum_fn", lambda *_a, **_k: [])
    kwargs.setdefault("auto_enum", False)
    return kernel_query_plan.build_model_query_plan(MetadataAdapter(payload), query, **kwargs)


def _run_skill(data_dir: Path, query: str, **kwargs) -> dict:
    kwargs.setdefault("auto_upgrade", False)
    kwargs.setdefault("auto_enum", False)
    return skill_query_plan.build_model_query_plan(
        query, data_dir=data_dir, rules_path=RULES_PATH, **kwargs
    )


def _filter_set(filters: list) -> set:
    return {(item.get("field"), item.get("operator"), str(item.get("value"))) for item in filters}


def _assert_order_by_parity(kernel_order, skill_order, scenario: str) -> None:
    """orderBy 形态白名单（K1 已裁决）：内核 {field,desc} 布尔 vs skill {field,direction}
    字符串，语义等价、结构不同——归一后比对字段与方向，不要求原始结构相同。
    """
    assert (kernel_order is None) == (skill_order is None), scenario
    if kernel_order:
        assert kernel_order[0]["field"] == skill_order[0]["field"], scenario
        k_desc = bool(kernel_order[0].get("desc"))
        s_desc = skill_order[0].get("direction") == "DESC"
        assert k_desc == s_desc, scenario


def _assert_planning_parity(kernel_contract: dict, skill_contract: dict, *, scenario: str) -> None:
    """核对 task-K4-brief 规定的四项对照键：status / table_id / query_template
    dimensions·metrics·filters 集合 / 澄清消息键集。
    """
    assert kernel_contract["query_mode"] == skill_contract["query_mode"], scenario
    # metadata_source 键存在性对照（白名单条目，见 change-log-pending.md K4 条目）：
    # 只比对键存在，不比对取值——kernel 元数据恒来自后端接口硬编码
    # "backend_query_metadata"，skill 从本地 CSV/data_state 判定来源
    # （skill_local/published_bundle/fallback_dir），取值本就是架构性差异
    assert "metadata_source" in kernel_contract, scenario
    assert "metadata_source" in skill_contract, scenario
    assert kernel_contract["status"] == skill_contract["status"], scenario
    status = kernel_contract["status"]
    if status == "planned":
        kt = kernel_contract["execution_ref"]["query_template"]
        st = skill_contract["execution_ref"]["query_template"]
        assert str(kt["tableId"]) == str(st["tableId"]), scenario
        assert {d["field"] for d in kt["dimensions"]} == {d["field"] for d in st["dimensions"]}, scenario
        assert {m["field"] for m in kt["metrics"]} == {m["field"] for m in st["metrics"]}, scenario
        assert _filter_set(kt["filters"]) == _filter_set(st["filters"]), scenario
        _assert_order_by_parity(kt.get("orderBy"), st.get("orderBy"), scenario)
        assert kt.get("limit") == st.get("limit"), scenario
    elif status == "clarify_required":
        k_view = kernel_contract["model_view"]
        s_view = skill_contract["model_view"]
        assert set(k_view.get("clarification_reason_codes", [])) == set(
            s_view.get("clarification_reason_codes", [])
        ), scenario
        assert len(k_view.get("clarification_messages_zh", [])) == len(
            s_view.get("clarification_messages_zh", [])
        ), scenario
    else:
        # 第三态防护：两侧同时落入 blocked（或其他未覆盖状态）时，status 相等的
        # 断言会静默通过——但这不是本文件五个场景想验证的路径，说明用例的元数据/
        # 查询原文构造有问题（例如字段解析失败），必须让测试显式失败而不是让
        # "两侧都失败于同一状态"被误判为"对照通过"
        raise AssertionError(
            f"{scenario}: 两侧落入未覆盖的 status={status!r}，不构成有效对照，"
            "请检查用例的元数据/查询原文构造是否命中了预期的 planned/clarify_required 路径"
        )


# ---------------------------------------------------------------------------
# 场景 1：单维度单指标
# ---------------------------------------------------------------------------


def test_single_dimension_single_metric_parity(tmp_path: Path):
    data_dir = tmp_path / "skill_data"
    payload = _write_and_build(data_dir, _BASE_DATASETS, _BASE_FIELDS)
    query = "SP 广告数据集近7天按SKU统计ACOS"

    kernel_contract = _run_kernel(payload, query)
    skill_contract = _run_skill(data_dir, query)

    _assert_planning_parity(kernel_contract, skill_contract, scenario="单维度单指标")
    assert kernel_contract["status"] == "planned", "本场景必须落在 planned，否则用例未覆盖预期路径"


# ---------------------------------------------------------------------------
# 场景 2：带时间口径（环比对比期）
# ---------------------------------------------------------------------------


def test_time_scope_with_comparison_parity(tmp_path: Path):
    data_dir = tmp_path / "skill_data"
    payload = _write_and_build(data_dir, _BASE_DATASETS, _BASE_FIELDS)
    query = "SP 广告数据集 近7天 ACOS 环比上一个7天"

    kernel_contract = _run_kernel(payload, query)
    skill_contract = _run_skill(data_dir, query)

    _assert_planning_parity(kernel_contract, skill_contract, scenario="带时间口径")
    assert kernel_contract["status"] == "planned", "本场景必须落在 planned，否则用例未覆盖预期路径"
    k_scope = kernel_contract["execution_ref"]["time_scope"]
    s_scope = skill_contract["execution_ref"]["time_scope"]
    assert k_scope["comparison_type"] == s_scope["comparison_type"] == "period_over_period"
    assert (k_scope["start"], k_scope["end"]) == (s_scope["start"], s_scope["end"])


# ---------------------------------------------------------------------------
# 场景 3：带排序 TopN
# ---------------------------------------------------------------------------


def test_order_by_topn_parity(tmp_path: Path):
    data_dir = tmp_path / "skill_data"
    payload = _write_and_build(data_dir, _BASE_DATASETS, _BASE_FIELDS)
    query = "SP 广告数据集近7天按ACOS降序排列，只要前5行，维度用SKU"

    kernel_contract = _run_kernel(payload, query)
    skill_contract = _run_skill(data_dir, query)

    _assert_planning_parity(kernel_contract, skill_contract, scenario="带排序TopN")
    if kernel_contract["status"] == "planned":
        kt = kernel_contract["execution_ref"]["query_template"]
        assert kt.get("orderBy"), "TopN 场景必须解析出 orderBy，否则用例未覆盖预期路径"
        assert kt.get("limit") == 5


# ---------------------------------------------------------------------------
# 场景 4：带组件筛选（平台）
# ---------------------------------------------------------------------------


def test_component_filter_parity(tmp_path: Path):
    data_dir = tmp_path / "skill_data"
    payload = _write_and_build(
        data_dir, _INSTANT_DATASETS, _INSTANT_FIELDS, _INSTANT_SELECT_COLUMNS
    )
    query = "使用即时综合数据集查询近7天亚马逊SC销售额"
    authorized_platform_values = ["亚马逊SC", "亚马逊VC"]

    kernel_contract = _run_kernel(
        payload, query, authorized_platform_values=authorized_platform_values
    )
    skill_contract = _run_skill(
        data_dir, query, authorized_platform_values=authorized_platform_values
    )

    _assert_planning_parity(kernel_contract, skill_contract, scenario="带组件筛选")
    if kernel_contract["status"] == "planned":
        assert (
            kernel_contract["execution_ref"]["resolved_platform_values"]
            == skill_contract["execution_ref"]["resolved_platform_values"]
        )


# ---------------------------------------------------------------------------
# 场景 5：澄清场景（同名数据集歧义）
# ---------------------------------------------------------------------------


def test_clarify_scenario_parity(tmp_path: Path):
    data_dir = tmp_path / "skill_data"
    payload = _write_and_build(data_dir, _CLARIFY_DATASETS, _CLARIFY_FIELDS)
    query = "查询用户仪表盘分享明细近30天的使用次数"

    kernel_contract = _run_kernel(payload, query)
    skill_contract = _run_skill(data_dir, query)

    _assert_planning_parity(kernel_contract, skill_contract, scenario="澄清场景")
    assert kernel_contract["status"] == "clarify_required", "本场景应命中同名数据集歧义澄清"
    k_cards = kernel_contract["model_view"]["dataset_candidates_zh"]
    s_cards = skill_contract["model_view"]["dataset_candidates_zh"]
    assert len(k_cards) == len(s_cards) == 2
    assert {c["name_zh"] for c in k_cards} == {c["name_zh"] for c in s_cards}


# ---------------------------------------------------------------------------
# 规则资源同源性：保证上面 5 个场景省略 rules= 显式传参时用的是同一份规则
# ---------------------------------------------------------------------------


def test_intent_rules_resource_matches_skill_source():
    """kernel 从内部资源加载规则（`query_plan._load_rules_resource()`），
    这里核对与 skill 侧 `data/intent_rules.json` 逐字节一致——否则上面 5 个场景
    省略 `rules=` 时两侧就不是同源输入，对照失去意义。
    """
    kernel_rules = kernel_query_plan._load_rules_resource()
    skill_rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    assert kernel_rules == skill_rules


# ---------------------------------------------------------------------------
# 执行段对照：证据合同 + 披露键集
# ---------------------------------------------------------------------------


def test_evidence_contract_identical_across_versions():
    """K1-K3 迁移声明 evidence_contract.py 除 CLI 壳外逐行一致（见 kernel 模块
    docstring 与 skill/kernel 两份源码 diff）；这里用同一份查询返回体验证两侧
    函数输出逐字段相同，作为『证据合同键集一致』的直接证据。
    """
    response = {
        "success": True,
        "data": {
            "payload": {"tableId": "1", "filters": []},
            "result": {
                "data": [{"price": "1.0"}],
                "meta": {
                    "currency": "CNY",
                    "freshness_status": "monthly_data_available_through_2026-07",
                },
            },
        },
    }
    kernel_result = kernel_evidence_contract.build_evidence_contract(
        response, dataset_name_zh="广告数据集"
    )
    skill_result = skill_evidence_contract.build_evidence_contract(
        response, dataset_name_zh="广告数据集"
    )
    assert kernel_result == skill_result


def _kernel_planned_template() -> dict:
    return {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "status": "planned",
        "model_view": {"dataset_name_zh": "广告数据集"},
        "execution_ref": {
            "query_template": {
                "tableId": 1,
                "dimensions": [{"field": "x", "alias": "x"}],
                "metrics": [],
                "filters": [],
                "orderBy": None,
                "limit": None,
            }
        },
    }


def test_result_disclosure_key_set_parity(tmp_path, monkeypatch, capsys):
    """执行段披露键集对照：内核 `run_flow` 的 `result_disclosures` 与 skill
    `run_query.py` 的 `disclosures` 键集差异必须恰好等于下方白名单，白名单外任何
    差异（新增或消失的键）都判定为回归。

    K4b 收口：K4 报告发现的 {currency, currency_disclosure_zh, limit} 缺口已在
    entry.py 补齐（`_extract_currency` 逐字迁入 + `original_limit` 在 auto-complete
    就地改写模板前捕获），键集差异只剩下架构性差异：
    - kernel 独有 {auto_complete_applied}：K2 已裁决的执行通道架构差异——源实现
      `preview_rows`/落盘文件/`disclosures` 三通道分离，触发时才在 `disclosures`
      内追加 `server_paging` 子对象；kernel `run_flow` 只有 `result_disclosures`
      一个通道，改为恒定输出布尔标记（见 task-K2-report.md「已落地的两道防线」段）。
    """
    # kernel 侧：跳过完整规划，直接注入已规划模板，只验证执行段披露键集
    monkeypatch.setattr(kernel_entry, "run_plan", lambda *_a, **_k: _kernel_planned_template())

    class _KernelQM:
        def run_query_template(self, execution_ref):
            return {
                "data": {
                    "result": {
                        "data": [{"x": 1}],
                        "meta": {"totalCount": 1, "currency": "cny"},
                    }
                }
            }

    kernel_out = kernel_entry.run_flow(
        "查询", user_email="u@x.com",
        result_dir=tmp_path / "kernel_out",
        query_manager=_KernelQM(),
    )
    kernel_keys = set(kernel_out["result_disclosures"].keys())

    # skill 侧：同形返回体（含 meta.currency），走真实 main() 入口（monkeypatch 掉 subprocess 调用）
    monkeypatch.setattr(
        skill_run_query,
        "_run_opscli",
        lambda *_a, **_k: {
            "data": {
                "result": {
                    "data": [{"x": 1}],
                    "meta": {"totalCount": 1, "currency": "cny"},
                }
            }
        },
    )
    exit_code = skill_run_query.main(
        [
            "--table-id", "1",
            "--json", json.dumps({"tableId": 1, "dimensions": [{"field": "x", "alias": "x"}]}),
            "--unsafe-unbound-plan",
            "--no-evidence",
            "--result-dir", str(tmp_path / "skill_out"),
        ]
    )
    assert exit_code == 0
    skill_out = json.loads(capsys.readouterr().out)
    skill_keys = set(skill_out["disclosures"].keys())

    assert skill_keys - kernel_keys == set()
    assert kernel_keys - skill_keys == {"auto_complete_applied"}
    # 公共键的语义（而非仅键名）必须一致
    assert (
        kernel_out["result_disclosures"]["row_count_returned"]
        == skill_out["disclosures"]["row_count_returned"]
    )
    assert (
        kernel_out["result_disclosures"]["total_count"] == skill_out["disclosures"]["total_count"]
    )
    assert kernel_out["result_disclosures"]["truncated"] == skill_out["disclosures"]["truncated"]
    assert kernel_out["result_disclosures"]["full_result_file"] is not None
    assert skill_out["disclosures"]["full_result_file"] is not None
    # 币种披露值与文案必须逐字一致（两侧对同一份含 meta.currency 的返回体）
    assert kernel_out["result_disclosures"]["currency"] == skill_out["disclosures"]["currency"] == "CNY"
    assert (
        kernel_out["result_disclosures"]["currency_disclosure_zh"]
        == skill_out["disclosures"]["currency_disclosure_zh"]
    )
    # 原始 limit 披露：两侧规划模板均未指定 limit，均应为 None（未被 auto-complete 污染）
    assert kernel_out["result_disclosures"]["limit"] == skill_out["disclosures"]["limit"] is None
