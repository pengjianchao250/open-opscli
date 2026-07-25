#!/usr/bin/env python3
"""规划器内核化回归对拍工具（安全网）。

对同一批代表性请求，分别运行：
- 旧 Skill 规划器：scripts/query_plan.py（读 ~/.claude/skills 已就绪 CSV，经 fallback）
- 新内核规划器：opscli query plan（读后端 query-metadata?include_all_fields=1）

比对规划合同的关键字段是否一致，作为迁移未改变规划语义的安全网。
只比对 query plan（不执行取数），关注 model_view 与 execution_ref 的稳定关键字段。

用法：
    OPSCLI_OPS_URL="http://ops.cm/api" OPSCLI_OPS_SYSTEM_URL="http://ops.cm" \
        python3 scripts/regression/planner_parity.py

需本地登录态（opscli auth token status 显示已登录）与本地后端可达。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# 代表性请求集：覆盖 明确数据集/相对时间、需澄清、平台枚举、环比、快照指标、chart_uuid
CASES: list[tuple[str, str]] = [
    ("explicit_relative_time", "查询各平台销售额 近7天"),
    ("vague_clarify", "帮我查一下数据"),
    ("platform_enum", "查询亚马逊平台的销售额 近7天"),
    ("period_over_period", "查询销售额 本月 环比"),
    ("snapshot_metric", "查询各仓库库存量 昨天"),
    ("chart_uuid", "查询图表 12345678-abcd-1234-abcd-1234567890ab 的数据"),
]

# 仓库根目录（本文件位于 scripts/regression/）
REPO_ROOT = Path(__file__).resolve().parents[2]
OLD_SCRIPT = REPO_ROOT / "opscli" / "skills" / "templates" / "ops-dataset-query" / "scripts" / "query_plan.py"
GOLDEN_DIR = REPO_ROOT / "tests" / "query" / "planner" / "golden"


def _run_old(request: str, env: dict) -> dict:
    """运行旧 Skill 规划器，返回模型合同 dict。"""
    proc = subprocess.run(
        [sys.executable, str(OLD_SCRIPT), request],
        cwd=str(OLD_SCRIPT.parent),
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )
    return json.loads(proc.stdout[proc.stdout.index("{"):])


def _run_new(request: str, env: dict) -> dict:
    """运行新内核规划器（opscli query plan），返回解包后的模型合同 dict。"""
    proc = subprocess.run(
        [sys.executable, "-m", "opscli.cli", "query", "plan", request],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )
    wrapper = json.loads(proc.stdout[proc.stdout.index("{"):])
    if not wrapper.get("success"):
        raise RuntimeError(f"新规划器失败：{wrapper.get('error')}")
    return wrapper["data"]


def _key_fields(contract: dict) -> dict:
    """抽取用于对拍的关键字段（表述性差异不纳入，只看语义决策字段）。"""
    mv = contract.get("model_view") or {}
    er = contract.get("execution_ref") or {}
    time_scope = er.get("time_scope") or {}
    return {
        "status": contract.get("status"),
        "query_mode": contract.get("query_mode"),
        "dataset_name_zh": mv.get("dataset_name_zh"),
        "dimensions": mv.get("dimensions"),
        "metrics": mv.get("metrics"),
        "platform_filter_state": mv.get("platform_filter_state"),
        "next_action": mv.get("next_action"),
        "clarification_reason_codes": sorted(mv.get("clarification_reason_codes") or []),
        "exec_dataset_alias": er.get("dataset_alias"),
        # table_id 统一按字符串比对语义身份：新路径来自后端 JSON 为 int、
        # 旧 CSV 路径为字符串 "1"，两者指向同一张表（新 int 更规范），
        # 仅类型归一差异不计为语义回归。
        "exec_table_id": None if er.get("table_id") is None else str(er.get("table_id")),
        "exec_dim_fields": [d.get("field") for d in (er.get("dimensions") or [])],
        "exec_metric_fields": [m.get("field") for m in (er.get("metrics") or [])],
        "time_scope_start": time_scope.get("start"),
        "time_scope_end": time_scope.get("end"),
        "time_comparison_type": time_scope.get("comparison_type"),
    }


def _diff(old: dict, new: dict) -> list[str]:
    """逐字段比对，返回差异描述列表（空列表表示一致）。"""
    diffs = []
    for key in old:
        if old[key] != new.get(key):
            diffs.append(f"  {key}: 旧={old[key]!r} | 新={new.get(key)!r}")
    return diffs


def main() -> int:
    import os

    env = dict(os.environ)
    env.setdefault("OPSCLI_OPS_URL", "http://ops.cm/api")
    env.setdefault("OPSCLI_OPS_SYSTEM_URL", "http://ops.cm")

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    consistent = 0
    for case_id, request in CASES:
        total += 1
        try:
            old = _run_old(request, env)
            new = _run_new(request, env)
        except Exception as exc:  # noqa: BLE001 对拍工具，异常需可见
            print(f"[{case_id}] 采集失败：{exc}")
            continue
        old_key = _key_fields(old)
        new_key = _key_fields(new)
        # 落盘黄金样例（新规划器关键字段）供后续回归复用
        (GOLDEN_DIR / f"{case_id}.json").write_text(
            json.dumps({"request": request, "new": new_key, "old": old_key}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        diffs = _diff(old_key, new_key)
        if not diffs:
            consistent += 1
            print(f"[{case_id}] ✅ 一致  status={new_key['status']} dataset={new_key['dataset_name_zh']!r}")
        else:
            print(f"[{case_id}] ⚠️ 差异 ({len(diffs)} 项):")
            for line in diffs:
                print(line)
    print(f"\n对拍汇总：{consistent}/{total} 一致；黄金样例已写入 {GOLDEN_DIR}")
    return 0 if consistent == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
