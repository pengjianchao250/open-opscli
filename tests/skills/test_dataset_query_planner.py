"""ops-dataset-query 本地查询规划器（query_plan 组合入口）的回归测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema


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

import query_plan  # noqa: E402
import run_query  # noqa: E402
import scoped_metadata_index  # noqa: E402
import time_scope  # noqa: E402

RULES_PATH = SKILL_ROOT / "data" / "intent_rules.json"
CHART_UUID = "e49a7298-67d7-4abb-a11f-284673297661"


def _write_ready_metadata(data_dir: Path) -> None:
    """写入一套最小的 data_state=ready 元数据（含公式指标与快照指标）。"""
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.2.3", "data_state": "ready"}),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,SP广告数据集,\n"
        "2,ds_inv,库存数据集,normal,0,库存快照数据集,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "1,ds_ads,广告数据集,date_id,日期,f_date_id,dimension,,,,,0,0\n"
        "1,ds_ads,广告数据集,acos,ACOS,f_acos,metric,ads_cost / sales,,广告成本销售比,,0,1\n"
        "2,ds_inv,库存数据集,sku,SKU,f_sku,dimension,,,,,0,0\n"
        "2,ds_inv,库存数据集,stock_qty,库存量,f_stock_qty,metric,,,,,1,0\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_ads,platform_name,平台,ds_ads\n",
        encoding="utf-8",
    )


def _write_ready_metadata_with_filter_config(data_dir: Path) -> None:
    """写入带 filter_config 的 data_state=ready 元数据。

    ds_ads 的 date_type 维度字段配置了 required QUARTER 默认条件，
    用于验证规划器的默认条件投影能力（R5）。
    """
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.2.3", "data_state": "ready"}),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,SP广告数据集,\n"
        "2,ds_inv,库存数据集,normal,0,库存快照数据集,\n",
        encoding="utf-8",
    )
    # filter_config 单元格：CSV 内嵌 JSON 需用双引号包裹，内部双引号转义为 ""
    fc_json = json.dumps({
        "type": "required",
        "enabled": True,
        "operator": "equals",
        "filter_type": "enum",
        "enum_value": ["QUARTER"],
        "value": None,
        "filter_agg": "none",
    }, ensure_ascii=False)
    fc_cell = '"' + fc_json.replace('"', '""') + '"'
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config,filter_config\n"
        f"1,ds_ads,广告数据集,date_type,日期类型,f_date_type,dimension,,,,,0,0,{fc_cell}\n"
        "1,ds_ads,广告数据集,date_id,日期,f_date_id,dimension,,,,,0,0,\n"
        "1,ds_ads,广告数据集,acos,ACOS,f_acos,metric,ads_cost / sales,,广告成本销售比,,0,1,\n"
        "2,ds_inv,库存数据集,sku,SKU,f_sku,dimension,,,,,0,0,\n"
        "2,ds_inv,库存数据集,stock_qty,库存量,f_stock_qty,metric,,,,,1,0,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_ads,platform_name,平台,ds_ads\n",
        encoding="utf-8",
    )


def test_chart_uuid_data_request_bypasses_dataset_metadata(tmp_path: Path):
    """图表数据请求应在读取本地元数据前分流，并生成可执行 Chart 命令。"""
    result = query_plan.build_model_query_plan(
        f"查询图表ID：{CHART_UUID} 的数据",
        data_dir=tmp_path / "missing-data",
        auto_upgrade=False,
    )

    assert result["query_mode"] == "chart_uuid"
    assert result["data_state"] == "not_required"
    assert result["status"] == "planned"
    assert result["execution_ref"] == {
        "user_visible": False,
        "chart_uuid": CHART_UUID,
        "chart_action": "run",
        "query_command": f"opscli query chart --uuid {CHART_UUID} --run --pretty",
        "run": True,
        "dry_run": False,
    }


def test_chart_uuid_plans_structure_dry_run_and_document():
    """图表入口应按用户原文区分结构、SQL 和文档三种非数据执行动作。"""
    cases = [
        ("只获取图表 UUID {uuid} 的查询结构，不执行", "structure", "query chart", "--run"),
        ("图表 UUID {uuid} 只生成SQL", "dry_run", "--dry-run", "--run"),
        ("为图表 UUID {uuid} 生成API文档", "document", "query chart-doc", "--run"),
    ]
    for prompt, action, command_marker, absent_marker in cases:
        result = query_plan.build_model_query_plan(
            prompt.format(uuid=CHART_UUID), auto_upgrade=False
        )
        command = result["execution_ref"]["query_command"]
        assert result["execution_ref"]["chart_action"] == action
        assert command_marker in command
        assert absent_marker not in command


def test_chart_uuid_multiple_candidates_require_clarification():
    """同一请求含多个图表 UUID 时不得静默选择。"""
    second_uuid = "11111111-2222-4333-8444-555555555555"
    result = query_plan.build_model_query_plan(
        f"对比图表 {CHART_UUID} 和图表 {second_uuid} 的数据",
        auto_upgrade=False,
    )

    assert result["query_mode"] == "chart_uuid"
    assert result["status"] == "clarify_required"
    assert result["execution_ref"]["chart_uuid_candidates"] == [CHART_UUID, second_uuid]
    assert "query_command" not in result["execution_ref"]


def test_chart_uuid_contract_matches_strict_schema():
    """图表规划结果必须通过与普通规划共用的严格模型合同 Schema。"""
    result = query_plan.build_model_query_plan(
        f"执行图表 chart_uuid: {CHART_UUID} 的数据", auto_upgrade=False
    )
    schema = json.loads((SKILL_ROOT / "data" / "query_plan.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(result)


def test_chart_uuid_cli_default_output_uses_chart_route(capsys):
    """query_plan.py 默认 CLI 输出应直接返回图表模型合同。"""
    exit_code = query_plan.main([f"查询图表ID {CHART_UUID} 的数据", "--no-auto-upgrade"])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["query_mode"] == "chart_uuid"
    assert result["execution_ref"]["chart_action"] == "run"


def test_query_plan_selects_acos_with_formula_policy(tmp_path: Path):
    """显式点名数据集 + 公式指标：应定表并给出公式聚合口径。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    cards = scoped_metadata_index.build_cards(data_dir)
    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert {card["dataset_alias"] for card in cards} == {"ds_ads", "ds_inv"}
    assert result["status"] == "planned"
    assert result["model_view"]["dataset_name_zh"] == "SP广告数据集"
    assert "ACOS" in result["model_view"]["metrics"]
    assert result["execution_ref"]["user_visible"] is False
    acos = next(
        item
        for item in result["execution_ref"]["metrics"]
        if item["field_name"] == "acos"
    )
    assert acos["is_formula"] is True
    assert acos["aggregation_policy"] == "formula_expression_without_extra_aggregation"


