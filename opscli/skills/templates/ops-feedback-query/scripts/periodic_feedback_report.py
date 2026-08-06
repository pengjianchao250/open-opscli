#!/usr/bin/env python3
"""从已完成日报运行快照生成反馈周报或自然月月报。"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple
from uuid import uuid4
from zoneinfo import ZoneInfo

from opscli.feedback.services.insight import sanitize_feedback_text


# Skill 脚本不是 Python 包，将同目录加入导入路径以复用输出路径约束。
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from query_feedbacks import FeedbackQueryError, resolve_output_path  # noqa: E402


PERIODIC_SCHEMA_VERSION = "1.0"
DAILY_SCHEMA_VERSION = "1.0"
SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
STATUS_ORDER = ("new", "triaged", "processing", "resolved", "rejected")


class PeriodicReportError(Exception):
    """表示周期、日报快照或周期报告产物不合法。"""


class Period(NamedTuple):
    """周期报告使用的闭区间日期。"""

    date_from: date
    date_to: date

    @property
    def days(self) -> int:
        """返回闭区间包含的自然日数量。"""
        return (self.date_to - self.date_from).days + 1

    def to_dict(self) -> dict[str, str]:
        """转换为稳定 JSON 字段。"""
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
        }


def _parse_date(value: str, label: str) -> date:
    """解析 ISO 日期。"""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PeriodicReportError(f"{label} 必须使用 YYYY-MM-DD 格式") from exc


def resolve_periods(
    report_type: str,
    *,
    period_end: str | None,
    month: str | None,
    now: datetime | None = None,
) -> tuple[Period, Period]:
    """解析周报或自然月月报的当前周期和等价对比周期。

    Args:
        report_type: weekly 或 monthly。
        period_end: 周报结束日期。
        month: 月报自然月。
        now: 测试或默认周期计算使用的当前时间。

    Returns:
        当前周期和紧邻的上一等价周期。

    Raises:
        PeriodicReportError: 周期参数组合或格式不合法。
    """
    current_time = (now or datetime.now(SHANGHAI_TIMEZONE)).astimezone(SHANGHAI_TIMEZONE)
    if report_type == "weekly":
        if month is not None:
            raise PeriodicReportError("周报不接受 --month")
        if period_end:
            end = _parse_date(period_end, "--period-end")
        else:
            # 默认取上一个完整周的周日；当天尚未结束，因此周日回退七天。
            end = current_time.date() - timedelta(days=current_time.weekday() + 1)
        current = Period(end - timedelta(days=6), end)
        return current, Period(current.date_from - timedelta(days=7), end - timedelta(days=7))

    if period_end is not None:
        raise PeriodicReportError("月报不接受 --period-end")
    if month:
        try:
            year_text, month_text = month.split("-", 1)
            year, month_number = int(year_text), int(month_text)
            if len(year_text) != 4 or len(month_text) != 2 or not 1 <= month_number <= 12:
                raise ValueError
        except ValueError as exc:
            raise PeriodicReportError("--month 必须使用 YYYY-MM 格式") from exc
    else:
        previous_last = current_time.date().replace(day=1) - timedelta(days=1)
        year, month_number = previous_last.year, previous_last.month
    current_last = calendar.monthrange(year, month_number)[1]
    current = Period(date(year, month_number, 1), date(year, month_number, current_last))
    previous_end = current.date_from - timedelta(days=1)
    previous = Period(previous_end.replace(day=1), previous_end)
    return current, previous


def build_parser() -> argparse.ArgumentParser:
    """构造周期报告命令参数。

    Returns:
        配置完成的 argparse 参数解析器。
    """
    parser = argparse.ArgumentParser(description="从反馈日报快照生成周报或自然月月报")
    parser.add_argument("--report-type", required=True, choices=("weekly", "monthly"))
    parser.add_argument("--period-end", help="周报结束日期 YYYY-MM-DD")
    parser.add_argument("--month", help="月报自然月 YYYY-MM")
    parser.add_argument("--output", type=Path, help="发布 Markdown 路径，仅允许 output/feedback-query/")
    return parser


def _read_json(path: Path, label: str) -> dict[str, Any]:
    """读取 JSON 对象，非法文件按周期报告错误返回。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PeriodicReportError(f"无法读取{label}: {path}") from exc
    if not isinstance(payload, dict):
        raise PeriodicReportError(f"{label}必须是 JSON 对象: {path}")
    return payload


