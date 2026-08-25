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

# 意图触发词覆盖不足的真实缺口，保留为 xfail 而不是删除：删了就再也没人知道差在哪。
# case_002/004/013/015 在旧画像与现 catalog 下表现一致，均为触发词竞争问题；
# case_007 已随 SP关键词数据集 上线而修复，从本表移出。
KNOWN_ROUTING_GAPS = {
    "case_002": "「今天销售」未进即时销售触发词，路由到承接它的即时综合数据集",
    "case_004": "「各平台广告整体投入」被即时综合的意图名加权压过广告费数据集",
    "case_013": "「沃尔玛平台广告活动明细」被活动数据集的「活动」触发词抢走",
    "case_015": "「销售主口径下的转化率」被流量转化率数据集抢走",
}

# 意图目录与数据集清单的快照夹具。
# 为什么用夹具而不是读模板 data/：模板 data/ 是占位符（datasets.csv 只有表头、
# dataset_catalog.json 为空），真实内容由 opscli skills upgrade 从服务端下发，
# 仓库里不存在可供断言的真数据。夹具取自一次真实 upgrade 后的安装目录快照。
CATALOG = json.loads(
    (Path(__file__).parent / "data" / "dataset_catalog_fixture.json").read_text(encoding="utf-8")
)
DATASETS_CSV = (Path(__file__).parent / "data" / "datasets_fixture.csv").read_text(
    encoding="utf-8"
)
# 夹具里承担字段级断言的两张表：即时综合（维度/指标齐全）与广告费（带公式指标）
DS_INSTANT = "ds_d35ac6f3910c"
DS_ADS_FEE = "ds_0759e20F0DrG"


def _write_ready_data_dir(data_dir: Path) -> None:
    """写一套 ready 的本地索引：真实数据集清单 + 真实意图目录 + 最小字段表。

    字段表保持手写最小集而不用真实快照：字段级用例只关心「点名字段能否命中、
    不存在的字段会不会被编出来」，塞进上万行真实字段只会让断言变得不可读。
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v9.9.9", "data_state": "ready"}),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(DATASETS_CSV, encoding="utf-8")
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        f"1,{DS_INSTANT},即时综合数据集,channel_name,渠道,f_channel,dimension,,,,,0,0\n"
        f"1,{DS_INSTANT},即时综合数据集,asin,ASIN,f_asin,dimension,,,,,0,0\n"
        f"1,{DS_INSTANT},即时综合数据集,sales,销售额,f_sales,metric,,,,,0,0\n"
        f"15,{DS_ADS_FEE},广告费数据集,acos,ACOS,f_acos,metric,cost/sales,,,,0,1\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        f"{DS_INSTANT},channel_name,渠道,ds_channel\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_catalog.json").write_text(
        json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8"
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
    candidates = result.get("dataset_candidates") or []
    names = [item.get("name_zh") for item in candidates]
    assert names, f"{case['id']} 未产出任何候选：{case['user_query']}"
    assert names[0] == case["expected_dataset"], (
        f"{case['id']} 首选数据集不符：期望 {case['expected_dataset']}，实际 {names}"
    )


@pytest.mark.parametrize("case", EVAL_CASES, ids=[case["id"] for case in EVAL_CASES])
def test_intent_routing_candidates_are_executable(case: dict, tmp_path: Path):
    """候选必须解析得出 table_id 与 dataset_alias，否则 Agent 拿到也执行不了。

    为什么单独立一条：路由用例只断中文名，而中文名腐烂得比 alias 慢——旧画像时期
    21 条用例名字命中 16 条，实际能解析出 table_id 的只有 4 条，绿灯掩盖了
    「候选全是死路」的真相。这条断言把可执行性钉死，改名也不会再放它过去。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    candidates = local_fallback.build_fallback(case["user_query"], data_dir=data_dir).get(
        "dataset_candidates"
    ) or []
    assert candidates, f"{case['id']} 未产出任何候选：{case['user_query']}"
    for item in candidates:
        assert item.get("dataset_alias"), f"{case['id']} 候选缺 dataset_alias：{item}"
        assert item.get("table_id"), f"{case['id']} 候选缺 table_id：{item}"


