#!/usr/bin/env python3
"""
Script Name: calculate_inventory_health_mcp.py
Description: 计算库存健康评级和风险识别（MCP 模式 - 无 opscli 依赖）
Author: opscli Team
Date: 2026-04-29

Usage:
    echo '{"sku":"SKU001",...}' | python calculate_inventory_health_mcp.py
    python calculate_inventory_health_mcp.py --input /tmp/health.json --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import calculate_inventory_health


def main() -> None:
    parser = argparse.ArgumentParser(description="库存健康度计算（MCP 无状态模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        if not raw.strip():
            result = {"success": False, "error": "输入为空，请通过 stdin 传入 JSON 参数"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)

        params = json.loads(raw)

        if "sku" not in params:
            raise ValueError("Missing required field: sku")
        if "inventory" not in params:
            raise ValueError("Missing required field: inventory")
        if "sales" not in params:
            raise ValueError("Missing required field: sales")

        result = calculate_inventory_health(
            params["sku"], params["inventory"], params["sales"], params.get("thresholds")
        )

        output = {"success": result.get("status") == "success", "data": result}
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
