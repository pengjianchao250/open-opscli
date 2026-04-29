#!/usr/bin/env python3
"""
Script Name: calculate_weighted_share.py
Description: 计算单个维度的销售加权市场份额
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, List, Optional


def calculate_weighted_share(
    dimension: str,
    data: List[Dict[str, Any]],
    weight_field: str = "order_qty",
    count_field: str = "asin"
) -> Dict[str, Any]:
    """
    计算指定维度的销售加权市场份额。

    算法说明：
    1. 按 dimension 字段分组汇总 weight_field（默认 order_qty）
    2. 计算每个分组的销量占总销量的比例（market share）
    3. 计算每个分组的 ASIN 数量（count_field）
    4. 计算 sales_per_unit = 分组销量 / 分组 ASIN 数

    Args:
        dimension: 分析维度字段名，如 "development_type"
        data: 原始数据行列表，每行包含 dimension、weight_field、count_field 等字段
        weight_field: 权重字段名，默认 "order_qty"
        count_field: 计数维度字段名，默认 "asin"

    Returns:
        包含维度、总权重、总条数、各分组份额等信息的字典
    """
    if not data:
        return {
            "dimension": dimension,
            "total_weight": 0,
            "total_count": 0,
            "shares": [],
            "status": "warning",
            "message": "输入数据为空"
        }

    # 按维度字段分组聚合
    groups: Dict[str, Dict[str, Any]] = {}
    for row in data:
        key = str(row.get(dimension, "Unknown"))
        weight = float(row.get(weight_field, 0) or 0)
        # count_field 支持去重计数：如果 row 里有 count_field 则用该值，否则每行计 1
        count_val = int(row.get(count_field, 1) or 1)

        if key not in groups:
            groups[key] = {"weight": 0.0, "count": 0}
        groups[key]["weight"] += weight
        groups[key]["count"] += count_val

    total_weight = sum(g["weight"] for g in groups.values())
    total_count = sum(g["count"] for g in groups.values())

    if total_weight == 0:
        return {
            "dimension": dimension,
            "total_weight": 0,
            "total_count": total_count,
            "shares": [],
            "status": "warning",
            "message": "总销量为 0，无法计算份额"
        }

    shares = []
    for key, agg in groups.items():
        share = agg["weight"] / total_weight if total_weight > 0 else 0.0
        avg_per_unit = agg["weight"] / agg["count"] if agg["count"] > 0 else 0.0
        shares.append({
            "value": key,
            "weight": round(agg["weight"], 2),
            "count": agg["count"],
            "share": round(share, 4),
            "avg_per_unit": round(avg_per_unit, 2)
        })

    # 按 share 降序排列
    shares.sort(key=lambda x: x["share"], reverse=True)

    return {
        "dimension": dimension,
        "total_weight": round(total_weight, 2),
        "total_count": total_count,
        "shares": shares,
        "status": "success"
    }


def main():
    """主执行函数，从标准输入读取 JSON 并输出计算结果。"""
    try:
        input_data = json.loads(sys.stdin.read())

        # 校验必填字段
        if "dimension" not in input_data:
            raise ValueError("Missing required field: dimension")
        if "data" not in input_data:
            raise ValueError("Missing required field: data")

        dimension = input_data["dimension"]
        data = input_data["data"]
        weight_field = input_data.get("weight_field", "order_qty")
        count_field = input_data.get("count_field", "asin")

        result = calculate_weighted_share(dimension, data, weight_field, count_field)

        # 输出 JSON 结果
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except ValueError as e:
        error_result = {"status": "error", "error_type": "ValueError", "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    except json.JSONDecodeError as e:
        error_result = {"status": "error", "error_type": "JSONDecodeError", "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        error_result = {"status": "error", "error_type": type(e).__name__, "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