def _candidate_score(manifest: dict[str, Any]) -> tuple[int, int, str, str]:
    """同一天多次运行时优先选择洞察成功且较新的产物。"""
    insight = manifest.get("insight") if isinstance(manifest.get("insight"), dict) else {}
    profile_score = {"success": 3, "degraded": 2, "disabled": 1}.get(
        str(insight.get("status") or ""),
        0,
    )
    return (
        profile_score,
        1 if manifest.get("execution_status") == "success" else 0,
        str(manifest.get("finished_at") or manifest.get("generated_at") or ""),
        str(manifest.get("run_id") or ""),
    )


def load_daily_snapshots(report_root: Path, period: Period) -> list[dict[str, Any]]:
    """选择周期内每天一份可复算的已发布日报快照。

    Args:
        report_root: feedback-query 输出根目录。
        period: 要读取的闭区间周期。

    Returns:
        按日期升序排列且每天最多一份的结构化日报快照。
    """
    candidates: dict[str, tuple[tuple[int, int, str, str], dict[str, Any]]] = {}
    runs_root = report_root / "runs"
    if not runs_root.exists():
        return []
    for manifest_path in runs_root.glob("*/manifest.json"):
        try:
            manifest = _read_json(manifest_path, "日报 manifest")
        except PeriodicReportError:
            continue
        if (
            manifest.get("schema_version") != DAILY_SCHEMA_VERSION
            or manifest.get("report_type") != "daily"
            or manifest.get("status") not in {"success", "degraded"}
            or not isinstance(manifest.get("publication"), dict)
            or manifest["publication"].get("status") != "success"
        ):
            continue
        period_payload = manifest.get("period")
        label = str(period_payload.get("label") or "") if isinstance(period_payload, dict) else ""
        try:
            day = date.fromisoformat(label)
        except ValueError:
            continue
        if day < period.date_from or day > period.date_to:
            continue
        artifacts = manifest.get("artifacts")
        relative_clusters = artifacts.get("clusters") if isinstance(artifacts, dict) else None
        if not isinstance(relative_clusters, str):
            continue
        try:
            clusters_path = (report_root / relative_clusters).resolve(strict=True)
            if not clusters_path.is_relative_to(report_root.resolve()) or clusters_path.is_symlink():
                continue
            clusters = _read_json(clusters_path, "日报 clusters")
        except (OSError, RuntimeError, PeriodicReportError):
            continue
        if (
            clusters.get("schema_version") != DAILY_SCHEMA_VERSION
            or clusters.get("run_id") != manifest.get("run_id")
            or clusters.get("report_type") != "daily"
        ):
            continue
        snapshot = {"day": label, "manifest": manifest, "clusters": clusters}
        score = _candidate_score(manifest)
        previous = candidates.get(label)
        if previous is None or score > previous[0]:
            candidates[label] = (score, snapshot)
    return [candidates[key][1] for key in sorted(candidates)]


def _sum_counters(target: Counter[str], values: Any) -> None:
    """把 JSON 计数字典安全累加到 Counter。"""
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        try:
            target[str(key)] += int(value)
        except (TypeError, ValueError):
            continue


def _safe_problem_text(value: Any, maximum: int = 200) -> str:
    """清理周期报告中的模型文本和 Markdown 表格控制符。"""
    text = sanitize_feedback_text(value, maximum).replace("|", "\\|")
    return text or "-"


