#!/usr/bin/env python3
"""判断一个运营 Skill 是否达到内测候选提交门槛。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SUCCESS_STATUSES = {"success", "ok", "passed", "done", "completed"}
FAIL_STATUSES = {"failed", "fail", "error", "critical"}


def parse_frontmatter(skill_dir: Path) -> dict[str, str]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {}
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not match:
        return {}
    values: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() in {"name", "description", "version"}:
            values[key.strip()] = value
    version_match = re.search(r"metadata:\s*\n(?:  .+\n)*?  version:\s*['\"]?([^'\"\n]+)", match.group(1))
    if "version" not in values and version_match:
        values["version"] = version_match.group(1).strip()
    return values


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def iter_jsonl_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*.jsonl") if p.is_file())


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                records.append({
                    "status": "failed",
                    "error_category": "invalid_log_json",
                    "severity": "high",
                    "source_file": str(path),
                    "source_line": lineno,
                    "error": str(exc),
                })
                continue
            if isinstance(value, dict):
                value.setdefault("source_file", str(path))
                value.setdefault("source_line", lineno)
                records.append(value)
    return records


def record_status(record: dict[str, Any]) -> str:
    if record.get("success") is True:
        return "success"
    if record.get("success") is False:
        return "failed"
    status = str(record.get("status", "")).strip().lower()
    if status in SUCCESS_STATUSES:
        return "success"
    if status in FAIL_STATUSES:
        return "failed"
    if record.get("error_category"):
        return "failed"
    return "unknown"


def has_real_input(record: dict[str, Any]) -> bool:
    if record.get("real_business_input") is True:
        return True
    if record.get("real_business_input") is False:
        return False
    input_summary = record.get("input_summary")
    if isinstance(input_summary, str) and any(marker in input_summary.lower() for marker in ("模拟", "synthetic", "mock", "sample")):
        return False
    if isinstance(input_summary, dict) and any(v not in ("", None, [], {}) for v in input_summary.values()):
        return True
    data_sources = record.get("data_sources")
    if isinstance(data_sources, list) and data_sources:
        return True
    return False


def is_critical(record: dict[str, Any]) -> bool:
    joined = " ".join(
        str(record.get(key, ""))
        for key in ("severity", "error_category", "status", "failure_category")
    ).lower()
    return "critical" in joined


def summarize_records(
    records: list[dict[str, Any]],
    skill_name: str | None,
    days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for record in records:
        if skill_name and record.get("skill_name") and str(record.get("skill_name")) != skill_name:
            continue
        parsed_time = parse_time(record.get("time") or record.get("created_at") or record.get("timestamp"))
        if parsed_time and parsed_time < cutoff:
            continue
        filtered.append(record)

    statuses = [record_status(record) for record in filtered]
    success_count = statuses.count("success")
    failed_count = statuses.count("failed")
    total = len(filtered)
    success_rate = success_count / total if total else 0.0
    real_input_count = sum(1 for record in filtered if has_real_input(record))
    critical_count = sum(1 for record in filtered if is_critical(record))
    last_run_at = None
    parsed_times = [
        parsed for parsed in (parse_time(record.get("time") or record.get("created_at") or record.get("timestamp")) for record in filtered)
        if parsed is not None
    ]
    if parsed_times:
        last_run_at = max(parsed_times).isoformat()

    intent_counter = Counter(str(record.get("intent", "")).strip() for record in filtered if record.get("intent"))
    failure_counter = Counter(
        str(record.get("error_category") or record.get("failure_category") or "").strip()
        for record in filtered
        if record_status(record) == "failed" and (record.get("error_category") or record.get("failure_category"))
    )
    output_counter = Counter(str(record.get("output_type", "")).strip() for record in filtered if record.get("output_type"))
    feedback = [
        str(record.get("feedback")).strip()
        for record in filtered
        if str(record.get("feedback", "")).strip()
    ]
    contains_internal_data = any(record.get("data_sources") for record in filtered)

    return {
        "window_days": days,
        "runs": total,
        "success": success_count,
        "failed": failed_count,
        "unknown": statuses.count("unknown"),
        "success_rate": round(success_rate, 4),
        "real_business_input_runs": real_input_count,
        "critical_failures": critical_count,
        "last_run_at": last_run_at,
        "top_intents": [item for item, _ in intent_counter.most_common(5)],
        "failure_categories": [item for item, _ in failure_counter.most_common(5)],
        "outputs": [item for item, _ in output_counter.most_common(5)],
        "user_feedback": feedback[:10],
        "contains_internal_data": contains_internal_data,
    }


def evaluate_candidate(
    skill_dir: Path,
    runs_path: Path,
    *,
    days: int = 14,
    min_runs: int = 3,
    min_success_rate: float = 0.7,
    min_real_inputs: int = 1,
) -> dict[str, Any]:
    metadata = parse_frontmatter(skill_dir)
    skill_name = metadata.get("name") or skill_dir.name
    description = metadata.get("description", "")
    records = load_records(iter_jsonl_files(runs_path))
    summary = summarize_records(records, skill_name, days)

    reasons: list[str] = []
    if not (skill_dir / "SKILL.md").exists():
        reasons.append("缺少 SKILL.md")
    if not description:
        reasons.append("SKILL.md description 为空")
    if summary["runs"] < min_runs:
        reasons.append(f"最近 {days} 天执行次数不足：{summary['runs']} < {min_runs}")
    if summary["success_rate"] < min_success_rate:
        reasons.append(f"成功率不足：{summary['success_rate']:.0%} < {min_success_rate:.0%}")
    if summary["real_business_input_runs"] < min_real_inputs:
        reasons.append(f"真实业务输入次数不足：{summary['real_business_input_runs']} < {min_real_inputs}")
    if summary["critical_failures"] > 0:
        reasons.append(f"存在 critical 失败：{summary['critical_failures']} 次")

    eligible = not reasons
    return {
        "eligible": eligible,
        "status": "candidate" if eligible else "personal_draft",
        "reasons": reasons,
        "skill": {
            "name": skill_name,
            "version": metadata.get("version", "0.1.0"),
            "description": description,
            "path": str(skill_dir),
        },
        "criteria": {
            "window_days": days,
            "min_runs": min_runs,
            "min_success_rate": min_success_rate,
            "min_real_business_inputs": min_real_inputs,
            "allow_critical_failures": 0,
        },
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, required=True, help="目标 Skill 目录")
    parser.add_argument("--runs", type=Path, required=True, help="运行日志 JSONL 文件或目录")
    parser.add_argument("--days", type=int, default=14, help="统计最近多少天，默认 14")
    parser.add_argument("--min-runs", type=int, default=3, help="候选提交最小执行次数，默认 3")
    parser.add_argument("--min-success-rate", type=float, default=0.7, help="最小成功率，默认 0.7")
    parser.add_argument("--min-real-inputs", type=int, default=1, help="最小真实业务输入次数，默认 1")
    parser.add_argument("--output", type=Path, help="可选，将结果写入 JSON 文件")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    parser.add_argument("--fail-on-ineligible", action="store_true", help="未达到门槛时返回非 0")
    args = parser.parse_args()

    result = evaluate_candidate(
        args.skill_dir,
        args.runs,
        days=args.days,
        min_runs=args.min_runs,
        min_success_rate=args.min_success_rate,
        min_real_inputs=args.min_real_inputs,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_ineligible and not result["eligible"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