def test_snapshot_metric_gets_snapshot_aggregation_policy(tmp_path: Path):
    """快照类指标（snapshot_metric=1）必须带最新快照聚合口径。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "库存快照数据集 近7天 库存量",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "planned"
    stock = next(
        item
        for item in result["execution_ref"]["metrics"]
        if item["field_name"] == "stock_qty"
    )
    assert stock["is_snapshot"] is True
    assert stock["aggregation_policy"] == "latest_snapshot_no_period_aggregation"


def test_unsupported_platform_scope_is_blocked_explicitly(tmp_path: Path):
    """请求了不支持的平台（如沃尔玛）时应明确阻断为平台范围不支持，而非枚举歧义。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS 只看沃尔玛平台",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "blocked"
    assert result["model_view"]["next_action"] == "block_platform_scope_unsupported"


def test_published_bundle_version_shape_is_ready(tmp_path: Path):
    """技能广场发布包形状的 VERSION.json（无 data_state 字段）必须被判定为就绪。

    背景：2026-07-13 QA e2e 实测发布包被 data_state 硬校验全部打回 blocked，
    导致二代管线完全失效；本用例锁定兼容判定不回退。
    """
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    # 覆写为 BI 发布管线的真实形状：无 data_state，仅有 dataset_count 等字段
    (data_dir / "VERSION.json").write_text(
        json.dumps(
            {
                "version": "v1.1.2",
                "released_at": "2026-04-24T07:27:01Z",
                "dataset_count": 2,
                "field_count": 4,
            }
        ),
        encoding="utf-8",
    )

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
    )

    assert result["status"] == "planned"
    assert result["metadata_source"] == "published_bundle"
    assert result["model_view"]["dataset_name_zh"] == "SP广告数据集"


