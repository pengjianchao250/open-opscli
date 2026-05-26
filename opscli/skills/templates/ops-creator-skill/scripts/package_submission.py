#!/usr/bin/env python3
"""生成内测候选 Skill 的脱敏提交包。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qualify_candidate import evaluate_candidate


EXCLUDE_DIRS = {".git", "__pycache__", "runs", "diary", "outputs", "dist", "tmp", ".pytest_cache"}
EXCLUDE_FILES = {".DS_Store", ".env"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".skill"}
SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|cookie|authorization)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def should_exclude(path: Path, skill_dir: Path) -> bool:
    rel = path.relative_to(skill_dir)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    if rel.name in EXCLUDE_FILES:
        return True
    if rel.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def scan_sensitive(skill_dir: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked_files = 0
    excluded_paths: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        if path.is_dir():
            continue
        if should_exclude(path, skill_dir):
            excluded_paths.append(str(path.relative_to(skill_dir)))
            continue
        checked_files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            findings.append({
                "path": str(path.relative_to(skill_dir)),
                "reason": "无法读取文件",
            })
            continue
        for pattern in SENSITIVE_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append({
                    "path": str(path.relative_to(skill_dir)),
                    "reason": "疑似敏感信息",
                    "pattern": pattern.pattern,
                    "sample": match.group(0)[:80],
                })
                break
    return {
        "contains_sensitive_data": bool(findings),
        "findings": findings,
        "checked_files": checked_files,
        "excluded_paths": sorted(set(excluded_paths)),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def create_skill_zip(skill_dir: Path, zip_path: Path) -> list[str]:
    added: list[str] = []
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            if not path.is_file() or should_exclude(path, skill_dir):
                continue
            arcname = Path(skill_dir.name) / path.relative_to(skill_dir)
            archive.write(path, arcname)
            added.append(str(arcname))
    return added


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, required=True, help="要提交的 Skill 目录")
    parser.add_argument("--runs", type=Path, required=True, help="运行日志 JSONL 文件或目录")
    parser.add_argument("--output-dir", type=Path, required=True, help="提交包输出根目录")
    parser.add_argument("--employee", required=True, help="提交人")
    parser.add_argument("--department", default="", help="提交人所在部门")
    parser.add_argument("--runtime", default="", help="使用运行时，如 codex/claude/cursor")
    parser.add_argument("--business-use", default="", help="业务用途")
    parser.add_argument("--submit-reason", default="", help="提交理由")
    parser.add_argument("--days", type=int, default=14, help="统计最近多少天，默认 14")
    parser.add_argument("--min-runs", type=int, default=3)
    parser.add_argument("--min-success-rate", type=float, default=0.7)
    parser.add_argument("--min-real-inputs", type=int, default=1)
    parser.add_argument("--allow-unqualified", action="store_true", help="未达到候选门槛也生成提交包")
    parser.add_argument("--allow-sensitive", action="store_true", help="发现疑似敏感信息也继续打包")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的输出目录")
    args = parser.parse_args()

    skill_dir = args.skill_dir.resolve()
    result = evaluate_candidate(
        skill_dir,
        args.runs,
        days=args.days,
        min_runs=args.min_runs,
        min_success_rate=args.min_success_rate,
        min_real_inputs=args.min_real_inputs,
    )
    if not result["eligible"] and not args.allow_unqualified:
        print(json.dumps({
            "success": False,
            "error": "未达到候选提交门槛",
            "qualification": result,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    safety = scan_sensitive(skill_dir)
    if safety["contains_sensitive_data"] and not args.allow_sensitive:
        print(json.dumps({
            "success": False,
            "error": "发现疑似敏感信息，已停止打包",
            "safety_check": safety,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3

    skill_name = result["skill"]["name"]
    version = result["skill"].get("version") or "0.1.0"
    safe_employee = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "-", args.employee.strip(), flags=re.UNICODE) or "unknown"
    destination = args.output_dir / safe_employee / skill_name / version
    if destination.exists():
        if not args.force:
            print(f"输出目录已存在: {destination}。如需覆盖请加 --force。", file=sys.stderr)
            return 4
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    zip_path = destination / "skill.zip"
    added_files = create_skill_zip(skill_dir, zip_path)

    summary = result["summary"]
    submission = {
        "employee": args.employee,
        "department": args.department,
        "skill_name": skill_name,
        "version": version,
        "runtime": args.runtime,
        "status": "candidate" if result["eligible"] else "personal_draft",
        "business_use": args.business_use,
        "run_count_14d": summary["runs"],
        "success_rate": summary["success_rate"],
        "last_run_at": summary["last_run_at"],
        "contains_internal_data": summary["contains_internal_data"],
        "contains_sensitive_data": safety["contains_sensitive_data"],
        "submit_reason": args.submit_reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    run_summary = {
        "runs": summary["runs"],
        "success": summary["success"],
        "failed": summary["failed"],
        "unknown": summary["unknown"],
        "success_rate": summary["success_rate"],
        "top_intents": summary["top_intents"],
        "failure_categories": summary["failure_categories"],
        "outputs": summary["outputs"],
        "user_feedback": summary["user_feedback"],
    }

    write_json(destination / "submission.json", submission)
    write_json(destination / "run-summary.json", run_summary)
    write_json(destination / "safety-check.json", safety)
    write_json(destination / "qualification.json", result)

    response = {
        "success": True,
        "output_dir": str(destination),
        "skill_zip": str(zip_path),
        "files_added_to_zip": len(added_files),
        "submission": submission,
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
