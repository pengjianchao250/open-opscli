"""规划器降级路径回归测试。

守住的核心行为：规划器失败时 Agent 仍有一条**只用本地权威数据**的路可走，
且这条路在任何不确定的地方都停下来问，而不是替用户做主。

路由用例迁移自旧版 ops-dataset-query v1.0.2 的 routing_eval_cases.yml，
是目前唯一能量化路由质量的资产。
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

import local_fallback  # noqa: E402

EVAL_CASES = json.loads(
    (Path(__file__).parent / "data" / "routing_eval_cases.json").read_text(encoding="utf-8")
)["cases"]

# 旧版 route_intent.py 本身也路由不中的用例（已逐条跑过旧实现对照，结论一致）。
# 迁移时保留为 xfail 而不是删除：这是意图触发词覆盖不足的真实缺口，
# 删了就再也没人知道差在哪；本次移植的目标是「行为等价」，不是顺手改口径。
KNOWN_ROUTING_GAPS = {
    "case_002": "「今天销售」未进即时销售触发词，新旧版都路由到即时综合数据集",
    "case_004": "「各平台广告整体投入」被即时综合的 user_intent 加权压过广告费数据集",
    "case_007": "「SP关键词表现」无任何触发词命中，新旧版都产不出候选",
    "case_013": "「沃尔玛平台广告活动明细」被活动数据集的「活动」触发词抢走",
    "case_015": "「销售主口径下的转化率」被流量转化率数据集抢走",
}

PROFILES = json.loads(
    (SKILL_ROOT / "data" / "dataset_profiles.json").read_text(encoding="utf-8")
)


def _write_ready_data_dir(data_dir: Path) -> None:
    """写一套 ready 的最小本地索引，附带真实画像文件。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v9.9.9", "data_state": "ready"}),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_instant,order_sale_trend_adv_traffic_inv_set,normal,0,即时综合数据集,\n"
        "12,ds_ads_fee,ads_fee_set,normal,0,广告费数据集,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "1,ds_instant,即时综合数据集,channel_name,渠道,f_channel,dimension,,,,,0,0\n"
        "1,ds_instant,即时综合数据集,asin,ASIN,f_asin,dimension,,,,,0,0\n"
        "1,ds_instant,即时综合数据集,sales,销售额,f_sales,metric,,,,,0,0\n"
        "12,ds_ads_fee,广告费数据集,acos,ACOS,f_acos,metric,cost/sales,,,,0,1\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_instant,channel_name,渠道,ds_channel\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_profiles.json").write_text(
        json.dumps(PROFILES, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 意图路由质量（迁移自旧版 eval 用例）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            case,
            marks=pytest.mark.xfail(
                reason=KNOWN_ROUTING_GAPS[case["id"]], strict=True
            ),
        )
        if case["id"] in KNOWN_ROUTING_GAPS
        else case
        for case in EVAL_CASES
    ],
    ids=[case["id"] for case in EVAL_CASES],
)
def test_intent_routing_hits_expected_dataset(case: dict, tmp_path: Path):
    """每条历史用例都应把期望数据集路由进候选，且排在首位。

    只断言「命中且居首」，不断言唯一——降级路径本就允许多候选后交用户选择。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(case["user_query"], data_dir=data_dir)
    names = [item.get("name_zh") for item in result.get("dataset_candidates") or []]
    assert names, f"{case['id']} 未产出任何候选：{case['user_query']}"
    assert names[0] == case["expected_dataset"], (
        f"{case['id']} 首选数据集不符：期望 {case['expected_dataset']}，实际 {names}"
    )


def test_embedded_intent_maps_to_execution_dataset(tmp_path: Path):
    """embedded_intent 必须落到承接它的父数据集，并保留原意图名供披露口径差异。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback("即时销售今天怎么样", data_dir=data_dir)
    top = (result.get("dataset_candidates") or [{}])[0]
    assert top.get("name_zh") == "即时销售数据集"
    assert top.get("execution_dataset") == "即时综合数据集"
    assert top.get("routing_status") == "embedded_intent"


# ---------------------------------------------------------------------------
# 降级链路：不许猜
# ---------------------------------------------------------------------------


