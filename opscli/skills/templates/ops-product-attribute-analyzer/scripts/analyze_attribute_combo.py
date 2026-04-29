#!/usr/bin/env python3
"""
Script Name: analyze_attribute_combo.py
Description: 分析属性组合，识别供给不足的高价值机会
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, List


def find_opportunities(
    combo_data: List[Dict[str, Any]],
    threshold_ratio: float = 1.5,
    max_market_share: float = 0.20
) -> Dict[str, Any]:
    """
    识别属性组合中的供给不足机会点。

    核心算法：
    1. 计算所有组合的平均 sales_per_asin
    2. 对于每个组合：
       - 如果 sales_per_asin > avg * threshold_ratio 且 market_share < max_market_share
       - 则标记为机会点，计算 opportunity_score
    3. opportunity_score = (sales_per_asin / avg) * (1 - market_share)
       该分数同时考虑了「效率溢价」和「供给缺口」

    Args:
        combo_data: 属性组合数据列表，每项至少包含：
                    - dimensions: 组合标签（字符串或列表）
                    - total_sales: 总销量
                    - asin_count: ASIN 数量
                    - market_share: 市场份额（0-1）
        threshold_ratio: sales_per_asin 高于均值的倍数阈值，默认 1.5
        max_market_share: 允许的最大市场份额上限，默认 0.20

    Returns:
        包含机会列表、平均 sales_per_asin、统计概览的字典
    """
    if not combo_data:
        return {
            "opportunities": [],
            "avg_sales_per_asin": 0.0,
            "total_combos": 0,
            "status": "warning",
            "message": "输入数据为空"
        }

    # 计算全局平均 sales_per_asin（加权平均）
    total_sales = sum(d.get("total_sales", 0) for d in combo_data)
    total_asins = sum(d.get("asin_count", 0) for d in combo_data)
    avg_sales_per_asin = total_sales / total_asins if total_asins > 0 else 0.0

    if avg_sales_per_asin == 0:
        return {
            "opportunities": [],
            "avg_sales_per_asin": 0.0,
            "total_combos": len(combo_data),
            "status": "warning",
            "message": "平均单 ASIN 销量为 0，无法识别机会"
        }

    opportunities = []
    for combo in combo_data:
        sales = float(combo.get("total_sales", 0))
        asin_count = int(combo.get("asin_count", 0))
        market_share = float(combo.get("market_share", 0))

        if asin_count <= 0:
            continue

        spa = sales / asin_count

        # 机会判定：单 ASIN 销量显著高于均值，但市场份额低（供给不足）
        if spa > avg_sales_per_asin * threshold_ratio and market_share < max_market_share:
            opportunity_score = (spa / avg_sales_per_asin) * (1 - market_share)
            opportunities.append({
                "combo": combo.get("dimensions", "Unknown"),
                "sales_per_asin": round(spa, 2),
                "market_share": round(market_share, 4),
                "asin_count": asin_count,
                "total_sales": round(sales, 2),
                "opportunity_score": round(opportunity_score, 4),
                "vs_avg_ratio": round(spa / avg_sales_per_asin, 2)
            })

    # 按 opportunity_score 降序排列
    opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)

    return {
        "opportunities": opportunities,
        "avg_sales_per_asin": round(avg_sales_per_asin, 2),
        "total_combos": len(combo_data),
        "threshold_ratio": threshold_ratio,
        "max_market_share": max_market_share,
        "status": "success"
    }


def main():
    """主执行函数，从标准输入读取 JSON 并输出分析结果。"""
    try:
        input_data = json.loads(sys.stdin.read())

        if "combo_data" not in input_data:
            raise ValueError("Missing required field: combo_data")

        combo_data = input_data["combo_data"]
        threshold_ratio = input_data.get("threshold_ratio", 1.5)
        max_market_share = input_data.get("max_market_share", 0.20)

        result = find_opportunities(combo_data, threshold_ratio, max_market_share)

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
