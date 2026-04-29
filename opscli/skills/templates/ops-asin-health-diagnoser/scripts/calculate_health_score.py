#!/usr/bin/env python3
"""
Script Name: calculate_health_score.py
Description: Calculate ASIN health score from operational metrics (CLI mode)
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"asin": "B08XXXXXX", "metrics": {...}}' | python calculate_health_score.py
    python calculate_health_score.py --input /tmp/metrics.json --pretty
    python calculate_health_score.py --input /tmp/batch.json --batch --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (
    DEFAULT_WEIGHTS,
    DEFAULT_BENCHMARKS,
    calculate_health_score,
    format_diagnosis,
)


def process_single(input_data: dict) -> dict:
    """处理单个 ASIN 诊断。"""
    asin = input_data.get("asin", "Unknown")
    product_name = input_data.get("product_name", "")
    date_range = input_data.get("date_range", "")
    metrics = input_data.get("metrics", {})
    weights = input_data.get("weights")
    benchmarks = input_data.get("benchmarks")

    if not metrics:
        raise ValueError("Missing required field: metrics")

    result = calculate_health_score(metrics, weights, benchmarks)

    result["asin"] = asin
    result["product_name"] = product_name
    result["date_range"] = date_range
    result["formatted_diagnosis"] = format_diagnosis(result, asin, product_name, date_range)

    return result


def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="ASIN 健康评分计算器（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--batch", action="store_true", help="批量模式（输入为 JSON 数组）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        input_data = json.loads(raw)

        if args.batch:
            if not isinstance(input_data, list):
                raise ValueError("批量模式要求输入为 JSON 数组")
            results = []
            for item in input_data:
                try:
                    result = process_single(item)
                    result["status"] = "success"
                    results.append(result)
                except Exception as e:
                    results.append({
                        "status": "error",
                        "asin": item.get("asin", "Unknown"),
                        "error": str(e),
                    })
            output = {"success": True, "data": results}
        else:
            result = process_single(input_data)
            output = {"success": True, "data": result}

        indent = 2 if args.pretty else None
        print(json.dumps(output, indent=indent, ensure_ascii=False))

    except ValueError as e:
        _emit_error("ValueError", str(e))
        sys.exit(1)
    except json.JSONDecodeError as e:
        _emit_error("JSONDecodeError", str(e))
        sys.exit(1)
    except Exception as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)


def _emit_error(error_type: str, message: str) -> None:
    """输出错误 JSON。"""
    error_result = {"success": False, "error": {"type": error_type, "message": message}}
    print(json.dumps(error_result, indent=2, ensure_ascii=False))
    print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()