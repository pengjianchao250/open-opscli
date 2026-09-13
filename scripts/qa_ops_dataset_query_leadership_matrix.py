#!/usr/bin/env python3
"""全量审计 ops-dataset-query 规划器，并生成领导汇报版报告。"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import subprocess
import threading
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OPSCLI = ROOT / ".venv/bin/opscli"
SKILL_DIR = ROOT / "opscli/skills/templates/ops-dataset-query"
FEEDBACK_DIR = ROOT / "opscli/skills/templates/ops-feedback"
DEFAULT_OUTPUT = ROOT / "output/ops-dataset-query-leadership-matrix-20260908"
SESSION_ID = "ops-dataset-query-leadership-matrix-20260908"


@dataclass(frozen=True)
class Case:
    case_id: str
    table_id: int
    dataset_name: str
    dataset_category: str
    scenario: str
    prompt: str
    expected_fields: tuple[str, ...]
    expected_date_fields: tuple[str, ...] = ()
    expected_limit: int | None = None
    expected_order_field: str | None = None
    expected_order_desc: bool | None = None
    expected_snapshot: bool = False


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def run(command: list[str], timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as error:
        return {
            "exit_code": 124,
            "stdout": error.stdout if isinstance(error.stdout, str) else "",
            "stderr": error.stderr if isinstance(error.stderr, str) else "",
            "timed_out": True,
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def parse_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def skill_version() -> str:
    payload = json.loads((SKILL_DIR / "data/VERSION.json").read_text(encoding="utf-8"))
    return str(payload.get("version") or "unknown")


class Feedback:
    """对真实 opscli 失败执行即时、分组去重反馈。"""

    def __init__(self, output: Path) -> None:
        self.output = output / "feedback"
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.counter = 0
        self.records: list[dict[str, Any]] = []

    def submit(self, case: Case | None, process: dict[str, Any], code: str, message: str) -> str | None:
        with self.lock:
            self.counter += 1
            event_id = f"event-{self.counter:04d}"
            prompt = case.prompt if case else "opscli query metadata --all-fields"
            event = {
                "outcome": "failure",
                "source": "cli",
                "tool": "opscli query plan" if case else "opscli query metadata",
                "command_name": "opscli query plan" if case else "opscli query metadata",
                "call_params": {"request": prompt, "table_id": case.table_id if case else None},
                "error_code": code,
                "error_message": message,
                "needs_owner_action": True,
                "session_id": SESSION_ID,
                "feedback_group_key": f"{SESSION_ID}:{code}:{message[:120]}",
            }
            event_path = self.output / f"{event_id}.json"
            event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
            guard = run(
                [
                    "python3",
                    str(FEEDBACK_DIR / "scripts/feedback_guard.py"),
                    "decide",
                    "--event-file",
                    str(event_path),
                ],
                20,
            )
            decision = parse_json(guard["stdout"]) or {}
            uuid = decision.get("feedback_uuid")
            record = {"event_id": event_id, "code": code, "decision": decision, "feedback_uuid": uuid}
            if decision.get("submit_remote"):
                body = {
                    "source": "cli",
                    "feedback_type": "bug",
                    "severity": "high",
                    "title": f"全量规划器矩阵调用失败：{code}",
                    "content": "全量自然语言规划器验收中 opscli 调用失败，已按失败分组保留最小复现。",
                    "skill_name": "ops-dataset-query",
                    "skill_version": skill_version(),
                    "command_name": event["command_name"],
                    "execution_summary": {
                        "summary": "全量规划器矩阵出现真实 CLI 失败。",
                        "failed_calls": [{
                            "tool": event["tool"],
                            "call_params": event["call_params"],
                            "error_message": f"{code}: {message}",
                            "reason": "推测：规划器、元数据或远端服务未能完成请求。",
                            "fix_suggestion": "使用保存的自然语言和 table_id 复现，定位规划、元数据或服务端错误。",
                        }],
                        "successful_calls": [],
                        "final_resolution": "反馈后继续执行其余独立用例。",
                    },
                    "context": {"cwd": str(ROOT), "agent": "Codex", "workflow": SESSION_ID},
                    "attachments": [str(event_path)],
                }
                feedback_path = self.output / f"{event_id}-feedback.json"
                feedback_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
                submitted = run([str(OPSCLI), "feedback", "submit", "--file", str(feedback_path), "--pretty"], 30)
                submitted_payload = parse_json(submitted["stdout"]) or {}
                uuid = ((submitted_payload.get("data") or {}).get("feedback_uuid"))
                record.update({"feedback_uuid": uuid, "feedback_submit": submitted})
                if uuid:
                    run(
                        [
                            "python3",
                            str(FEEDBACK_DIR / "scripts/feedback_guard.py"),
                            "record",
                            "--event-file",
                            str(event_path),
                            "--feedback-uuid",
                            str(uuid),
                        ],
                        20,
                    )
            self.records.append(record)
            return str(uuid) if uuid else None


def command_failure(process: dict[str, Any], payload: dict[str, Any] | None) -> tuple[str, str] | None:
    if process["timed_out"]:
        return "COMMAND_TIMEOUT", f"超过 {process['duration_seconds']} 秒"
    if process["exit_code"] != 0:
        return "NON_ZERO_EXIT", (process["stderr"] or process["stdout"] or "无输出")[:1000]
    if not payload:
        return "INVALID_JSON", (process["stderr"] or "stdout 不是 JSON")[:1000]
    if payload.get("success") is False:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        return str(error.get("code") or "OPSCLI_FAILURE"), str(error.get("message") or error)[:1000]
    return None


def unique_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    label_counts = Counter(str(item.get("verbose_name") or "") for item in rows)
    for item in rows:
        name = str(item.get("field_name") or "")
        label = str(item.get("verbose_name") or name)
        if name and label and label_counts[label] == 1:
            result.setdefault(name, item)
    return list(result.values())


def choose(rows: list[dict[str, Any]], field_type: str, *, exclude_time: bool = False) -> list[dict[str, Any]]:
    selected = [item for item in unique_fields(rows) if item.get("field_type") == field_type]
    if exclude_time:
        selected = [item for item in selected if not is_time(item)]
    return selected


def is_time(field: dict[str, Any]) -> bool:
    name = str(field.get("field_name") or "").lower()
    label = str(field.get("verbose_name") or "")
    return bool(
        name in {"date_id", "date", "month", "year_month", "timestamp"}
        or re.search(r"(?:^|_)(?:date|time|month|year)(?:$|_)", name)
        or name.endswith("_at")
        or any(token in label for token in ("日期", "时间", "年月", "月份", "年度"))
    )


def label(field: dict[str, Any]) -> str:
    return str(field.get("verbose_name") or field.get("field_name"))


def build_cases(datasets: list[dict[str, Any]], fields: list[dict[str, Any]]) -> list[Case]:
    by_table: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for field in fields:
        by_table[int(field["table_id"])].append(field)
    cases: list[Case] = []
    phrasing = ("请从", "帮领导看", "我想查", "麻烦分析")
    for dataset in datasets:
        table_id = int(dataset["table_id"])
        name = str(dataset.get("description") or dataset.get("dataset_name") or table_id)
        category = str(dataset.get("dataset_category") or "normal")
        rows = by_table.get(table_id, [])
        dimensions = choose(rows, "dimension", exclude_time=True)
        metrics = choose(rows, "metric")
        dates = [
            item for item in unique_fields(rows)
            if item.get("field_type") == "dimension" and is_time(item)
        ]
        snapshots = [item for item in metrics if bool(int(item.get("snapshot_metric") or 0))]
        additive_metrics = [item for item in metrics if item not in snapshots]
        compatible_metrics = additive_metrics or snapshots
        prefix = phrasing[table_id % len(phrasing)]
        if category == "query_component":
            target = dimensions[0] if dimensions else (unique_fields(rows)[0] if rows else None)
            expected = (str(target["field_name"]),) if target else ()
            target_text = label(target) if target else "可选值"
            cases.append(Case(
                f"t{table_id}-component", table_id, name, category, "query_component",
                f"{prefix}“{name}”里列出当前账号可见的{target_text}，给我前5条",
                expected, expected_limit=5,
            ))
            continue
        base_fields = [*dimensions[:1], *compatible_metrics[:2]] or unique_fields(rows)[:2]
        if base_fields:
            field_text = "、".join(label(item) for item in base_fields)
            time_text = "，范围是2026年8月" if dates else ""
            cases.append(Case(
                f"t{table_id}-baseline", table_id, name, category, "baseline",
                f"{prefix}“{name}”中查看{field_text}{time_text}",
                tuple(str(item["field_name"]) for item in base_fields),
            ))
        if len(compatible_metrics) >= 2:
            metric_text = "、".join(label(item) for item in compatible_metrics[:2])
            cases.append(Case(
                f"t{table_id}-multi", table_id, name, category, "multi_metric",
                f"在“{name}”里汇总{metric_text}" + ("，看2026年8月" if dates else ""),
                tuple(str(item["field_name"]) for item in compatible_metrics[:2]),
            ))
        if dates and compatible_metrics:
            date, metric = dates[0], compatible_metrics[0]
            date_names = tuple(str(item["field_name"]) for item in dates)
            cases.append(Case(
                f"t{table_id}-trend", table_id, name, category, "trend",
                f"用“{name}”按日查看2026年8月{label(metric)}趋势",
                (str(metric["field_name"]),),
                expected_date_fields=date_names,
                expected_order_desc=False,
            ))
            cases.append(Case(
                f"t{table_id}-compare", table_id, name, category, "comparison",
                f"从“{name}”看2026年8月{label(metric)}，和7月做环比",
                (str(metric["field_name"]),), expected_date_fields=date_names,
            ))
        if dimensions and compatible_metrics:
            dimension, metric = dimensions[0], compatible_metrics[0]
            cases.append(Case(
                f"t{table_id}-topn", table_id, name, category, "topn_sort",
                f"“{name}”里按{label(metric)}从高到低看2026年8月各{label(dimension)}前5名"
                if dates else f"“{name}”里按{label(metric)}从高到低看各{label(dimension)}前5名",
                (str(dimension["field_name"]), str(metric["field_name"])),
                expected_limit=5, expected_order_field=str(metric["field_name"]), expected_order_desc=True,
            ))
        if dates and snapshots:
            cases.append(Case(
                f"t{table_id}-snapshot", table_id, name, category, "snapshot",
                f"查看“{name}”2026年8月的{label(snapshots[0])}，不要按日拆分",
                (str(snapshots[0]["field_name"]),), expected_snapshot=True,
            ))
    return cases


def evaluate(case: Case, payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    model = data.get("model_view") if isinstance(data.get("model_view"), dict) else {}
    execution = data.get("execution_ref") if isinstance(data.get("execution_ref"), dict) else {}
    template = execution.get("query_template") if isinstance(execution.get("query_template"), dict) else {}
    actual_table = execution.get("table_id")
    actual_fields = {
        str(item.get("field_name"))
        for group in (execution.get("dimensions") or [], execution.get("metrics") or [])
        for item in group if isinstance(item, dict) and item.get("field_name")
    }
    issues: list[str] = []
    status = str(data.get("status") or "missing")
    if status != "planned":
        issues.append(f"unexpected_status:{status}")
    if actual_table != case.table_id:
        issues.append(f"wrong_dataset:{actual_table}")
    missing = sorted(set(case.expected_fields) - actual_fields)
    if missing:
        issues.append("missing_fields:" + ",".join(missing))
    if status == "planned" and not template:
        issues.append("missing_query_template")
    actual_dimensions = {
        str(item.get("field_name"))
        for item in execution.get("dimensions") or []
        if isinstance(item, dict) and item.get("field_name")
    }
    if case.scenario == "trend" and case.expected_date_fields:
        if not actual_dimensions.intersection(case.expected_date_fields):
            issues.append("trend_missing_time_dimension")
    if case.scenario == "comparison" and not isinstance(template.get("dataComparison"), dict):
        issues.append("comparison_missing")
    if case.expected_limit is not None and template.get("limit") != case.expected_limit:
        issues.append(f"wrong_limit:{template.get('limit')}")
    if case.expected_order_field or (case.scenario == "trend" and case.expected_date_fields):
        order = template.get("orderBy") if isinstance(template.get("orderBy"), list) else []
        matched = any(
            isinstance(item, dict)
            and (
                item.get("field") == case.expected_order_field
                if case.expected_order_field
                else item.get("field") in case.expected_date_fields
            )
            and item.get("desc") is case.expected_order_desc
            for item in order
        )
        if not matched:
            issues.append("wrong_or_missing_order")
    if case.expected_snapshot and not isinstance(execution.get("snapshot_policy"), dict):
        issues.append("snapshot_policy_missing")
    return {
        "passed": not issues,
        "status": status,
        "actual_table_id": actual_table,
        "actual_dataset_name": model.get("dataset_name_zh"),
        "actual_fields": sorted(actual_fields),
        "issues": issues,
        "clarification_codes": model.get("clarification_reason_codes") or [],
    }


def execute(case: Case, output: Path, timeout: int, force: bool, feedback: Feedback) -> dict[str, Any]:
    raw_path = output / "raw" / f"{case.case_id}.json"
    if raw_path.exists() and not force:
        return json.loads(raw_path.read_text(encoding="utf-8"))
    process = run([str(OPSCLI), "query", "plan", case.prompt], timeout)
    payload = parse_json(process["stdout"])
    failure = command_failure(process, payload)
    feedback_uuid = None
    if failure:
        feedback_uuid = feedback.submit(case, process, *failure)
        evaluation = {
            "passed": False,
            "status": "command_failed",
            "actual_table_id": None,
            "actual_dataset_name": None,
            "actual_fields": [],
            "issues": [f"{failure[0]}:{failure[1]}"],
            "clarification_codes": [],
        }
    else:
        evaluation = evaluate(case, payload)
    record = {
        "case": asdict(case),
        "process": {key: value for key, value in process.items() if key != "stdout"},
        "evaluation": evaluation,
        "feedback_uuid": feedback_uuid,
        "payload": payload,
    }
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def write_reports(
    output: Path,
    datasets: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    cases: list[Case],
    records: list[dict[str, Any]],
    feedback: Feedback,
) -> Path:
    passed = [item for item in records if item["evaluation"]["passed"]]
    failed = [item for item in records if not item["evaluation"]["passed"]]
    covered = {item["case"]["table_id"] for item in records}
    scenario_counts = Counter(item["case"]["scenario"] for item in records)
    failure_counts = Counter(
        issue.split(":", 1)[0]
        for item in failed for issue in item["evaluation"]["issues"]
    )
    dataset_rows = []
    for dataset in datasets:
        table_id = int(dataset["table_id"])
        subset = [item for item in records if item["case"]["table_id"] == table_id]
        count_passed = sum(bool(item["evaluation"]["passed"]) for item in subset)
        dataset_rows.append({
            "table_id": table_id,
            "dataset_name": dataset.get("description"),
            "category": dataset.get("dataset_category"),
            "case_count": len(subset),
            "passed": count_passed,
            "failed": len(subset) - count_passed,
            "pass_rate": count_passed / len(subset) if subset else 0,
        })
    def root_cause(item: dict[str, Any]) -> str:
        codes = set(item["evaluation"]["clarification_codes"])
        case_id = item["case"]["case_id"]
        if "metric_not_in_dataset" in codes:
            return "精确指标被短别名覆盖"
        if "component_filter_value_unmatched" in codes:
            return "分组或句法片段误判为筛选值"
        if "business_dataset" in codes and item["case"]["dataset_category"] == "query_component":
            return "查询组件合同与实现不一致"
        if "snapshot_metric_window_conflict" in codes:
            return "数据集名称泄漏为额外指标"
        if case_id == "t96-trend":
            return "排名指标覆盖趋势时间排序"
        if case_id == "t98-trend":
            return "主日期字段识别错误"
        return "其他规划异常"

    root_causes = Counter(root_cause(item) for item in failed)
    priorities = {
        "精确指标被短别名覆盖": ("P0", "精确完整字段名优先于其中的稳定短别名；别名只在未命中完整授权字段时补位。"),
        "分组或句法片段误判为筛选值": ("P0", "组件值提取排除数据集标题、引号区间和“查看/按/各”等分组句法，只允许授权枚举完整等值进入筛选。"),
        "主日期字段识别错误": ("P0", "日期候选必须同时满足日期字段类型或字段语义，不得把运行角色等普通维度作为时间字段。"),
        "数据集名称泄漏为额外指标": ("P1", "字段识别前遮蔽已确认的数据集名称，避免标题中的“仓租”等词被再次消费为指标。"),
        "排名指标覆盖趋势时间排序": ("P1", "显式趋势/按日的时间升序优先级高于排名类指标的默认降序。"),
        "查询组件合同与实现不一致": ("P1", "统一 Skill 与内核：明确枚举请求应走组件查询；普通业务取数继续禁止组件表。"),
        "其他规划异常": ("P2", "逐条复核并补充针对性回归。"),
    }
    root_cause_rows = [
        {"root_cause": name, "count": count, "priority": priorities[name][0], "recommendation": priorities[name][1]}
        for name, count in sorted(root_causes.items(), key=lambda item: (priorities[item[0]][0], -item[1]))
    ]
    summary = {
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "skill_version": skill_version(),
        "scope": {
            "dataset_count": len(datasets),
            "normal_dataset_count": sum(item.get("dataset_category") == "normal" for item in datasets),
            "query_component_count": sum(item.get("dataset_category") == "query_component" for item in datasets),
            "field_count": len(fields),
            "covered_dataset_count": len(covered),
        },
        "metrics": {
            "case_count": len(records),
            "passed": len(passed),
            "failed": len(failed),
            "pass_rate": len(passed) / len(records) if records else 0,
            "scenario_counts": dict(scenario_counts),
            "failure_counts": dict(failure_counts),
            "root_cause_counts": dict(root_causes),
        },
        "root_causes": root_cause_rows,
        "datasets": dataset_rows,
        "failures": [{
            "case_id": item["case"]["case_id"],
            "table_id": item["case"]["table_id"],
            "dataset_name": item["case"]["dataset_name"],
            "scenario": item["case"]["scenario"],
            "prompt": item["case"]["prompt"],
            "status": item["evaluation"]["status"],
            "issues": item["evaluation"]["issues"],
            "clarification_codes": item["evaluation"]["clarification_codes"],
            "raw_file": f"raw/{item['case']['case_id']}.json",
        } for item in failed],
        "feedback": feedback.records,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    percent = summary["metrics"]["pass_rate"] * 100
    lines = [
        "# 数据集自然语言规划器全量验收报告",
        "",
        f"> 生成时间：{summary['generated_at']}｜Skill {summary['skill_version']}",
        "",
        "## 管理摘要",
        "",
        f"- 当前账号数据集覆盖：{len(covered)} / {len(datasets)}。",
        f"- 当前后端字段：{len(fields)} 个。",
        f"- 自然语言组合用例：{len(records)} 条，通过 {len(passed)}，失败 {len(failed)}，通过率 {percent:.2f}%。",
        f"- 场景分布：" + "、".join(f"{key} {value}" for key, value in sorted(scenario_counts.items())),
        "",
        "## 待优化问题",
        "",
    ]
    if root_cause_rows:
        lines.extend(
            f"- **{item['priority']}｜{item['root_cause']}**：{item['count']} 条。{item['recommendation']}"
            for item in root_cause_rows
        )
    else:
        lines.append("- 本轮未发现机器判分缺陷。")
    lines.extend(["", "## 失败明细", ""])
    for item in summary["failures"]:
        lines.append(
            f"- `{item['case_id']}`｜{item['dataset_name']}｜{item['scenario']}｜"
            f"{'；'.join(item['issues'])}｜原文：{item['prompt']}"
        )
    lines.extend(["", "## 结论边界", "", "- 全量阶段只验证规划合同，不执行全部业务查询，避免大范围读取生产数据。", "- 规划状态、选表、字段完整性、时间、排序、TopN、环比和快照策略均按合同机器判分。", "- 代表性高风险用例需另行通过 query flow 做真实执行复验。"])
    (output / "leadership-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failure_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(item["case_id"]), item["table_id"], html.escape(item["dataset_name"]),
            html.escape(item["scenario"]), html.escape("；".join(item["issues"])),
        ) for item in summary["failures"]
    ) or '<tr><td colspan="5">未发现失败</td></tr>'
    cause_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(item["priority"]), html.escape(item["root_cause"]), item["count"],
            html.escape(item["recommendation"]),
        ) for item in root_cause_rows
    ) or '<tr><td colspan="4">未发现问题</td></tr>'
    dataset_html = "".join(
        "<tr><td>{table_id}</td><td>{dataset_name}</td><td>{category}</td><td>{case_count}</td>"
        "<td>{passed}</td><td>{failed}</td><td>{pass_rate:.2%}</td></tr>".format(
            **{**item, "dataset_name": html.escape(str(item["dataset_name"])), "category": html.escape(str(item["category"]))}
        ) for item in dataset_rows
    )
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>规划器全量验收</title><style>
body{{margin:0;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17202a;background:#f4f6f7}}header{{background:#16324f;color:white;padding:28px 5vw}}main{{padding:24px 5vw}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.metric,section{{background:white;border:1px solid #dfe6e9;border-radius:6px;padding:16px;margin-bottom:16px}}.value{{font-size:28px;font-weight:700}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #e5e8e8;text-align:left}}th{{background:#eef2f3;position:sticky;top:0}}.wrap{{max-height:520px;overflow:auto}}@media(max-width:800px){{.metrics{{grid-template-columns:1fr 1fr}}}}
</style></head><body><header><h1>数据集自然语言规划器全量验收</h1><div>Skill {html.escape(summary['skill_version'])}｜{html.escape(summary['generated_at'])}</div></header><main><div class="metrics"><div class="metric"><div>数据集覆盖</div><div class="value">{len(covered)}/{len(datasets)}</div></div><div class="metric"><div>组合用例</div><div class="value">{len(records)}</div></div><div class="metric"><div>通过率</div><div class="value">{percent:.2f}%</div></div><div class="metric"><div>待优化</div><div class="value">{len(failed)}</div></div></div><section><h2>场景覆盖</h2><p>{html.escape('、'.join(f'{key} {value}' for key, value in sorted(scenario_counts.items())))}</p></section><section><h2>优化优先级</h2><table><thead><tr><th>优先级</th><th>根因</th><th>用例数</th><th>建议</th></tr></thead><tbody>{cause_rows}</tbody></table></section><section><h2>失败明细</h2><div class="wrap"><table><thead><tr><th>用例</th><th>ID</th><th>数据集</th><th>场景</th><th>问题</th></tr></thead><tbody>{failure_rows}</tbody></table></div></section><section><h2>数据集明细</h2><div class="wrap"><table><thead><tr><th>ID</th><th>数据集</th><th>类型</th><th>用例</th><th>通过</th><th>失败</th><th>通过率</th></tr></thead><tbody>{dataset_html}</tbody></table></div></section></main></body></html>'''
    html_path = output / "leadership-report.html"
    html_path.write_text(document, encoding="utf-8")
    return html_path


def main() -> int:
    options = args()
    output = options.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    feedback = Feedback(output)
    metadata_process = run([str(OPSCLI), "query", "metadata", "--all-fields"], 60)
    metadata_payload = parse_json(metadata_process["stdout"])
    failure = command_failure(metadata_process, metadata_payload)
    if failure:
        feedback.submit(None, metadata_process, *failure)
        raise SystemExit(f"metadata 失败：{failure[0]} {failure[1]}")
    data = metadata_payload["data"]
    datasets = [item for item in data.get("datasets", []) if isinstance(item, dict)]
    fields = [item for item in data.get("fields", []) if isinstance(item, dict)]
    cases = build_cases(datasets, fields)
    if options.max_cases is not None:
        cases = cases[: options.max_cases]
    (output / "case-manifest.json").write_text(
        json.dumps({"cases": [asdict(item) for item in cases]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"phase": "start", "datasets": len(datasets), "fields": len(fields), "cases": len(cases)}, ensure_ascii=False), flush=True)
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=options.workers) as executor:
        futures = {
            executor.submit(execute, case, output, options.timeout, options.force, feedback): case
            for case in cases
        }
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            records.append(record)
            completed += 1
            if completed % 20 == 0 or completed == len(cases):
                print(json.dumps({"phase": "progress", "completed": completed, "total": len(cases)}, ensure_ascii=False), flush=True)
    order = {case.case_id: index for index, case in enumerate(cases)}
    records.sort(key=lambda item: order[item["case"]["case_id"]])
    report = write_reports(output, datasets, fields, cases, records, feedback)
    passed = sum(bool(item["evaluation"]["passed"]) for item in records)
    print(json.dumps({"phase": "complete", "passed": passed, "failed": len(records) - passed, "report": str(report)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