def test_placeholder_blocked_contract_carries_recovery_command(tmp_path: Path):
    """占位/未就绪元数据打回时，合同必须携带可直接执行的恢复命令与中文指引。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "1.2.4", "data_state": "placeholder"}),
        encoding="utf-8",
    )

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
    )

    assert result["status"] == "blocked"
    assert result["model_view"]["next_action"] == "refresh_authorized_metadata"
    assert result["model_view"]["recovery_command"] == "opscli skills upgrade ops-dataset-query"
    assert result["model_view"]["recovery_hint_zh"]


def test_empty_bundle_without_data_state_stays_blocked(tmp_path: Path):
    """无 data_state 且索引文件仅有表头的空包/坏包不得被误判为就绪。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"version": "v0.0.0", "dataset_count": 0}),
        encoding="utf-8",
    )
    # 空包特征：核心索引 CSV 只有表头、没有任何数据行
    for name in ("datasets.csv", "dataset_fields.csv"):
        header = (data_dir / name).read_text(encoding="utf-8").split("\n")[0]
        (data_dir / name).write_text(header + "\n", encoding="utf-8")

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
    )

    assert result["status"] == "blocked"
    assert result["model_view"]["recovery_command"]


def test_fallback_data_dir_takes_over_readonly_mount(tmp_path: Path, monkeypatch):
    """只读挂载快照场景（沙箱实测）：升级成功但主目录仍占位时，接管 opscli 实际安装位置的就绪数据。"""
    # 主目录：模拟只读挂载的占位包（升级无法写入）
    primary = tmp_path / "mounted" / "data"
    _write_ready_metadata(primary)
    (primary / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "1.3.1", "data_state": "placeholder"}),
        encoding="utf-8",
    )
    # opscli 实际安装位置：cwd/.claude/skills/...（升级真实写入点），数据就绪
    workdir = tmp_path / "cwd"
    fallback = workdir / ".claude" / "skills" / "ops-dataset-query" / "data"
    _write_ready_metadata(fallback)
    monkeypatch.chdir(workdir)
    monkeypatch.delenv("OPSCLI_SKILLS_DIR", raising=False)
    # 新流程 fallback 前置：就绪目录已存在时应直接接管、不再发起升级
    def _must_not_upgrade(**_kwargs):
        raise AssertionError("fallback 目录已就绪时不应再发起自动升级")

    monkeypatch.setattr(query_plan, "_try_metadata_upgrade", _must_not_upgrade)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=primary,
        rules_path=RULES_PATH,
        auto_enum=False,
    )

    assert result["status"] == "planned"
    assert result["metadata_source"] == "skill_local+fallback_dir"
    assert result["model_view"]["dataset_name_zh"] == "SP广告数据集"


def test_auto_upgrade_completed_within_grace_continues_planning(tmp_path: Path, monkeypatch):
    """升级在前台宽限内完成（completed）：同一次调用直接继续规划。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    ready_version = (data_dir / "VERSION.json").read_text(encoding="utf-8")
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "1.3.3", "data_state": "placeholder"}),
        encoding="utf-8",
    )
    calls = []

    def fake_upgrade(**_kwargs):
        # 模拟 opscli skills upgrade 在宽限内完成：把 VERSION.json 写回就绪形状
        calls.append(1)
        (data_dir / "VERSION.json").write_text(ready_version, encoding="utf-8")
        return "completed"

    # 隔离环境泄漏：本机可能存在真实的 opscli 安装目录，禁用 fallback 候选
    monkeypatch.setattr(query_plan, "_fallback_ready_data_dir", lambda _primary: None)
    monkeypatch.setattr(query_plan, "_try_metadata_upgrade", fake_upgrade)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert calls == [1]
    assert result["status"] == "planned"
    assert result["metadata_source"] == "skill_local"


def test_auto_upgrade_in_progress_returns_wait_and_rerun_contract(tmp_path: Path, monkeypatch):
    """升级超出宽限转后台续跑（in_progress）：立即返回等待重跑指引，守住 30 秒窗口。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "1.3.3", "data_state": "placeholder"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(query_plan, "_fallback_ready_data_dir", lambda _primary: None)
    monkeypatch.setattr(query_plan, "_try_metadata_upgrade", lambda **_kwargs: "in_progress")

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "blocked"
    assert result["model_view"]["recovery_state"] == "refresh_in_progress"
    # 恢复命令是「sleep + 原样重跑」合并的一条命令，模型无需自行升级
    assert result["model_view"]["recovery_command"].startswith("sleep 25 && ")
    assert "后台" in result["model_view"]["recovery_hint_zh"]


