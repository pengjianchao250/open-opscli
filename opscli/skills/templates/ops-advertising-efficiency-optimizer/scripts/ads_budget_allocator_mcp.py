#!/usr/bin/env python3
"""
Script Name: ads_budget_allocator_mcp.py
Description: 广告预算分配优化器（MCP 模式 - 无 opscli 依赖）
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"campaigns": [...], "total_budget": 10000}' | python ads_budget_allocator_mcp.py
    python ads_budget_allocator_mcp.py --input /tmp/budget_input.json --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import optimize_budget


def main() -> None:
    parser = argparse.ArgumentParser(description="广告预算分配优化器（MCP 无状态模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        input_data = json.loads(raw)

        if "campaigns" not in input_data:
            raise ValueError("Missing required field: campaigns")
        if "total_budget" not in input_data:
            raise ValueError("Missing required field: total_budget")

        campaigns = input_data["campaigns"]
        total_budget = float(input_data["total_budget"])

        result = optimize_budget(campaigns, total_budget)
        output = {"success": True, "data": result}

        indent = 2 if args.pretty else None
        print(json.dumps(output, indent=indent, ensure_ascii=False))

    except (ValueError, json.JSONDecodeError) as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)
    except Exception as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)


def _emit_error(error_type: str, message: str) -> None:
    error_result = {"success": False, "error": {"type": error_type, "message": message}}
    print(json.dumps(error_result, indent=2, ensure_ascii=False))
    print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()