def test_placeholder_data_blocks_instead_of_guessing(tmp_path: Path):
    """本地索引是空模板时必须阻断——此时任何数据集名字段名都只能是猜的。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v0", "data_state": "placeholder"}),
        encoding="utf-8",
    )

    result = local_fallback.build_fallback("查渠道和ASIN", data_dir=data_dir)
    assert result["status"] == "blocked"
    assert result["fallback_level"] == "L3_metadata_refresh"
    assert "opscli skills upgrade" in result["recovery_command"]
    assert "dataset_candidates" not in result


def test_missing_data_dir_blocks(tmp_path: Path):
    """数据目录不存在同样阻断，不得回退到凭空构造。"""
    result = local_fallback.build_fallback("查渠道", data_dir=tmp_path / "nope")
    assert result["status"] == "blocked"
    assert result["fallback_level"] == "L3_metadata_refresh"


def test_ambiguous_candidates_require_clarification(tmp_path: Path):
    """候选不唯一时必须转澄清，不允许默默取第一个。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(
        "看一下整体经营情况和各平台广告投入ACOS", data_dir=data_dir
    )
    assert len(result["dataset_candidates"]) > 1
    assert result["status"] == "clarify_required"
    assert result["selected_dataset_alias"] is None
    assert "AskUserQuestion" in result["next_action_zh"]


def test_explicit_dataset_is_confirmed_from_csv(tmp_path: Path):
    """用户点名数据集时按 CSV 权威记录确认，字段范围收敛到该表。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(
        "查渠道和ASIN",
        requested_fields=["渠道", "ASIN"],
        dataset_alias="ds_instant",
        data_dir=data_dir,
    )
    assert result["status"] == "ready"
    assert result["dataset_candidates"][0]["source"] == "user_specified"
    assert {item["field_name"] for item in result["field_candidates"]} == {
        "channel_name",
        "asin",
    }


def test_unknown_requested_field_does_not_get_invented(tmp_path: Path):
    """点名字段在本地不存在时返回空候选并转澄清，绝不编一个字段名出来。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(
        "查一下并不存在的字段",
        requested_fields=["根本不存在的字段"],
        dataset_alias="ds_instant",
        data_dir=data_dir,
    )
    assert result["field_candidates"] == []
    assert result["status"] == "clarify_required"


def test_result_carries_no_guess_and_filter_value_policy(tmp_path: Path):
    """降级结果必须随身带「不许猜」与「筛选值须枚举校验」两条硬规则。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(
        "查渠道和ASIN", dataset_alias="ds_instant", data_dir=data_dir
    )
    assert "禁止凭记忆或推测" in result["no_guess_policy_zh"]
    assert "枚举" in result["filter_value_policy_zh"]
    # 查询组件必须随附，否则 Agent 不知道哪些筛选值需要权限校验
    assert [item["field_name"] for item in result["filter_components"]] == ["channel_name"]


def test_hard_constraints_ride_along_with_candidates(tmp_path: Path):
    """数据集业务约束必须跟着候选一起交出去，降级路径才不会重蹈旧版覆辙。

    迁移后画像全部 certified=False（未经人工复核的旧口径），因此约束不能混进
    hard_constraints 冒充权威规则，只能降级为 uncertified_hints_zh 提示。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(
        "看一下近30天整体经营情况，销售广告库存流量一起看", data_dir=data_dir
    )
    top = result["dataset_candidates"][0]
    assert top["hard_constraints"] == [], "未审核的业务约束不能混入 hard_constraints"
    assert top["uncertified_hints_zh"], "即时综合数据集的业务约束提示丢失"
    assert any("库存快照" in item for item in top["uncertified_hints_zh"])