def test_embedded_intent_maps_to_execution_dataset(tmp_path: Path):
    """embedded_intent 必须落到承接它的父数据集，并保留原意图名供披露口径差异。

    查询用「大促」而不是「即时销售」：后者在意图目录里被即时销售监控和
    即时销售与广告综合分析两条意图共享，宽口径那条触发词更少、归一化置信度更高会
    压过来，本用例就变成在考排序而不是考跳转。「大促」是前者独占的触发词。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback("大促期间销售异常吗", data_dir=data_dir)
    top = (result.get("dataset_candidates") or [{}])[0]
    assert top.get("name_zh") == "即时销售数据集"
    assert top.get("execution_dataset") == "即时综合数据集"
    assert top.get("routing_status") == "embedded_intent"
    # 跳转后必须解析出父表的 table_id，否则跳转等于把候选跳成死路
    assert top.get("table_id") == "1"


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
        dataset_alias=DS_INSTANT,
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
        dataset_alias=DS_INSTANT,
        data_dir=data_dir,
    )
    assert result["field_candidates"] == []
    assert result["status"] == "clarify_required"


def test_result_carries_no_guess_and_filter_value_policy(tmp_path: Path):
    """降级结果必须随身带「不许猜」与「筛选值须枚举校验」两条硬规则。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    result = local_fallback.build_fallback(
        "查渠道和ASIN", dataset_alias=DS_INSTANT, data_dir=data_dir
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


def test_business_constraints_reach_agent_under_at_least_one_key(tmp_path: Path):
    """意图的业务约束必须至少经某个键抵达 Agent，两键同时为空等于护栏被静默吞掉。

    审查发现的形态：约束因未经人工复核而全部落在 `uncertified_hints_zh`，
    而 SKILL.md 当时只教 Agent 遵守 `hard_constraints`——防静默错数的护栏
    （库存快照字段只能用于明细表、亚马逊搜索词绩效「必须选择报告周期」）就此无人消费。
    本用例只锁「约束不能一个键都不到」这条不变量，不锁它落在哪个键，
    因此后续把某批约束升级为已复核也不会误伤。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)
    # 期望值从意图目录派生：按 intent_code 取约束，服务端增删条目时自动跟随
    constrained = {
        str(item.get("intent_code")): item.get("hard_constraints") or []
        for item in CATALOG["intents"]
        if item.get("hard_constraints")
    }

    for query in ("看一下近30天整体经营情况，销售广告库存流量一起看", "搜索词的点击份额"):
        candidates = local_fallback.build_fallback(query, data_dir=data_dir)[
            "dataset_candidates"
        ]
        assert candidates, query
        top = candidates[0]
        if top.get("intent_id") not in constrained:
            continue
        delivered = (top.get("hard_constraints") or []) + (
            top.get("uncertified_hints_zh") or []
        )
        assert delivered, f"{query} → {top.get('name_zh')} 的业务约束一个键都没抵达 Agent"
        assert delivered == constrained[top["intent_id"]], (
            f"{query} → {top.get('name_zh')} 的业务约束在传递中被截断或改写"
        )


def test_skill_md_registers_uncertified_hints_key(tmp_path: Path):
    """降级路径实际产出的约束键必须在 SKILL.md 里有登记，否则 Agent 不会消费它。

    `uncertified_hints_zh` 曾在 SKILL.md、其它脚本、任何文档里零引用——
    键存在但无人消费，等于约束没交付。
    """
    skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "uncertified_hints_zh" in skill_md
    # 只登记键名不够：必须写明「先复述确认再套用」，否则会被当成已确认口径直接用
    assert "未经人工审核" in skill_md


def test_emit_plan_produces_executor_consumable_plan(tmp_path: Path):
    """降级 plan 必须能被 run_query.py 消费，从而保留字段校验闸。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)
    plan_path = tmp_path / "plan.json"

    result = local_fallback.build_fallback(
        "查渠道和ASIN",
        requested_fields=["渠道", "ASIN"],
        dataset_alias=DS_INSTANT,
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
# 意图目录结构：路由所依赖的最小合同
# ---------------------------------------------------------------------------


def test_catalog_intents_resolve_to_a_dataset():
    """每条意图都必须能解析出数据集，否则路由中它就等于产出一个死候选。

    只锁 local_fallback 真正依赖的三个键：intent_code（候选回标意图）、
    dataset_alias（回查 datasets.csv 取中文名与 table_id）、
    embedded_intent 的 execution_dataset_id（跳转父表）。
    catalog 由服务端生成，其余字段的形状不在本仓库的断言范围内。
    """
    for intent in CATALOG["intents"]:
        assert intent.get("intent_code"), f"意图缺 intent_code：{intent}"
        assert intent.get("dataset_alias"), f"{intent.get('intent_code')} 缺 dataset_alias"
        if intent.get("routing_status") == "embedded_intent":
            assert intent.get("execution_dataset_id"), (
                f"{intent.get('intent_code')} 声明 embedded_intent 却没有 execution_dataset_id"
            )


# ---------------------------------------------------------------------------
# 覆盖率巡检：catalog 与 datasets.csv 是两次独立下发，仍会互相漂移
# ---------------------------------------------------------------------------


def test_audit_reports_coverage_gap(tmp_path: Path):
    """巡检必须报出没有意图入口的表与已对不上元数据的意图，让漂移可见。

    断具体集合内容而不是只断形状：故意构造一张只有「新表 + 一张被意图覆盖的表」
    的 datasets.csv——新表没有意图入口（missing），意图目录里其余 35 个 alias
    在本次元数据里查不到（stale）。只断 `total_datasets >= 1` 或键存在的话，
    把 missing/stale 的集合差算反、或 `profiled` 写成 `len(profiled)` 而不是
    `len(profiled & aliases)`，全部照过。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        f"1,{DS_INSTANT},order_sale_trend_adv_traffic_inv_set,normal,0,即时综合数据集,\n"
        "999,ds_brand_new,brand_new_set,normal,0,尚未配意图的新表,\n",
        encoding="utf-8",
    )
    catalog_aliases = {
        str(item["dataset_alias"]) for item in CATALOG["intents"] if item.get("dataset_alias")
    }

    report = local_fallback.audit_profiles(data_dir=data_dir)

    assert report["status"] == "ok"
    assert report["total_datasets"] == 2
    # 新表没有意图入口：算反差集会让这里变成一堆意图 alias
    assert report["missing_profiles"] == ["ds_brand_new"]
    # 即时综合有意图入口：漏掉 & aliases 会让 profiled 变成全部意图数
    assert report["profiled"] == 1
    assert report["stale_profiles"] == sorted(catalog_aliases - {DS_INSTANT})
    # 唯一的 embedded_intent 指向 table_id=1，本次元数据里存在，因此不算断链
    assert report["broken_intent_links"] == []


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
    """数据目录存在但是空模板时也要挡住，不能把 0/0 误报成"意图已全覆盖"。

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


def test_emit_plan_carries_intent_attribution(tmp_path: Path):
    """降级 plan 必须带意图归因，执行段才能把 intent_code 透传给服务端落库。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    # 任务简报原用「大促期间销售异常吗」，但该句同时含「销售」二字，会被
    # ops_comprehensive_monitoring 的意图名分词命中（+0.3 分），产出第二候选，
    # 导致 status 落在 clarify_required 而非 ready（与 test_embedded_intent_
    # maps_to_execution_dataset 特意不断言 status 的原因一致）。这里把「销售」
    # 换成语义等价的「数据」，只保留 realtime_sales_monitoring 独占的「大促」
    # 触发词，使其成为唯一候选，从而验证 status=ready 路径下 execution_ref 的
    # 意图归因透传。
    result = local_fallback.build_fallback("大促期间数据异常吗", data_dir=data_dir)
    assert result["status"] == "ready"
    plan_path = tmp_path / "plan.json"
    local_fallback._emit_plan(result, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert plan["execution_ref"]["intent_code"] == "realtime_sales_monitoring"
    assert plan["execution_ref"]["selection_source"] == "local_fallback"


def test_audit_reports_broken_intent_links(tmp_path: Path):
    """巡检必须报出 execution_dataset_id 找不到对应表的 embedded_intent。

    embedded_intent 靠 execution_dataset_id 跳转到承接它的父表，父表下线后
    这条跳转会静默失效，路由结果退回意图自身表——巡检必须让这个问题可见，
    而不是只查数据集覆盖率。
    """
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)
    broken_catalog = {
        "intents": [
            {"intent_code": "intent_ok", "dataset_alias": DS_INSTANT},
            {
                "intent_code": "intent_broken",
                "dataset_alias": DS_INSTANT,
                "routing_status": "embedded_intent",
                "execution_dataset_id": 99999,
            },
        ]
    }
    (data_dir / "dataset_catalog.json").write_text(
        json.dumps(broken_catalog, ensure_ascii=False), encoding="utf-8"
    )

    report = local_fallback.audit_profiles(data_dir=data_dir)
    assert report["broken_intent_links"] == [
        {"intent_id": "intent_broken", "execution_dataset_id": 99999}
    ]
