"""route_intent.py 的单元测试。

route_intent.py 是一个独立脚本，通过将 scripts 目录插入 sys.path 来导入。
测试依赖 data/ 目录中已落地的 intent_taxonomy.yml 和 dataset_profiles.yml（Task 1 完成后才能通过）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# 脚本所在目录（绝对路径）
SKILL_ROOT = (
    Path(__file__).parent.parent.parent
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
DATA_DIR = SKILL_ROOT / "data"

# 将 scripts/ 加入 sys.path，以便直接 import route_intent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import route_intent  # noqa: E402 — 必须在 sys.path 修改之后导入


@pytest.fixture(scope="module")
def check_data_ready():
    """确保 data_state=ready，否则跳过所有依赖数据文件的测试。"""
    version_file = DATA_DIR / "VERSION.json"
    if not version_file.exists():
        pytest.skip("VERSION.json 不存在，请先完成 Task 1")
    data = json.loads(version_file.read_text(encoding="utf-8"))
    if data.get("data_state") != "ready":
        pytest.skip("data_state 不是 ready，请先完成 Task 1")


# ──────────────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────────────

def _route(query: str, top_n: int = 3) -> dict:
    return route_intent.route(query, data_dir=DATA_DIR, top_n=top_n)


# ──────────────────────────────────────────────────────────────────────────────
# 测试：账单销售意图
# billing_sales_review trigger_keywords 含 "月度"、"复盘" 等长周期词
# ──────────────────────────────────────────────────────────────────────────────

def test_billing_sales_top1(check_data_ready):
    """月度复盘关键词应命中 billing_sales_review 意图作为 top1。"""
    result = _route("月度各部门销售复盘")
    top = result["top_results"]
    assert len(top) > 0, "应至少返回一个候选"
    assert top[0]["intent_id"] == "billing_sales_review"


def test_billing_sales_is_direct_intent(check_data_ready):
    """billing_sales_review 路由模式应为 direct_intent，execution_alias 不为空。"""
    result = _route("月度销售复盘趋势分析")
    ids = [r["intent_id"] for r in result["top_results"]]
    assert "billing_sales_review" in ids
    billing = next(r for r in result["top_results"] if r["intent_id"] == "billing_sales_review")
    assert billing["routing_status"] == "direct_intent"
    assert billing["execution_alias"] is not None


# ──────────────────────────────────────────────────────────────────────────────
# 测试：即时销售 embedded_intent 映射
# realtime_sales_monitoring 无独立数据集，应跳转到即时综合数据集
# ──────────────────────────────────────────────────────────────────────────────

def test_realtime_sales_embedded_intent(check_data_ready):
    """即时销售应映射到即时综合数据集（embedded_intent）。"""
    result = _route("今日实时销售监控")
    realtime = next(
        (r for r in result["top_results"] if r["intent_id"] == "realtime_sales_monitoring"),
        None,
    )
    assert realtime is not None, "应命中 realtime_sales_monitoring 意图"
    assert realtime["routing_status"] == "embedded_intent"
    assert realtime["execution_alias"] is not None, "embedded_intent 必须有 execution_alias"
    # 实际执行数据集不应是即时销售数据集本身（其无独立入口）
    assert realtime["execution_dataset"] != realtime["primary_dataset"]


# ──────────────────────────────────────────────────────────────────────────────
# 测试：澄清触发
# amazon_sp_ads_detail 的 clarify_when 包含"投放词"，query 包含该词应触发
# ──────────────────────────────────────────────────────────────────────────────

def test_sp_word_requires_clarification(check_data_ready):
    """SP广告 + 投放词查询应触发澄清（SP广告数据集不含词组数据）。"""
    result = _route("SP广告关键词投放词效果分析")
    assert not result["fallback_needed"], "应找到至少一个候选意图"
    any_clarification = any(r["requires_clarification"] for r in result["top_results"])
    assert any_clarification, "SP广告+投放词查询应触发至少一次澄清"


# ──────────────────────────────────────────────────────────────────────────────
# 测试：无关输入回退
# ──────────────────────────────────────────────────────────────────────────────

def test_unrelated_query_fallback(check_data_ready):
    """完全无关的输入应返回 fallback_needed=True 或空结果。"""
    result = _route("今天天气怎么样")
    assert result["fallback_needed"] is True or len(result["top_results"]) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 测试：top_n 限制
# ──────────────────────────────────────────────────────────────────────────────

def test_top_n_limits_results(check_data_ready):
    """top_n 参数应严格限制返回数量。"""
    result = _route("销售广告综合数据", top_n=1)
    assert len(result["top_results"]) <= 1


def test_top_n_default_three(check_data_ready):
    """默认 top_n=3，结果不超过 3 个。"""
    result = _route("广告ACOS分析")
    assert len(result["top_results"]) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# 测试：返回字段完整性
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_KEYS = {
    "intent_id",
    "intent_name",
    "primary_dataset",
    "execution_dataset",
    "execution_alias",
    "table_id",
    "confidence",
    "matched_keywords",
    "routing_status",
    "requires_clarification",
    "clarification_reasons",
    "avoid_when",
    "hard_constraints",
}


def test_result_has_required_fields(check_data_ready):
    """每个候选结果必须包含所有约定字段。"""
    result = _route("SP广告ACOS分析")
    for item in result["top_results"]:
        missing = REQUIRED_KEYS - set(item.keys())
        assert not missing, f"结果缺少字段: {missing}"


def test_confidence_in_range(check_data_ready):
    """confidence 必须在 [0.0, 1.0] 范围内。"""
    result = _route("月度销售额趋势")
    for item in result["top_results"]:
        assert 0.0 <= item["confidence"] <= 1.0, f"confidence 超出范围: {item['confidence']}"


def test_routing_status_valid_values(check_data_ready):
    """routing_status 只能是 direct_intent 或 embedded_intent。"""
    result = _route("综合运营销售广告库存监控")
    valid = {"direct_intent", "embedded_intent"}
    for item in result["top_results"]:
        assert item["routing_status"] in valid


# ──────────────────────────────────────────────────────────────────────────────
# 测试：CLI 接口（通过 subprocess 调用，验证主入口正常）
# ──────────────────────────────────────────────────────────────────────────────

def test_cli_entrypoint_returns_json(check_data_ready):
    """命令行入口应输出合法 JSON。"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "route_intent.py"), "月度各部门销售复盘"],
        capture_output=True,
        text=True,
        cwd=str(SKILL_ROOT),
    )
    assert result.returncode == 0, f"脚本退出码非0: {result.stderr}"
    data = json.loads(result.stdout)
    assert "top_results" in data
    assert "fallback_needed" in data
