"""ops-dataset-query 低调用一体化执行入口测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


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

import query_flow  # noqa: E402


def test_skill_version_matches_version_json():
    """SKILL.md frontmatter 版本须与 data/VERSION.json 一致。

    原先此断言把版本号硬编码为字面量（写作 1.3.14，而 SKILL.md 与 VERSION.json
    实为 1.3.15），既拦不住真正该拦的「两处版本源分叉」，又会在每次正常升版时
    误报失败。改为断言两个版本源一致——这才是需要守住的不变量。
    """
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    declared = json.loads((SKILL_ROOT / "data" / "VERSION.json").read_text(encoding="utf-8"))
    version = str(declared["version"])

    assert f"version: {version}" in text, (
        f"SKILL.md frontmatter 版本与 VERSION.json({version}) 不一致"
    )


def test_skill_defaults_to_bounded_single_flow_entry():
    """Skill 正常路径必须固定为一体化入口，并禁止重复探查与手工改计划。"""
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "正常路径工具调用预算" in text
    assert "最多 3 次工具调用" in text
    assert "非正常路径最多 7 次" in text
    assert 'python3 scripts/query_flow.py "$USER_REQUEST"' in text
    assert "禁止为了“确认环境/字段/语法”调用 `opscli query catalog`" in text
    assert "禁止手工修改 plan" in text
    assert "`query_plan.py` + `run_query.py` 不是 Agent 的规划器正常路径" in text


def test_skill_allows_fallback_only_on_objective_failure():
    """规划器由硬性规定改为优先路径后，降级入口必须仍受客观失败条件约束。

    守住两条不变量：① 降级触发条件被显式列举，Agent 不能凭主观判断绕过规划器；
    ② 主观理由被明确排除，避免"优先使用"被读成"可选使用"。
    """
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "**CLI 主线的优先入口是 `query_flow.py`。**" in text
    assert "### 降级触发条件（满足其一即可降级）" in text
    assert "**不构成降级理由**" in text
    assert "主观觉得规划器不合适" in text
    # 降级态的字段来源护栏不得随触发条件一起放宽
    assert "仍禁止凭记忆手拼" in text


def test_skill_defines_multi_dataset_excel_orchestration_contract():
    """多表 Excel 请求必须保留逐表时间、全量和 LEFT JOIN 语义。

    本次真实异常把库龄“超6月”错当自然月，又把“未售出”反向改成销量大于 0。
    这些不是单字段解析问题，而是多表编排边界；用静态合同测试防止后续精简文档时
    再删除关键口径。
    """
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "多数据集计算与 Excel 交付" in text
    assert "181 天以上" in text
    assert "执行当天" in text
    assert "LEFT JOIN" in text
    assert "无销售记录按 `order_qty=0`" in text
    assert "禁止改写成 `order_qty>0`" in text
    assert "`truncated=false`" in text
    assert "每张快照表独立" in text


def test_query_flow_plans_and_executes_once(monkeypatch, tmp_path: Path):
    """无歧义路径应各调用一次规划器与执行器，且不传手工 payload。"""
    calls = {"plan": 0, "run": 0}
    plan = {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "data_state": "ready",
        "metadata_version": "1.3.14",
        "status": "planned",
        "model_view": {},
        "answer_contract": {},
        "execution_ref": {
            "user_visible": False,
            "table_id": "1",
            "query_template": {"tableId": "1", "dimensions": [], "metrics": []},
        },
    }

    def fake_plan(*_args, **_kwargs):
        calls["plan"] += 1
        return plan

    def fake_run(argv):
        calls["run"] += 1
        assert "--plan-file" in argv
        assert "--json" not in argv
        assert "--json-file" not in argv
        return 0

    monkeypatch.setattr(query_flow.query_plan, "build_model_query_plan", fake_plan)
    monkeypatch.setattr(query_flow.run_query, "main", fake_run)

    exit_code = query_flow.execute_flow(
        "查询2026年6月销量",
        result_dir=tmp_path,
    )

    assert exit_code == 0
    assert calls == {"plan": 1, "run": 1}


def test_query_flow_returns_clarification_without_execution(
    monkeypatch, capsys, tmp_path: Path
):
    """澄清态只返回规划合同，不得尝试正式查询。"""
    plan = {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "data_state": "ready",
        "metadata_version": "1.3.14",
        "status": "clarify_required",
        "model_view": {"next_action": "ask_user_for_clarification"},
        "answer_contract": {},
        "execution_ref": {"user_visible": False},
    }
    monkeypatch.setattr(
        query_flow.query_plan,
        "build_model_query_plan",
        lambda *_args, **_kwargs: plan,
    )

    def must_not_run(_argv):
        raise AssertionError("澄清态不得调用执行器")

    monkeypatch.setattr(query_flow.run_query, "main", must_not_run)

    exit_code = query_flow.execute_flow("查询运营数据", result_dir=tmp_path)
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "clarify_required"
