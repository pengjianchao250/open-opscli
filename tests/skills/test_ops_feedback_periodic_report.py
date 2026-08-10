"""反馈周报、月报和处置指标契约测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


SCRIPT_PATH = Path(
    "opscli/skills/templates/ops-feedback-query/scripts/periodic_feedback_report.py"
)


def _load_script() -> ModuleType:
    """从 Skill 模板加载周期报告脚本。"""
    spec = importlib.util.spec_from_file_location("ops_feedback_periodic_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_daily_run(
    project_root: Path,
    day: str,
    *,
    problems: list[dict],
    statuses: dict[str, int],
) -> None:
    """写入一份已完成日报快照。"""
    run_id = f"daily-{day}-insight"
    report_root = project_root / "output" / "feedback-query"
    run_dir = report_root / "runs" / run_id
    run_dir.mkdir(parents=True)
    problem_count = sum(statuses.values())
    clusters = {
        "schema_version": "1.0",
        "run_id": run_id,
        "report_type": "daily",
        "period": {
            "label": day,
            "date_from": f"{day} 00:00:00",
            "date_to": f"{day} 23:59:59",
        },
        "base_metrics": {
            "feedback_count": problem_count,
            "problem_feedback_count": problem_count,
            "failed_call_count": problem_count,
            "feedback_types": {"bug": problem_count},
            "problem_severities": {"high": problem_count},
            "problem_sources": {"mcp": problem_count},
            "problem_statuses": statuses,
        },
        "problems": problems,
        "modules": [],
        "model": {"provider": "codex_app", "model": "scheduled-codex"},
    }
    (run_dir / "clusters.json").write_text(
        json.dumps(clusters, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "report_type": "daily",
        "generated_at": f"{day}T01:00:00Z",
        "finished_at": f"{day}T01:01:00Z",
        "status": "success",
        "analysis_status": "success",
        "execution_status": "success",
        "period": clusters["period"],
        "insight": {"status": "success"},
        "publication": {"status": "success"},
        "artifacts": {"clusters": f"runs/{run_id}/clusters.json"},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


def _problem(module: str, key: str, count: int, *, priority: str = "P1") -> dict:
    """生成日报问题簇测试数据。"""
    return {
        "module": module,
        "problem_key": key,
        "problem_category": "代码缺陷",
        "problem_summary": f"{module}-{key}",
        "current_count": count,
        "affected_users": count,
        "severity": "high",
        "priority": priority,
        "priority_score": 70,
        "recommended_work": f"修复 {key}",
        "confidence": 0.95,
        "needs_review": False,
        "sample_feedback_uuids": [f"{key}-{count}"],
    }


def test_weekly_report_aggregates_snapshots_and_disposition_metrics(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    """周报应对比相邻七天，并输出覆盖率、复发和处置快照指标。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)

    _write_daily_run(
        project_root,
        "2026-07-10",
        problems=[_problem("query", "field_not_found", 1)],
        statuses={"new": 1},
    )
    _write_daily_run(
        project_root,
        "2026-07-11",
        problems=[_problem("auth", "legacy_login", 1, priority="P2")],
        statuses={"resolved": 1},
    )
    _write_daily_run(
        project_root,
        "2026-07-14",
        problems=[_problem("query", "field_not_found", 2)],
        statuses={"new": 1, "resolved": 1},
    )
    _write_daily_run(
        project_root,
        "2026-07-16",
        problems=[_problem("query", "field_not_found", 1)],
        statuses={"triaged": 1},
    )
    _write_daily_run(
        project_root,
        "2026-07-20",
        problems=[_problem("auth", "token_refresh", 1, priority="P2")],
        statuses={"resolved": 1},
    )

    exit_code = module.main(
        ["--report-type", "weekly", "--period-end", "2026-07-20"]
    )
    output = json.loads(capsys.readouterr().out)
    metrics = json.loads(Path(output["metrics"]).read_text(encoding="utf-8"))
    markdown = Path(output["output"]).read_text(encoding="utf-8")

    assert exit_code == 0
    assert metrics["period"] == {"date_from": "2026-07-14", "date_to": "2026-07-20"}
    assert metrics["coverage"] == {"actual_days": 3, "expected_days": 7}
    assert metrics["comparison_coverage"] == {"actual_days": 2, "expected_days": 7}
    assert metrics["disposition"] == {
        "new": 1,
        "triaged": 1,
        "processing": 0,
        "resolved": 2,
        "rejected": 0,
        "unknown": 0,
        "triage_rate": 75.0,
        "resolution_rate": 50.0,
        "status_coverage_rate": 100.0,
    }
    assert metrics["problem_lifecycle"] == {
        "new": 1,
        "persistent": 1,
        "not_seen_again": 1,
        "recurring": 1,
    }
    query_problem = next(
        item for item in metrics["problems"] if item["problem_key"] == "field_not_found"
    )
    assert query_problem["occurrence_count"] == 3
    assert query_problem["active_days"] == 2
    assert query_problem["first_seen"] == "2026-07-14"
    assert query_problem["last_seen"] == "2026-07-16"
    assert query_problem["affected_user_days"] == 3
    assert query_problem["priority_reasons"] == [
        "severity:high",
        "occurrences:3",
        "active_days:2",
        "affected_user_days:3",
    ]
    assert "# 反馈周报（2026-07-14 至 2026-07-20）" in markdown
    assert "日报快照口径" in markdown
    assert "## 二、管理摘要" in markdown
    assert "## 三、重点模块" in markdown
    assert "## 四、根因分布" in markdown
    assert "## 五、重复问题证据" in markdown
    assert "## 六、重点风险" in markdown
    assert "## 七、治理工作建议" in markdown
    assert "## 八、周期对比" in markdown
    assert "## 附录：结构化明细" in markdown
    assert "<details>" in markdown
    assert "对比期数据覆盖仅 2/7 天" in markdown
    assert "query-field_not_found：3 次，活跃 2 天" in markdown
    assert "按确定性优先级和发生次数排序" in markdown
    assert Path(output["manifest"]).exists()


