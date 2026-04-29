#!/usr/bin/env python3
"""
Script Name: calculate_roas_acos.py
Description: 快速 ROAS/ACOS 计算器（CLI 模式）
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"cost": 1000, "sales": 5000}' | python calculate_roas_acos.py
    python calculate_roas_acos.py --input /tmp/roas_input.json --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import calculate_roas_acos


def main() -> None:
    parser = argparse.ArgumentParser(description="ROAS/ACOS 快速计算器（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        input_data = json.loads(raw)

        if "cost" in input_data and "sales" in input_data:
            cost = float(input_data["cost"])
            sales = float(input_data["sales"])
            clicks = input_data.get("clicks")
            impressions = input_data.get("impressions")
            conversions = input_data.get("conversions")
        elif "campaign" in input_data:
            campaign = input_data["campaign"]
            cost = float(campaign.get("cost", 0))
            sales = float(campaign.get("sales", 0))
            clicks = campaign.get("clicks")
            impressions = campaign.get("impressions")
            conversions = campaign.get("conversions")
        else:
            raise ValueError("Missing required fields: cost + sales, or campaign object")

        result = calculate_roas_acos(
            cost, sales,
            clicks=float(clicks) if clicks is not None else None,
            impressions=float(impressions) if impressions is not None else None,
            conversions=float(conversions) if conversions is not None else None,
        )

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