def test_main_error_json_carries_next_action(monkeypatch, capsys):
    """组合入口异常必须输出 stdout 错误 JSON，并带 retryable 与中文下一步指引。"""

    def boom(*_args, **_kwargs):
        raise RuntimeError("metadata_snapshot_changed")

    monkeypatch.setattr(query_plan, "build_model_query_plan", boom)

    exit_code = query_plan.main(["任意查询"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())

    assert exit_code == 2
    assert payload["error"] == "metadata_snapshot_changed"
    assert payload["retryable"] is True
    assert "重跑" in payload["next_action_zh"]


def test_platform_enum_component_with_normal_category_is_usable(tmp_path: Path):
    """组件数据集被发布为 dataset_category=normal 时（QA 真实形态），平台枚举流程不得被阻断。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    # 追加平台组件数据集（类目 normal，模拟 QA 的 query_channel_set 发布形态）
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,SP广告数据集,\n"
        "2,ds_inv,库存数据集,normal,0,库存快照数据集,\n"
        "7,ds_channel,查询组件渠道数据集,normal,0,查询组件渠道数据集,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        (data_dir / "dataset_fields.csv").read_text(encoding="utf-8")
        + "7,ds_channel,查询组件渠道数据集,platform_name,平台,f_platform,dimension,,,,,0,0\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_ads,platform_name,平台,ds_channel\n",
        encoding="utf-8",
    )

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS 只看亚马逊SC",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )

    # 不得因组件类目为 normal 而 block_platform_filter_missing_component；
    # 正确走向是「去查权限枚举」并给出组件执行引用
    assert result["model_view"]["next_action"] == "query_platform_permission_enum"
    assert result["model_view"]["platform_filter_state"] == "requires_permission_enum"
    assert result["execution_ref"]["platform_component_alias"] == "ds_channel"
    # P0-3 兜底层：待枚举合同必须内嵌可直接执行的枚举命令与回传指引
    assert "opscli query simple --table-id" in result["execution_ref"]["platform_enum_command"]
    assert result["execution_ref"]["platform_enum_return_hint_zh"]


def test_main_unexpected_error_is_wrapped_not_traceback(monkeypatch, capsys):
    """未预期异常（预期五类之外，如 AttributeError）不得裸 traceback，应包装为 internal_error 错误 JSON。"""

    def boom(*_args, **_kwargs):
        raise AttributeError("SourceSnapshot has no attribute content")

    monkeypatch.setattr(query_plan, "build_model_query_plan", boom)

    exit_code = query_plan.main(["任意查询"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())

    assert exit_code == 2
    assert payload["error"] == "internal_error:AttributeError"
    assert payload["retryable"] is False
    assert payload["next_action_zh"]


# ---------------------------------------------------------------------------
# 第二/三批：合同补全（日期字段/推荐字段/时间口径/模板骨架/澄清弹药）
# ---------------------------------------------------------------------------


def test_contract_carries_date_fields_time_scope_and_template(tmp_path: Path):
    """planned 合同必须无条件带日期字段、时间窗口与预填模板（P0-1a/P0-5/P1-4）。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS 环比上一个7天",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )

    assert result["status"] == "planned"
    # 日期字段无条件输出（用户未点名"日期"）
    date_fields = result["execution_ref"]["date_fields"]
    assert any(item["field_name"] == "date_id" for item in date_fields)
    # 时间口径本地解析：近7天 + 环比对比期，模型可见层带中文描述
    scope = result["execution_ref"]["time_scope"]
    assert scope["is_default"] is False
    assert scope["comparison_type"] == "period_over_period"
    assert "近7天" in result["model_view"]["time_scope_zh"]
    # 模板骨架：预填日期过滤（>=/<= 两行实测形态）与 dataComparison；公式指标不带聚合
    template = result["execution_ref"]["query_template"]
    operators = [item["operator"] for item in template["filters"]]
    assert operators == [">=", "<="]
    assert template["dataComparison"]["field"] == "date_id"
    acos_entry = next(item for item in template["metrics"] if item["field"] == "acos")
    assert "aggregation" not in acos_entry


def test_recommended_fields_when_nothing_named(tmp_path: Path):
    """点名数据集但未点名任何字段时，合同给出推荐字段而非全空（P0-1c）。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "SP广告数据集 近7天整体情况",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )

    assert result["status"] == "clarify_required"
    assert result["model_view"]["pending_confirmations_zh"]
    assert "query_template" not in result["execution_ref"]
    assert result["model_view"]["recommended_metrics"]
    recommended = [
        item
        for item in result["execution_ref"]["metrics"]
        if item.get("selection_source") == "recommended"
    ]
    assert recommended, "推荐指标必须进入 execution_ref 并带 recommended 标注"


def test_clarify_contract_carries_candidate_cards(tmp_path: Path):
    """同名冲突显式点名时，澄清合同必须携带候选卡片供带选项提问（P0-2）。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    # 镜像 QA 真实形态：两行 dataset_name 完全相同（table 52/61 同名场景）
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "52,ds_share_a,用户仪表盘分享明细,normal,0,用户仪表盘分享明细,\n"
        "61,ds_share_b,用户仪表盘分享明细,normal,0,用户仪表盘分享明细(新版),\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "52,ds_share_a,用户仪表盘分享明细,use_count,使用次数,f_uc_a,metric,,,,,0,0\n"
        "52,ds_share_a,用户仪表盘分享明细,share_user,分享用户,f_su_a,dimension,,,,,0,0\n"
        "61,ds_share_b,用户仪表盘分享明细,view_count,查看次数,f_vc_b,metric,,,,,0,0\n",
        encoding="utf-8",
    )

    result = query_plan.build_model_query_plan(
        "查询用户仪表盘分享明细近30天的使用次数",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )

    assert result["status"] == "clarify_required"
    cards = result["model_view"]["dataset_candidates_zh"]
    assert len(cards) == 2
    assert all(card["name_zh"] and card["reason_zh"] for card in cards)
    assert len({card["summary_zh"] for card in cards}) == 2


