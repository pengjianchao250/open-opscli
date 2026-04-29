#!/usr/bin/env python3
"""
Script Name: analyze_ads_efficiency_mcp.py
Description: 广告效率分析主脚本（MCP 模式 - 无 opscli 依赖）
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"campaigns": [...], "benchmarks": {...}}' | python analyze_ads_efficiency_mcp.py
    python analyze_ads_efficiency_mcp.py --input /tmp/ads_data.json --pretty
    python analyze_ads_efficiency_mcp.py --input /tmp/ads_data.json --benchmarks '{"acos_target": 0.18}' --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (
    analyze_ad_efficiency,
    DEFAULT_BENCHMARKS,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="广告效率分析器（MCP 无状态模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--benchmarks", help="自定义基准 JSON 字符串")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

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

        if isinstance(input_data, dict):
            campaigns = input_data.get("campaigns", [])
            benchmarks = input_data.get("benchmarks") or custom_benchmarks or DEFAULT_BENCHMARKS
            if custom_benchmarks and not input_data.get("benchmarks"):
                input_data["benchmarks"] = custom_benchmarks
        else:
            _emit_error("ValueError", "输入必须是 JSON 对象")
            sys.exit(1)

        result = analyze_ad_efficiency(campaigns, benchmarks)
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