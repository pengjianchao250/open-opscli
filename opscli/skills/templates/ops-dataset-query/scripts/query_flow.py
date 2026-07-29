#!/usr/bin/env python3
"""低调用一体化入口：一次规划，明确可执行时直接运行原始查询模板。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Sequence

import core
import query_plan
import run_query


def execute_flow(
    query: str,
    requested_fields: Sequence[str] = (),
    *,
    result_dir: Path | str = Path("."),
    preview_rows: int = 20,
    auto_upgrade: bool = True,
    auto_enum: bool = True,
) -> int:
    """规划一次；仅 planned 数据集查询进入执行器，其他路由原样返回合同。"""
    plan = query_plan.build_model_query_plan(
        query,
        requested_fields=requested_fields,
        auto_upgrade=auto_upgrade,
        auto_enum=auto_enum,
    )
    if plan.get("query_mode") != "dataset_query" or plan.get("status") != "planned":
        print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))
        return 0

    with tempfile.TemporaryDirectory(prefix="ops-dataset-query-") as temp_dir:
        plan_path = Path(temp_dir) / "query-plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return run_query.main(
            [
                "--plan-file",
                str(plan_path),
                "--result-dir",
                str(result_dir),
                "--preview-rows",
                str(preview_rows),
            ]
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="", help="用户原始查询")
    parser.add_argument("--query-file", default="", help="从 UTF-8 文件读取用户原始查询")
    parser.add_argument("--field", action="append", default=[], help="补充点名字段，可重复")
    parser.add_argument("--result-dir", default=".", help="完整查询结果落盘目录")
    parser.add_argument("--preview-rows", type=int, default=20)
    parser.add_argument("--no-auto-upgrade", action="store_true")
    parser.add_argument("--no-auto-enum", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：失败时返回简洁中文 JSON，避免裸 traceback。"""
    # 入口先切 UTF-8 stdio：一体化流程的中文 JSON 需被 Agent 原样读取
    core.force_utf8_stdio()
    args = _parse_args(argv)
    try:
        query = (
            Path(args.query_file).read_text(encoding="utf-8")
            if args.query_file
            else args.query
        ).strip()
        if not query:
            raise ValueError("缺少用户原始查询。")
        return execute_flow(
            query,
            requested_fields=args.field,
            result_dir=args.result_dir,
            preview_rows=args.preview_rows,
            auto_upgrade=not args.no_auto_upgrade,
            auto_enum=not args.no_auto_enum,
        )
    except Exception as error:  # noqa: BLE001 —— 入口需向 Agent 返回结构化恢复信息
        print(
            json.dumps(
                {
                    "status": "flow_error",
                    "error": str(error)[:200],
                    "next_action_zh": "保留用户原始查询重试一次；仍失败则按反馈规范提交并停止。",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
