#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
退款优先级矩阵计算脚本

功能：构建退款优先级矩阵，按 Critical/Important/Nice-to-have 三级分类
输入：JSON（通过 --input 文件路径或 stdin 传入）
输出：JSON（优先级矩阵和排序建议）

CLI 模式：直接输出分析结果
MCP 模式：请使用 calculate_priority_matrix_mcp.py（输出带 success 包裹）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import build_priority_matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="退款优先级矩阵（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        if not raw.strip():
            result = {"status": "error", "message": "缺少输入数据"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)

        data = json.loads(raw)

        if "refund_data" not in data:
            raise ValueError("Missing required field: refund_data")

        result = build_priority_matrix(data)
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