def test_exact_dataset_identity_does_not_become_platform_filter(tmp_path: Path):
    """数据集名和完整字段标签里的 VC/Walmart 不得变成额外平台筛选。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,vc_report_set,normal,0,VC报告【Manufacturing】,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "1,ds_ads,vc_report_set,wmt_stock,Walmart可售库存,f_wmt,metric,,,,,0,0\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n",
        encoding="utf-8",
    )
    by_name = query_plan.build_model_query_plan(
        "查询VC报告【Manufacturing】最近7天",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    by_field = query_plan.build_model_query_plan(
        "查询 ds_ads 最近7天，字段Walmart可售库存",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    assert by_name["status"] == "clarify_required"
    assert by_name["model_view"]["platform_filter_state"] == "not_requested"
    assert by_field["status"] == "planned"
    assert "Walmart可售库存" in by_field["model_view"]["metrics"]


def test_continuous_chinese_residual_selects_unique_dataset(tmp_path: Path):
    """“查即时销售额”扣除指标词后保留“即时”，可唯一命中即时综合表。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,即时综合数据集,\n"
        "2,ds_inv,库存数据集,normal,0,库存快照数据集,\n",
        encoding="utf-8",
    )
    result = query_plan.build_model_query_plan(
        "查即时销售额",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    assert result["status"] == "clarify_required"
    assert result["model_view"]["dataset_name_zh"] == "即时综合数据集"


def test_natural_duplicate_label_requires_clarification(tmp_path: Path):
    """同中文标签的不同物理字段不得静默绑定第一项；技术 --field 仍可区分。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "1,ds_ads,广告数据集,SPU,SPU,f_spu_a,dimension,,,,,0,0\n"
        "1,ds_ads,广告数据集,spu,SPU,f_spu_b,dimension,,,,,0,0\n",
        encoding="utf-8",
    )
    natural = query_plan.build_model_query_plan(
        "查询 ds_ads 字段SPU 最近7天",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    exact = query_plan.build_model_query_plan(
        "查询 ds_ads 最近7天",
        requested_fields=["spu"],
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    assert natural["status"] == "clarify_required"
    assert natural["model_view"]["ambiguous_field_labels_zh"] == ["SPU"]
    assert exact["status"] == "planned"
    assert exact["execution_ref"]["dimensions"][0]["field_name"] == "spu"


def test_explicit_dataset_still_enforces_external_domain_constraints(tmp_path: Path):
    """alias 精确定表不等于允许忽略名称外明确提出的不兼容业务域。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    result = query_plan.build_model_query_plan(
        "查询 ds_ads 近7天的库存量",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    assert result["status"] == "clarify_required"
    assert "dataset_constraints" in result["model_view"]["clarification_reason_codes"]


def test_unknown_field_gets_similar_suggestions(tmp_path: Path):
    """点名字段拼写偏差时，澄清合同回显未知字段并给近似建议（P0-2/C2）。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    # 追加一个"销售额"指标供近似匹配
    (data_dir / "dataset_fields.csv").write_text(
        (data_dir / "dataset_fields.csv").read_text(encoding="utf-8")
        + "1,ds_ads,广告数据集,sales,销售额,f_sales,metric,,,,,0,0\n",
        encoding="utf-8",
    )

    result = query_plan.build_model_query_plan(
        "SP 广告数据集",
        requested_fields=["销售金额"],
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )

    assert result["status"] == "clarify_required"
    assert result["model_view"]["unknown_requested_fields"] == ["销售金额"]
    suggestions = result["model_view"]["field_suggestions_zh"]
    assert suggestions and "销售额" in suggestions[0]["candidates_zh"]


def test_auto_enum_resolves_platform_in_single_call(tmp_path: Path, monkeypatch):
    """自动枚举（P0-3）：待枚举合同应在一次调用内收敛为 resolved 终版。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,SP广告数据集,\n"
        "7,ds_channel,query_channel_set,query_component,0,查询组件渠道数据集,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        (data_dir / "dataset_fields.csv").read_text(encoding="utf-8")
        + "7,ds_channel,query_channel_set,platform_name,平台,f_platform,dimension,,,,,0,0\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_ads,platform_name,平台,ds_channel\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        query_plan, "_auto_enum_platform_values", lambda *_a, **_k: ["亚马逊SC", "Temu"]
    )

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS 只看亚马逊SC",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=True,
    )

    assert result["model_view"]["platform_filter_state"] == "resolved"
    assert result["execution_ref"]["resolved_platform_values"] == ["亚马逊SC"]
    assert result["execution_ref"]["platform_enum_source"] == "auto_enum_service"