def aggregate_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """把每天的结构化快照聚合为周期基础指标和问题指标。

    Args:
        snapshots: 已筛选的日报 manifest 与 clusters 快照。

    Returns:
        基础计数、处置快照、问题簇及来源运行 ID。
    """
    totals = Counter()
    feedback_types: Counter[str] = Counter()
    severities: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in snapshots:
        day = snapshot["day"]
        clusters = snapshot["clusters"]
        base = clusters.get("base_metrics") if isinstance(clusters.get("base_metrics"), dict) else {}
        for key in ("feedback_count", "problem_feedback_count", "failed_call_count"):
            totals[key] += int(base.get(key) or 0)
        _sum_counters(feedback_types, base.get("feedback_types"))
        _sum_counters(severities, base.get("problem_severities"))
        _sum_counters(sources, base.get("problem_sources"))
        _sum_counters(statuses, base.get("problem_statuses"))
        problems = clusters.get("problems")
        if not isinstance(problems, list):
            continue
        for problem in problems:
            if not isinstance(problem, dict):
                continue
            module = str(problem.get("module") or "unknown")
            problem_key = str(problem.get("problem_key") or "unknown")
            key = (module, problem_key)
            row = grouped.setdefault(
                key,
                {
                    "module": module,
                    "problem_key": problem_key,
                    "problem_category": _safe_problem_text(problem.get("problem_category"), 100),
                    "problem_summary": _safe_problem_text(problem.get("problem_summary")),
                    "recommended_work": _safe_problem_text(problem.get("recommended_work"), 500),
                    "occurrence_count": 0,
                    "affected_user_days": 0,
                    "days": set(),
                    "severity": "low",
                    "priority": "P4",
                    "sample_feedback_uuids": [],
                },
            )
            row["occurrence_count"] += int(problem.get("current_count") or 0)
            row["affected_user_days"] += int(problem.get("affected_users") or 0)
            row["days"].add(day)
            severity = str(problem.get("severity") or "low")
            if SEVERITY_ORDER.get(severity, -1) > SEVERITY_ORDER.get(row["severity"], -1):
                row["severity"] = severity
            priority = str(problem.get("priority") or "P4")
            if PRIORITY_ORDER.get(priority, 99) < PRIORITY_ORDER.get(row["priority"], 99):
                row["priority"] = priority
                row["problem_category"] = _safe_problem_text(problem.get("problem_category"), 100)
                row["problem_summary"] = _safe_problem_text(problem.get("problem_summary"))
                row["recommended_work"] = _safe_problem_text(problem.get("recommended_work"), 500)
            samples = problem.get("sample_feedback_uuids")
            if isinstance(samples, list):
                for sample in samples:
                    text = str(sample)
                    if text not in row["sample_feedback_uuids"] and len(row["sample_feedback_uuids"]) < 5:
                        row["sample_feedback_uuids"].append(text)

    problems_result: list[dict[str, Any]] = []
    for row in grouped.values():
        days = sorted(row.pop("days"))
        row.update(
            {
                "active_days": len(days),
                "first_seen": days[0],
                "last_seen": days[-1],
                "priority_reasons": [
                    f"severity:{row['severity']}",
                    f"occurrences:{row['occurrence_count']}",
                    f"active_days:{len(days)}",
                    f"affected_user_days:{row['affected_user_days']}",
                ],
            }
        )
        problems_result.append(row)
    problems_result.sort(
        key=lambda item: (
            PRIORITY_ORDER.get(item["priority"], 99),
            -item["occurrence_count"],
            item["module"],
            item["problem_key"],
        )
    )
    disposition = {status: int(statuses[status]) for status in STATUS_ORDER}
    problem_count = int(totals["problem_feedback_count"])
    known_status_count = sum(disposition.values())
    disposition["unknown"] = max(
        int(statuses["unknown"]),
        problem_count - known_status_count,
    )
    triaged_count = sum(
        disposition[status] for status in ("triaged", "processing", "resolved", "rejected")
    )
    disposition["triage_rate"] = (
        round(triaged_count * 100 / problem_count, 1) if problem_count else 0.0
    )
    disposition["resolution_rate"] = (
        round(disposition["resolved"] * 100 / problem_count, 1) if problem_count else 0.0
    )
    disposition["status_coverage_rate"] = (
        round(min(problem_count, known_status_count) * 100 / problem_count, 1)
        if problem_count
        else 0.0
    )
    return {
        "run_ids": [snapshot["manifest"]["run_id"] for snapshot in snapshots],
        "base_metrics": dict(totals),
        "feedback_types": dict(sorted(feedback_types.items())),
        "problem_severities": dict(sorted(severities.items())),
        "problem_sources": dict(sorted(sources.items())),
        "disposition": disposition,
        "problems": problems_result,
    }


