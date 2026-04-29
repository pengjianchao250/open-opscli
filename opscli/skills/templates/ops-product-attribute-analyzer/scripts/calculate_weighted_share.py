#!/usr/bin/env python3
"""
Script Name: calculate_weighted_share.py
Description: 计算单个维度的销售加权市场份额
Author: opscli Team
Date: 2026-04-28

输入：JSON（通过 --input 文件路径或 stdin 传入）
输出：JSON（加权份额计算结果）

CLI 模式：直接输出结果
MCP 模式：请使用 calculate_weighted_share_mcp.py（输出带 success 包裹）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import calculate_weighted_share


def main() -> None:
    parser = argparse.ArgumentParser(description="加权份额计算（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        if not raw.strip():
            result = {"status": "error", "message": "输入为空"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)

        params = json.loads(raw)

        if "dimension" not in params:
            raise ValueError("Missing required field: dimension")
        if "data" not in params:
            raise ValueError("Missing required field: data")

        result = calculate_weighted_share(
            params["dimension"], params["data"],
            params.get("weight_field", "order_qty"), params.get("count_field", "asin")
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