# ---------------------------------------------------------------------------
# time_scope 单元测试（P0-5）
# ---------------------------------------------------------------------------


def test_time_scope_recent_days_with_pop_comparison():
    """近7天 + 环比：窗口含今天、对比期为紧邻上一个等长周期。"""
    from datetime import date

    scope = time_scope.parse("近7天销售额环比", today=date(2026, 7, 13))
    assert (scope["start"], scope["end"]) == ("2026-07-07", "2026-07-13")
    comparison = scope["comparison"]
    assert comparison["type"] == "period_over_period"
    assert (comparison["start"], comparison["end"]) == ("2026-06-30", "2026-07-06")


def test_time_scope_last_week_and_yoy():
    """上周窗口与同比对比（去年同期）。"""
    from datetime import date

    scope = time_scope.parse("上周流量同比", today=date(2026, 7, 13))
    assert (scope["start"], scope["end"]) == ("2026-07-06", "2026-07-12")
    assert scope["comparison"]["type"] == "yoy"
    assert scope["comparison"]["start"] == "2025-07-06"


def test_time_scope_default_is_disclosed():
    """未识别时间表述时给默认近30天并标记 is_default（必须披露）。"""
    from datetime import date

    scope = time_scope.parse("看看销售情况", today=date(2026, 7, 13))
    assert scope["is_default"] is True
    assert (scope["start"], scope["end"]) == ("2026-06-14", "2026-07-13")


def test_time_scope_absolute_range_quarter_and_year():
    """绝对范围、自然季度和自然年必须确定性解析，不回退近30天。"""
    from datetime import date

    absolute = time_scope.parse("查询2026-07-01至2026-07-15销售额", today=date(2026, 7, 16))
    quarter = time_scope.parse("复盘2026Q2广告费", today=date(2026, 7, 16))
    last_quarter = time_scope.parse("上季度库存", today=date(2026, 7, 16))
    year = time_scope.parse("2025年全年销售", today=date(2026, 7, 16))
    assert (absolute["start"], absolute["end"], absolute["is_default"]) == (
        "2026-07-01", "2026-07-15", False,
    )
    assert (quarter["start"], quarter["end"]) == ("2026-04-01", "2026-06-30")
    assert (last_quarter["start"], last_quarter["end"]) == ("2026-04-01", "2026-06-30")
    assert (year["start"], year["end"]) == ("2025-01-01", "2025-12-31")


# ---------------------------------------------------------------------------
# run_query 执行器（P0-4）
# ---------------------------------------------------------------------------


def _fake_response(rows, total=None):
    """QA 实测返回形状：行在 data.result.data，总数在 data.result.meta.totalCount。"""
    return {
        "success": True,
        "data": {"result": {"data": rows, "meta": {"totalCount": total or len(rows)}}},
    }


def test_run_query_rejects_comparison_without_main_period(capsys):
    """dataComparison 缺主周期 filters 必须在执行前被拒绝（E1）。"""
    payload = json.dumps(
        {
            "metrics": [{"field": "price", "aggregation": "SUM", "alias": "price"}],
            "filters": [],
            "dataComparison": {"field": "date_id", "startDate": "2026-06-30", "endDate": "2026-07-06"},
        }
    )
    exit_code = run_query.main(
        ["--table-id", "2", "--json", payload, "--unsafe-unbound-plan"]
    )
    out = json.loads(capsys.readouterr().out.strip())
    assert exit_code == 2
    assert out["status"] == "precheck_failed"
    assert "主周期" in out["next_action_zh"]


