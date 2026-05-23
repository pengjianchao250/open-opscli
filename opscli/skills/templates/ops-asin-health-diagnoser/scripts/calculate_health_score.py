#!/usr/bin/env python3
"""ASIN 健康评分计算器 — 统一入口。

支持 CLI 和 MCP 两种场景，通过 stdin 或 --input 读取 JSON 数据。
纯 Python 标准库，无第三方依赖。

Usage:
    echo '{"asin":"B08X","metrics":{...}}' | python calculate_health_score.py --pretty
    python calculate_health_score.py --input /tmp/asin.json --pretty
    python calculate_health_score.py --input /tmp/batch.json --batch --pretty
    python calculate_health_score.py --input /tmp/data.json --weights '{"gross_profit_percent":0.40}' --pretty
    python calculate_health_score.py --input /tmp/data.json --benchmarks '{"gross_profit_percent":{"healthy":0.25}}' --pretty
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
        raise ValueError("缺少必要字段: metrics")

    result = calculate_health_score(metrics, weights, benchmarks)

    result["asin"] = asin
    result["product_name"] = product_name
    result["date_range"] = date_range
    result["formatted_diagnosis"] = format_diagnosis(result, asin, product_name, date_range)

    return result


def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="ASIN 健康评分计算器")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--batch", action="store_true", help="批量模式（输入为 JSON 数组）")
    parser.add_argument("--weights", help="自定义权重 JSON 字符串")
    parser.add_argument("--benchmarks", help="自定义阈值 JSON 字符串")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    # 解析可选的自定义权重和阈值
    custom_weights = _parse_json_arg(args.weights, "--weights")
    custom_benchmarks = _parse_json_arg(args.benchmarks, "--benchmarks")

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        input_data = json.loads(raw)

        # 合并命令行传入的权重和阈值到单条数据
        if isinstance(input_data, dict):
            _merge_overrides(input_data, custom_weights, custom_benchmarks)

        if args.batch:
            if not isinstance(input_data, list):
                raise ValueError("批量模式要求输入为 JSON 数组")
            output = _process_batch(input_data, custom_weights, custom_benchmarks)
        else:
            result = process_single(input_data)
            output = {"success": True, "data": result}

        indent = 2 if args.pretty else None
        print(json.dumps(output, indent=indent, ensure_ascii=False))

    except (ValueError, json.JSONDecodeError) as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)
    except Exception as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)


def _process_batch(
    items: list,
    custom_weights: dict | None,
    custom_benchmarks: dict | None,
) -> dict:
    """处理批量 ASIN 诊断，按评分降序排列。"""
    results = []
    for item in items:
        _merge_overrides(item, custom_weights, custom_benchmarks)
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

    # 按健康评分降序
    results.sort(
        key=lambda x: x.get("health_score", 0) if x.get("status") == "success" else 0,
        reverse=True,
    )

    success_count = sum(1 for r in results if r.get("status") == "success")
    return {
        "success": True,
        "data": results,
        "summary": {
            "total": len(results),
            "success": success_count,
            "error": len(results) - success_count,
            "avg_score": round(
                sum(r.get("health_score", 0) for r in results if r.get("status") == "success")
                / max(success_count, 1),
                1,
            ),
        },
    }


def _merge_overrides(
    item: dict,
    custom_weights: dict | None,
    custom_benchmarks: dict | None,
) -> None:
    """合并命令行传入的权重和阈值到数据项。"""
    if custom_weights:
        item.setdefault("weights", {}).update(custom_weights)
    elif "weights" not in item:
        item["weights"] = None
    if custom_benchmarks:
        item.setdefault("benchmarks", {}).update(custom_benchmarks)
    elif "benchmarks" not in item:
        item["benchmarks"] = None


def _parse_json_arg(value: str | None, arg_name: str) -> dict | None:
    """解析命令行 JSON 参数。"""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        _emit_error("JSONDecodeError", f"无效 {arg_name} JSON: {e}")
        sys.exit(1)


def _emit_error(error_type: str, message: str) -> None:
    """输出错误 JSON。"""
    error_result = {"success": False, "error": {"type": error_type, "message": message}}
    print(json.dumps(error_result, indent=2, ensure_ascii=False))
    print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
