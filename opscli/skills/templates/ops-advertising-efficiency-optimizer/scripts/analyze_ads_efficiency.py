#!/usr/bin/env python3
"""
Script Name: analyze_ads_efficiency.py
Description: 广告效率分析主脚本（CLI 模式）
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"campaigns": [...], "benchmarks": {...}}' | python analyze_ads_efficiency.py
    python analyze_ads_efficiency.py --input /tmp/ads_data.json --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import analyze_ad_efficiency, DEFAULT_BENCHMARKS


def main() -> None:
    parser = argparse.ArgumentParser(description="广告效率分析器（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        input_data = json.loads(raw)

        campaigns = input_data.get("campaigns")
        if not campaigns:
            raise ValueError("Missing required field: campaigns")

        benchmarks = input_data.get("benchmarks") or DEFAULT_BENCHMARKS
        result = analyze_ad_efficiency(campaigns, benchmarks)

        print(json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False))

    except (ValueError, json.JSONDecodeError) as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)
    except Exception as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)


def _emit_error(error_type: str, message: str) -> None:
    error_result = {"status": "error", "error_type": error_type, "message": message}
    print(json.dumps(error_result, indent=2, ensure_ascii=False))
    print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
