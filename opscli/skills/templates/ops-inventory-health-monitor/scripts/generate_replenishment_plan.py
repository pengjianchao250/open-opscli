#!/usr/bin/env python3
"""
Script Name: generate_replenishment_plan.py
Description: 生成补货计划，计算补货量和建议发货时间
Author: opscli Team
Date: 2026-04-28

输入：JSON（通过 --input 文件路径或 stdin 传入）
输出：JSON（补货计划结果）

CLI 模式：直接输出分析结果
MCP 模式：请使用 generate_replenishment_plan_mcp.py（输出带 success 包裹）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import calculate_replenishment


def main() -> None:
    parser = argparse.ArgumentParser(description="补货计划生成（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        if not raw.strip():
            result = {"status": "error", "message": "输入为空，请通过 stdin 传入 JSON 参数"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)

        params = json.loads(raw)

        if "sku_data" not in params:
            raise ValueError("Missing required field: sku_data")
        if "target_days" not in params:
            raise ValueError("Missing required field: target_days")
        if "lead_time_days" not in params:
            raise ValueError("Missing required field: lead_time_days")

        result = calculate_replenishment(
            params["sku_data"],
            int(params["target_days"]),
            int(params["lead_time_days"]),
            float(params.get("safety_factor", 1.5)),
            int(params.get("buffer_days", 7)),
            params.get("reference_date")
        )
        indent = 2 if args.pretty else None
        print(json.dumps(result, indent=indent, ensure_ascii=False))

    except (ValueError, json.JSONDecodeError) as e:
        error_result = {"status": "error", "error_type": type(e).__name__, "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {"status": "error", "error_type": type(e).__name__, "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