def test_run_query_rejects_leftover_placeholders(capsys):
    """占位符未替换必须阻断执行（执行前检查第5条代码化）。"""
    payload = json.dumps({"metrics": [{"field": "$AUTHORIZED_METRIC", "alias": "m"}]})
    exit_code = run_query.main(
        ["--table-id", "2", "--json", payload, "--unsafe-unbound-plan"]
    )
    out = json.loads(capsys.readouterr().out.strip())
    assert exit_code == 2
    assert out["status"] == "precheck_failed"
    assert "占位符" in out["next_action_zh"]


def test_run_query_requires_plan_binding(capsys):
    """正式执行缺少规划器合同必须在调用 opscli 前阻断。"""
    payload = json.dumps({"metrics": [{"field": "price", "alias": "price"}]})
    exit_code = run_query.main(["--table-id", "2", "--json", payload])
    out = json.loads(capsys.readouterr().out.strip())
    assert exit_code == 2
    assert out["status"] == "precheck_failed"
    assert "规划器绑定" in out["next_action_zh"]


def test_run_query_rejects_table_and_field_outside_plan(capsys):
    """tableId 或字段超出 execution_ref 时必须硬拒绝。"""
    plan = {
        "contract": "query_plan_model_contract_v2",
        "status": "planned",
        "execution_ref": {
            "table_id": "2",
            "dimensions": [{"field_name": "country"}],
            "metrics": [{"field_name": "price"}],
            "date_fields": [{"field_name": "date_id"}],
            "query_template": {},
        },
    }
    bad_table = run_query.main(
        [
            "--table-id", "3", "--json", json.dumps({"metrics": []}),
            "--plan-json", json.dumps(plan),
        ]
    )
    table_out = json.loads(capsys.readouterr().out.strip())
    bad_field = run_query.main(
        [
            "--table-id", "2",
            "--json", json.dumps({"metrics": [{"field": "secret_metric"}]}),
            "--plan-json", json.dumps(plan),
        ]
    )
    field_out = json.loads(capsys.readouterr().out.strip())
    assert bad_table == 2 and "不一致" in table_out["next_action_zh"]
    assert bad_field == 2 and "未授权字段" in field_out["next_action_zh"]


def test_run_query_order_fallback_requeries_and_resorts(tmp_path: Path, monkeypatch, capsys):
    """服务端排序未生效 + limit 场景：必须放大窗口重查、本地排序取前N并披露（D1）。"""
    calls = []

    def fake_run(table_id, payload):
        calls.append(dict(payload))
        if len(calls) == 1:
            # 首查：声明 DESC 但返回乱序（模拟服务端吞排序）
            return _fake_response(
                [{"country": "A", "price": 5}, {"country": "B", "price": 9}], total=4
            )
        # 重查：放大窗口后的全量行
        return _fake_response(
            [
                {"country": "A", "price": 5},
                {"country": "B", "price": 9},
                {"country": "C", "price": 7},
                {"country": "D", "price": 3},
            ],
            total=4,
        )

    monkeypatch.setattr(run_query, "_run_opscli", fake_run)
    payload = json.dumps(
        {
            "dimensions": [{"field": "country", "alias": "country"}],
            "metrics": [{"field": "price", "aggregation": "SUM", "alias": "price"}],
            "orderBy": [{"field": "price", "desc": True}],
            "limit": 2,
        }
    )
    exit_code = run_query.main(
        ["--table-id", "2", "--json", payload, "--result-dir", str(tmp_path), "--no-evidence", "--unsafe-unbound-plan"]
    )
    out = json.loads(capsys.readouterr().out.strip())

    assert exit_code == 0
    assert len(calls) == 2, "排序未生效时必须放大窗口重查一次"
    assert calls[1]["limit"] == 6  # limit*3
    # desc 布尔旧形态被归一为 direction 形态
    assert calls[0]["orderBy"] == [{"field": "price", "direction": "DESC"}]
    assert out["disclosures"]["order_fallback"]["order_fallback_applied"] is True
    assert [row["price"] for row in out["preview_rows"]] == [9, 7]


def test_run_query_ok_path_discloses_effective_order(tmp_path: Path, monkeypatch, capsys):
    """排序已生效时正常输出预览与生效披露，不触发兜底。"""
    monkeypatch.setattr(
        run_query,
        "_run_opscli",
        lambda table_id, payload: _fake_response(
            [{"country": "B", "price": 9}, {"country": "C", "price": 7}], total=2
        ),
    )
    payload = json.dumps(
        {
            "metrics": [{"field": "price", "aggregation": "SUM", "alias": "price"}],
            "orderBy": [{"field": "price", "direction": "DESC"}],
            "limit": 5,
        }
    )
    plan = json.dumps(
        {
            "contract": "query_plan_model_contract_v2",
            "status": "planned",
            "execution_ref": {
                "table_id": "2",
                "dimensions": [],
                "metrics": [{"field_name": "price"}],
                "query_template": {},
            },
        }
    )
    exit_code = run_query.main(
        [
            "--table-id", "2", "--json", payload,
            "--plan-json", plan,
            "--result-dir", str(tmp_path), "--no-evidence",
        ]
    )
    out = json.loads(capsys.readouterr().out.strip())

    assert exit_code == 0
    assert "order_fallback" not in out["disclosures"]
    assert "排序已生效" in out["disclosures"]["order_disclosure_zh"]
    assert out["disclosures"]["row_count_returned"] == 2