def test_monthly_report_uses_natural_month_and_expected_name(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    """月报必须使用自然月，不得用滚动 30 天代替。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _write_daily_run(
        project_root,
        "2026-02-28",
        problems=[_problem("query", "field_not_found", 1)],
        statuses={"new": 1},
    )
    _write_daily_run(
        project_root,
        "2026-03-01",
        problems=[_problem("query", "field_not_found", 1)],
        statuses={"resolved": 1},
    )

    exit_code = module.main(["--report-type", "monthly", "--month", "2026-03"])
    output = json.loads(capsys.readouterr().out)
    metrics = json.loads(Path(output["metrics"]).read_text(encoding="utf-8"))

    assert exit_code == 0
    assert metrics["period"] == {"date_from": "2026-03-01", "date_to": "2026-03-31"}
    assert metrics["comparison_period"] == {
        "date_from": "2026-02-01",
        "date_to": "2026-02-28",
    }
    assert Path(output["output"]).name == "2026年3月反馈复盘分析报告.md"


def test_snapshot_selection_prefers_degraded_insight_over_base_success():
    """同一时间窗应按 insight success、degraded、base success 的顺序选择。"""
    module = _load_script()

    assert module._candidate_score(
        {
            "run_id": "insight-degraded",
            "status": "degraded",
            "insight": {"status": "degraded"},
        }
    ) > module._candidate_score(
        {
            "run_id": "base-success",
            "status": "success",
            "insight": {"status": "disabled"},
        }
    )


def test_unknown_status_is_not_counted_as_triaged():
    """缺失或未知状态只能降低覆盖率，不能抬高分诊率。"""
    module = _load_script()
    result = module.aggregate_snapshots(
        [
            {
                "day": "2026-08-01",
                "manifest": {"run_id": "daily-unknown"},
                "clusters": {
                    "base_metrics": {
                        "problem_feedback_count": 2,
                        "problem_statuses": {"new": 1, "unknown": 1},
                    },
                    "problems": [],
                },
            }
        ]
    )

    assert result["disposition"]["triage_rate"] == 0.0
    assert result["disposition"]["unknown"] == 1
    assert result["disposition"]["status_coverage_rate"] == 50.0
