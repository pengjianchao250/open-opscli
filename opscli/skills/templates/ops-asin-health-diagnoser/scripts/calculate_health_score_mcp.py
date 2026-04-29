#!/usr/bin/env python3
"""
Script Name: calculate_health_score_mcp.py
Description: Calculate ASIN health score from operational metrics (MCP mode - no opscli dependency)
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"asin": "B08XXXXXX", "metrics": {...}}' | python calculate_health_score_mcp.py
    python calculate_health_score_mcp.py --input /tmp/metrics.json --pretty
    python calculate_health_score_mcp.py --input /tmp/batch.json --batch --pretty

MCP 模式说明：
    本脚本不依赖 opscli 命令行工具，仅依赖 Python 标准库。
    数据输入格式与 CLI 版本完全一致，可由 MCP Tool 调用或独立运行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (
    calculate_health_score,
    format_diagnosis,
    DEFAULT_WEIGHTS,
    DEFAULT_BENCHMARKS,
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
    parser = argparse.ArgumentParser(description="ASIN 健康评分计算器（MCP 无状态模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--batch", action="store_true", help="批量模式（输入为 JSON 数组）")
    parser.add_argument("--weights", help="自定义权重 JSON 字符串")
    parser.add_argument("--benchmarks", help="自定义阈值 JSON 字符串")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    # 解析可选的自定义权重和阈值
    custom_weights = None
    if args.weights:
        try:
            custom_weights = json.loads(args.weights)
        except json.JSONDecodeError as e:
            _emit_error("JSONDecodeError", f"Invalid --weights JSON: {e}")
            sys.exit(1)

    custom_benchmarks = None
    if args.benchmarks:
        try:
            custom_benchmarks = json.loads(args.benchmarks)
        except json.JSONDecodeError as e:
            _emit_error("JSONDecodeError", f"Invalid --benchmarks JSON: {e}")
            sys.exit(1)

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        input_data = json.loads(raw)

        # 合并命令行传入的权重和阈值
        if isinstance(input_data, dict):
            if custom_weights:
                input_data.setdefault("weights", {}).update(custom_weights)
            elif "weights" not in input_data:
                input_data["weights"] = None
            if custom_benchmarks:
                input_data.setdefault("benchmarks", {}).update(custom_benchmarks)
            elif "benchmarks" not in input_data:
                input_data["benchmarks"] = None

        if args.batch:
            if not isinstance(input_data, list):
                raise ValueError("批量模式要求输入为 JSON 数组")
            results = []
            for item in input_data:
                # 对每个 item 合并全局权重和阈值
                item_weights = item.get("weights") or custom_weights
                item_benchmarks = item.get("benchmarks") or custom_benchmarks
                if item_weights:
                    item["weights"] = item_weights
                if item_benchmarks:
                    item["benchmarks"] = item_benchmarks
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

            # 按健康评分排序（降序）
            results.sort(key=lambda x: x.get("health_score", 0) if x.get("status") == "success" else 0, reverse=True)

            output = {
                "success": True,
                "data": results,
                "summary": {
                    "total": len(results),
                    "success": sum(1 for r in results if r.get("status") == "success"),
                    "error": sum(1 for r in results if r.get("status") == "error"),
                    "avg_score": round(
                        sum(r.get("health_score", 0) for r in results if r.get("status") == "success")
                        / max(sum(1 for r in results if r.get("status") == "success"), 1),
                        1,
                    ),
                },
            }
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