def test_emit_plan_produces_executor_consumable_plan(tmp_path: Path):
    """降级 plan 必须能被 run_query.py 消费，从而保留字段校验闸。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)
    plan_path = tmp_path / "plan.json"

    result = local_fallback.build_fallback(
        "查渠道和ASIN",
        requested_fields=["渠道", "ASIN"],
        dataset_alias="ds_instant",
        data_dir=data_dir,
    )
    local_fallback._emit_plan(result, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert plan["status"] == "planned"
    assert plan["plan_source"] == "local_fallback"
    # 执行器要求 plan 带 query_template 才放行
    template = plan["execution_ref"]["query_template"]
    assert {item["field"] for item in template["dimensions"]} == {"channel_name", "asin"}
    # 降级模板不预填任何筛选与时间条件，避免替用户做主
    assert template["filters"] == []


# ---------------------------------------------------------------------------
# 画像结构：按 alias 索引 + 删除可派生字段（Task 6）
# ---------------------------------------------------------------------------


def test_profiles_are_indexed_by_alias(tmp_path: Path):
    """画像必须按 dataset_alias 索引：按中文名索引会在数据集改名时静默腐烂。

    实测：现有 15 份画像里有 5 份的 standard_name 已对不上后端。
    查不到 alias 的条目不删除，但必须标 stale_reason 让巡检能看见腐烂。
    """
    profiles = json.loads(
        (SKILL_ROOT / "data" / "dataset_profiles.json").read_text(encoding="utf-8")
    )
    for item in profiles["datasets"]:
        assert item.get("dataset_alias") or item.get("stale_reason"), (
            f"画像缺少 dataset_alias 且未标 stale_reason：{item.get('standard_name')}"
        )


def test_profiles_carry_certification_state(tmp_path: Path):
    """每份画像必须带审核状态，未审核的只能作提示不能作硬约束。"""
    profiles = json.loads(
        (SKILL_ROOT / "data" / "dataset_profiles.json").read_text(encoding="utf-8")
    )
    for item in profiles["datasets"]:
        assert item.get("certified") in (True, False), item.get("dataset_alias")


def test_profiles_do_not_carry_derivable_fields(tmp_path: Path):
    """默认维度指标可由 CSV 实时生成，留在画像里只会与元数据漂移。"""
    profiles = json.loads(
        (SKILL_ROOT / "data" / "dataset_profiles.json").read_text(encoding="utf-8")
    )
    for item in profiles["datasets"]:
        assert "default_dimensions" not in item
        assert "default_metrics" not in item


# ---------------------------------------------------------------------------
# 覆盖率巡检（Task 7）：画像靠人工维护，没有巡检就只能等出错才发现
# ---------------------------------------------------------------------------


def test_audit_reports_coverage_gap(tmp_path: Path):
    """巡检必须报出未建画像与已腐烂的画像，让维护成本可见而不是靠人想起来。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    report = local_fallback.audit_profiles(data_dir=data_dir)
    assert report["total_datasets"] >= 1
    assert "missing_profiles" in report and "stale_profiles" in report
    assert isinstance(report["certified"], int)


def test_audit_blocks_when_data_dir_missing(tmp_path: Path):
    """数据目录缺失时巡检要给可操作的恢复指引，而不是崩溃或裸报错。

    blocked 载荷字段形状对齐 build_fallback() 的同类分支，同一文件里
    两份 blocked 合同不能长得不一样。
    """
    report = local_fallback.audit_profiles(data_dir=tmp_path / "nope")
    assert report["status"] == "blocked"
    assert report["data_state"] == "missing"
    assert "opscli skills upgrade" in report["next_action_zh"]
    assert report["recovery_command"] == "opscli skills upgrade ops-dataset-query"


def test_audit_blocks_when_data_is_placeholder(tmp_path: Path):
    """数据目录存在但是空模板时也要挡住，不能把 0/0 误报成"画像已全覆盖"。

    真实巡检时命中过：安装目录被 `opscli skills install --force` 整体覆盖回
    仓库模板（模板自带占位数据）后，datasets.csv 是空表，若不挡住会把
    total_datasets=0 误读成覆盖率数字，而不是数据未就绪。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v0", "data_state": "placeholder"}),
        encoding="utf-8",
    )

    report = local_fallback.audit_profiles(data_dir=data_dir)
    assert report["status"] == "blocked"
    assert report["data_state"] == "placeholder"
    assert "opscli skills upgrade" in report["next_action_zh"]
    assert report["recovery_command"] == "opscli skills upgrade ops-dataset-query"


def test_audit_reports_broken_intent_links(tmp_path: Path):
    """巡检必须报出 primary_dataset 对不上任何画像 standard_name 的意图。

    intents[].primary_dataset 按中文名指向数据集，这条链接没有 alias 保护，
    数据集改名后会静默断裂——巡检必须让这个问题可见，而不是只查数据集覆盖率。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)
    broken_profiles = {
        "intents": [
            {"intent_id": "intent_ok", "primary_dataset": "即时综合数据集"},
            {"intent_id": "intent_broken", "primary_dataset": "已改名的数据集"},
        ],
        "datasets": [
            {
                "dataset_alias": "ds_instant",
                "standard_name": "即时综合数据集",
                "certified": True,
            }
        ],
    }
    (data_dir / "dataset_profiles.json").write_text(
        json.dumps(broken_profiles, ensure_ascii=False), encoding="utf-8"
    )

    report = local_fallback.audit_profiles(data_dir=data_dir)
    assert report["broken_intent_links"] == [
        {"intent_id": "intent_broken", "primary_dataset": "已改名的数据集"}
    ]
