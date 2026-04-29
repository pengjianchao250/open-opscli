#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
透视图配置生成器 (build_perspective_config.py)

功能：根据用户输入的分析目标、维度、指标等，生成完整的 BI 透视图配置 JSON。
输入：JSON（通过 --input 文件路径或 stdin 传入）
输出：JSON（完整透视图配置）

CLI 模式：直接输出分析结果
MCP 模式：请使用 build_perspective_config_mcp.py（输出带 success 包裹）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import build_config, match_template


def main() -> None:
    parser = argparse.ArgumentParser(description="透视图配置生成器（CLI 模式）")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        if args.input:
            raw = Path(args.input).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        if not raw.strip():
            result = {"success": False, "error": "输入为空，请通过 stdin 传入 JSON 配置参数"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)

        params = json.loads(raw)

        goal = params.get("goal", "")
        scope = params.get("scope")
        time_range = params.get("time_range")
        kwargs = {k: v for k, v in params.items() if k not in ("goal", "scope", "time_range")}

        config = build_config(goal, scope, time_range, **kwargs)

        result = {
            "success": config["validation"]["passed"],
            "config": config,
            "matched_template": match_template(goal),
            "warnings": config["validation"]["errors"] if not config["validation"]["passed"] else []
        }
        indent = 2 if args.pretty else None
        print(json.dumps(result, indent=indent, ensure_ascii=False))
        sys.exit(0 if config["validation"]["passed"] else 1)

    except (ValueError, json.JSONDecodeError) as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)
    except Exception as e:
        _emit_error(type(e).__name__, str(e))
        sys.exit(1)


def _emit_error(error_type: str, message: str) -> None:
    error_result = {"success": False, "error": f"{error_type}: {message}"}
    print(json.dumps(error_result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