def build_periodic_metrics(
    report_type: str,
    period: Period,
    comparison_period: Period,
    current_snapshots: list[dict[str, Any]],
    comparison_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """生成周报/月报的可复算指标对象。

    Args:
        report_type: weekly 或 monthly。
        period: 当前报告周期。
        comparison_period: 对比周期。
        current_snapshots: 当前周期日报快照。
        comparison_snapshots: 对比周期日报快照。

    Returns:
        包含覆盖、处置、生命周期和问题明细的指标对象。
    """
    current = aggregate_snapshots(current_snapshots)
    previous = aggregate_snapshots(comparison_snapshots)
    current_keys = {(item["module"], item["problem_key"]) for item in current["problems"]}
    previous_keys = {(item["module"], item["problem_key"]) for item in previous["problems"]}
    lifecycle = {
        "new": len(current_keys - previous_keys),
        "persistent": len(current_keys & previous_keys),
        "not_seen_again": len(previous_keys - current_keys),
        "recurring": sum(1 for item in current["problems"] if item["active_days"] > 1),
    }
    module_counts: dict[str, int] = defaultdict(int)
    for problem in current["problems"]:
        module_counts[problem["module"]] += problem["occurrence_count"]
    return {
        "schema_version": PERIODIC_SCHEMA_VERSION,
        "report_type": report_type,
        "period": period.to_dict(),
        "comparison_period": comparison_period.to_dict(),
        "coverage": {"actual_days": len(current_snapshots), "expected_days": period.days},
        "comparison_coverage": {
            "actual_days": len(comparison_snapshots),
            "expected_days": comparison_period.days,
        },
        "base_metrics": current["base_metrics"],
        "comparison_base_metrics": previous["base_metrics"],
        "disposition": current["disposition"],
        "problem_lifecycle": lifecycle,
        "problems": current["problems"],
        "modules": [
            {"module": module, "occurrence_count": count}
            for module, count in sorted(module_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "source_run_ids": current["run_ids"],
        "comparison_source_run_ids": previous["run_ids"],
    }


def render_markdown(metrics: dict[str, Any]) -> str:
    """将周期指标渲染为不含原始反馈正文的 Markdown。

    Args:
        metrics: 已计算的周期指标对象。

    Returns:
        可发布的反馈周报或月报 Markdown。
    """
    period = metrics["period"]
    report_type = metrics["report_type"]
    title = "反馈周报" if report_type == "weekly" else "反馈月报"
    base = metrics["base_metrics"]
    disposition = metrics["disposition"]
    lifecycle = metrics["problem_lifecycle"]
    lines = [
        f"# {title}（{period['date_from']} 至 {period['date_to']}）",
        "",
        f"> 数据覆盖：{metrics['coverage']['actual_days']}/{metrics['coverage']['expected_days']} 天；所有处置指标均为日报快照口径。",
        "",
        "## 一、执行摘要",
        "",
        "| 指标 | 本期 |",
        "|---|---:|",
        f"| 反馈数 | {int(base.get('feedback_count') or 0)} |",
        f"| 问题反馈数 | {int(base.get('problem_feedback_count') or 0)} |",
        f"| 失败调用数 | {int(base.get('failed_call_count') or 0)} |",
        f"| 问题簇数 | {len(metrics['problems'])} |",
        "",
        "## 二、处置快照",
        "",
        "| new | triaged | processing | resolved | rejected | unknown | 状态覆盖率 | 分诊率 | 解决率 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        "| {new} | {triaged} | {processing} | {resolved} | {rejected} | {unknown} | {status_coverage_rate}% | {triage_rate}% | {resolution_rate}% |".format(
            **disposition
        ),
        "",
        "## 三、问题变化",
        "",
        "| 新增 | 持续 | 本期未再出现 | 多日复发 |",
        "|---:|---:|---:|---:|",
        f"| {lifecycle['new']} | {lifecycle['persistent']} | {lifecycle['not_seen_again']} | {lifecycle['recurring']} |",
        "",
        "## 四、高频问题",
        "",
        "| 优先级 | 模块 | 问题 | 次数 | 活跃天数 | 影响用户日 | 首次 | 最后 | 建议 |",
        "|---|---|---|---:|---:|---:|---|---|---|",
    ]
    if metrics["problems"]:
        for problem in metrics["problems"][:20]:
            lines.append(
                "| {priority} | {module} | {summary} | {count} | {days} | {users} | {first} | {last} | {work} |".format(
                    priority=problem["priority"],
                    module=problem["module"],
                    summary=problem["problem_summary"],
                    count=problem["occurrence_count"],
                    days=problem["active_days"],
                    users=problem["affected_user_days"],
                    first=problem["first_seen"],
                    last=problem["last_seen"],
                    work=problem["recommended_work"],
                )
            )
    else:
        lines.append("| - | - | 本期没有可聚合的问题簇 | 0 | 0 | 0 | - | - | - |")
    lines.extend(
        [
            "",
            "## 五、模块分布",
            "",
            "| 模块 | 问题发生次数 |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| {item['module']} | {item['occurrence_count']} |" for item in metrics["modules"]
    )
    if not metrics["modules"]:
        lines.append("| - | 0 |")
    lines.extend(
        [
            "",
            "## 六、口径说明",
            "",
            "- 周报使用完整七天，月报使用自然月；对比期为紧邻的上一等价周期。",
            "- 处置率来自日报生成时的反馈状态快照；没有状态事件时不计算 SLA、MTTA 或 MTTR。",
            "- 影响用户日是各日报受影响用户数之和，不等同于跨周期去重用户数。",
            "- “本期未再出现”不等同于已解决，只表示对比期出现的问题簇在本期快照中未出现。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_atomically(path: Path, content: str) -> Path:
    """在反馈导出目录内原子写入文本产物。"""
    resolved = resolve_output_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(resolved)
    except OSError as exc:
        raise PeriodicReportError(f"无法写入周期报告产物: {resolved}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return resolved


def _report_names(report_type: str, period: Period) -> tuple[str, str]:
    """返回发布文件名和稳定周期键。"""
    if report_type == "weekly":
        label = f"{period.date_from.isoformat()}_{period.date_to.isoformat()}"
        return f"反馈周报-{label}.md", f"weekly-{label}"
    label = f"{period.date_from.year}-{period.date_from.month:02d}"
    return f"{period.date_from.year}年{period.date_from.month}月反馈复盘分析报告.md", f"monthly-{label}"


def generate_report(args: argparse.Namespace) -> dict[str, Any]:
    """读取日报快照、生成指标和周期报告产物。

    Args:
        args: 已解析的报告类型、周期和输出参数。

    Returns:
        发布报告、归档、指标、manifest 和覆盖率路径摘要。

    Raises:
        FeedbackQueryError: 输出路径越界或项目根无法定位。
        PeriodicReportError: 周期参数或报告产物读写失败。
    """
    period, comparison_period = resolve_periods(
        args.report_type,
        period_end=args.period_end,
        month=args.month,
    )
    export_root = resolve_output_path(Path(".periodic-root")).parent
    current_snapshots = load_daily_snapshots(export_root, period)
    comparison_snapshots = load_daily_snapshots(export_root, comparison_period)
    metrics = build_periodic_metrics(
        args.report_type,
        period,
        comparison_period,
        current_snapshots,
        comparison_snapshots,
    )
    markdown = render_markdown(metrics)
    published_name, period_key = _report_names(args.report_type, period)
    artifact_dir = Path("periodic") / period_key
    metrics_path = _write_atomically(
        artifact_dir / "metrics.json",
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
    )
    report_path = _write_atomically(artifact_dir / "report.md", markdown)
    published_path = _write_atomically(args.output or Path(published_name), markdown)
    report_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": PERIODIC_SCHEMA_VERSION,
        "report_type": args.report_type,
        "period_key": period_key,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "success",
        "period": period.to_dict(),
        "comparison_period": comparison_period.to_dict(),
        "coverage": metrics["coverage"],
        "comparison_coverage": metrics["comparison_coverage"],
        "source_run_ids": metrics["source_run_ids"],
        "comparison_source_run_ids": metrics["comparison_source_run_ids"],
        "artifacts": {
            "report": str(report_path),
            "published_report": str(published_path),
            "metrics": str(metrics_path),
            "report_sha256": report_hash,
        },
    }
    manifest_path = _write_atomically(
        artifact_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "success": True,
        "report_type": args.report_type,
        "output": str(published_path),
        "archived_report": str(report_path),
        "metrics": str(metrics_path),
        "manifest": str(manifest_path),
        "coverage": metrics["coverage"],
    }


def main(argv: list[str] | None = None) -> int:
    """周期报告命令入口。

    Args:
        argv: 可选命令行参数；不传时读取当前进程参数。

    Returns:
        成功返回 0，受控失败返回 1。
    """
    args = build_parser().parse_args(argv)
    try:
        result = generate_report(args)
    except (FeedbackQueryError, PeriodicReportError) as exc:
        print(
            json.dumps(
                {"success": False, "code": "PERIODIC_REPORT_ERROR", "message": str(exc)},
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
