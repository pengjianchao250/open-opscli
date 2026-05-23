#!/usr/bin/env python3
"""ASIN 健康诊断执行日志记录器。

将执行摘要追加到 runs/YYYY-MM.jsonl，供后续迭代和候选提交统计使用。
纯 Python 标准库，无第三方依赖。

Usage:
    python record_run.py --intent "诊断ASIN健康度" --status success
    python record_run.py --intent "批量诊断" --status partial --output /tmp/result.json
    python record_run.py --input runs/2026-05.jsonl  # 查看本月执行统计
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 日志目录（与脚本所在目录同级）
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def record_run(
    *,
    intent: str,
    status: str,
    output: str | None = None,
    input_summary: dict | None = None,
    data_sources: list | None = None,
    assertions_passed: int = 0,
    assertions_total: int = 0,
    error_category: str = "",
    feedback: str = "",
    employee: str = "",
    department: str = "",
    runtime: str = "",
) -> str:
    """记录一条执行摘要到 runs/YYYY-MM.jsonl。

    返回记录的 JSON 字符串。
    """
    now = datetime.now(timezone.utc)
    entry = {
        "time": now.isoformat(),
        "employee": employee,
        "department": department,
        "runtime": runtime,
        "skill_name": "ops-asin-health-diagnoser",
        "skill_version": "0.2.0",
        "intent": intent,
        "input_summary": input_summary or {},
        "data_sources": data_sources or [],
        "status": status,
        "output_paths": [output] if output else [],
        "assertions_passed": assertions_passed,
        "assertions_total": assertions_total,
        "error_category": error_category,
        "severity": "critical" if status == "failed" else "",
        "feedback": feedback,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = RUNS_DIR / f"{now.strftime('%Y-%m')}.jsonl"

    line = json.dumps(entry, ensure_ascii=False)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    return line


def show_stats(log_file: str) -> None:
    """显示指定月份的执行统计。"""
    path = Path(log_file)
    if not path.exists():
        print(f"日志文件不存在: {path}")
        return

    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    if not entries:
        print("无执行记录")
        return

    total = len(entries)
    success = sum(1 for e in entries if e.get("status") == "success")
    partial = sum(1 for e in entries if e.get("status") == "partial")
    failed = sum(1 for e in entries if e.get("status") == "failed")

    print(f"执行统计（{path.name}）:")
    print(f"  总执行: {total}")
    print(f"  成功: {success} | 部分成功: {partial} | 失败: {failed}")
    print(f"  成功率: {success / max(total, 1) * 100:.0f}%")


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="ASIN 健康诊断执行日志记录器")
    parser.add_argument("--intent", required=True, help="执行意图/业务目的")
    parser.add_argument("--status", required=True, choices=["success", "partial", "failed"],
                        help="执行状态")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--input-summary", help="输入摘要 JSON")
    parser.add_argument("--employee", default="", help="执行人")
    parser.add_argument("--department", default="", help="部门")
    parser.add_argument("--runtime", default="", help="运行环境（claude/codex/opencode 等）")
    parser.add_argument("--feedback", default="", help="用户反馈")
    parser.add_argument("--error-category", default="", help="失败原因分类")
    parser.add_argument("--show", metavar="LOG_FILE", help="显示指定日志文件的统计")
    args = parser.parse_args()

    if args.show:
        show_stats(args.show)
        return

    input_summary = {}
    if args.input_summary:
        try:
            input_summary = json.loads(args.input_summary)
        except json.JSONDecodeError:
            input_summary = {"raw": args.input_summary}

    result = record_run(
        intent=args.intent,
        status=args.status,
        output=args.output,
        input_summary=input_summary,
        employee=args.employee,
        department=args.department,
        runtime=args.runtime,
        feedback=args.feedback,
        error_category=args.error_category,
    )
    print(result)


if __name__ == "__main__":
    main()