# ---------------------------------------------------------------------------
# Task 4: query_plan 投影默认条件（R5）
# ---------------------------------------------------------------------------


def test_query_plan_projects_default_filters(tmp_path: Path):
    """配置了 filter_config 的数据集：规划结果必须携带默认条件与中文披露。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata_with_filter_config(data_dir)  # 新 fixture：ds_ads 的 date_type 配 required QUARTER

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 近7天 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "planned"
    defaults = result["execution_ref"]["default_filters"]
    assert defaults[0]["field_name"] == "date_type"
    assert defaults[0]["operator"] == "equals"
    assert defaults[0]["values"] == ["QUARTER"]
    assert defaults[0]["type"] == "required"
    # 用户可见层中文披露
    assert any("QUARTER" in text for text in result["model_view"]["default_filters_zh"])
    # 回答合同强制披露
    assert any("默认条件" in text for text in result["answer_contract"]["required_disclosures_zh"])
    # query_template 不预填默认条件：服务端是唯一权威注入方，模型不得手动加入
    # 注：date_type 可能作为时间维度合法出现在日期范围过滤（>=/<= scope），
    # 但不应出现 equals/in + QUARTER 这类枚举型默认条件
    template_filters = result["execution_ref"]["query_template"].get("filters", [])
    assert not any(
        f.get("field") == "date_type" and f.get("value") == "QUARTER"
        for f in template_filters
    ), "query_template.filters 不应含 date_type=QUARTER 默认条件（由服务端自动应用）"


def test_query_plan_no_default_filters_key_when_unconfigured(tmp_path: Path):
    """未配置默认条件：execution_ref 不带 default_filters 键，行为与现状一致。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS", data_dir=data_dir, rules_path=RULES_PATH,
    )
    assert "default_filters" not in result["execution_ref"]
    assert "default_filters_zh" not in result["model_view"]
    # 未配置时回答合同不得注入默认条件披露
    assert not any(
        "默认条件" in text
        for text in result["answer_contract"]["required_disclosures_zh"]
    )


def test_model_contract_schema_accepts_projected_default_filters(tmp_path: Path):
    """严格 Schema 必须覆盖规划器已投影的默认条件两处字段。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata_with_filter_config(data_dir)
    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_enum=False,
    )
    schema = json.loads((SKILL_ROOT / "data" / "query_plan.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(result)


def test_authorized_query_labels_are_scoped_to_selected_dataset(tmp_path: Path):
    """外部数据集字段标签不得污染当前表，更不能产生无 field_name 的假执行字段。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)
    (data_dir / "dataset_fields.csv").write_text(
        (data_dir / "dataset_fields.csv").read_text(encoding="utf-8")
        + "2,ds_inv,库存数据集,days_sold,已售天数,f_days_sold,metric,,,,,0,0\n",
        encoding="utf-8",
    )
    result = query_plan.build_model_query_plan(
        "SP 广告数据集 已售天数",
        data_dir=data_dir,
        rules_path=RULES_PATH,
        auto_upgrade=False,
        auto_enum=False,
    )
    assert "已售天数" not in result["model_view"]["metrics"]
    assert all(
        item.get("field_name") != "days_sold"
        for item in result["execution_ref"].get("metrics", [])
    )


def test_explicit_fields_survive_label_dedup_and_containment():
    """显式物理字段不因同标签或长短标签包含关系从 execution_ref 消失。"""
    fields = [
        {"field_name": "sales", "verbose_name": "销售额", "selection_source": "explicit"},
        {
            "field_name": "ad_sales",
            "verbose_name": "广告销售额",
            "selection_source": "explicit",
        },
        {
            "field_name": "sales_copy",
            "verbose_name": "销售额",
            "selection_source": "explicit",
        },
    ]
    selected = query_plan._longest_unique_labels(fields)
    assert [item["field_name"] for item in selected] == [
        "sales",
        "ad_sales",
        "sales_copy",
    ]
