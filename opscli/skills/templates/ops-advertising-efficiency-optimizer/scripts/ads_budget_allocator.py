#!/usr/bin/env python3
"""
Script Name: ads_budget_allocator.py
Description: 广告预算分配优化器，基于 ROAS 重新分配预算
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, List


def optimize_budget(
    campaigns: List[Dict[str, Any]],
    total_budget: float
) -> Dict[str, Any]:
    """
    基于 ROAS 的广告预算重新分配优化器。

    算法策略：
    1. 计算每个活动的 ROAS = sales / cost
    2. 按 ROAS 降序排列活动
    3. 优先满足高 ROAS 活动的预算需求：
       - ROAS > 4.0：给予当前花费的 120%（扩大优势）
       - ROAS 2.5-4.0：保持当前花费（维持观察）
       - ROAS < 2.5：削减至当前花费的 50%（止损）
    4. 如果总分配超出 total_budget，按比例压缩
    5. 如果总分配低于 total_budget，将剩余预算追加给最高 ROAS 活动

    Args:
        campaigns: 广告活动列表，每项至少包含 name、current_spend、sales
        total_budget: 总预算上限

    Returns:
        包含分配方案、预期总销售额、预期综合 ROAS 的字典
    """
    if not campaigns:
        return {
            "status": "warning",
            "message": "输入活动列表为空",
            "allocations": []
        }

    if total_budget <= 0:
        raise ValueError("total_budget 必须大于 0")

    # 计算每个活动的 ROAS 并排序
    for camp in campaigns:
        cost = float(camp.get("current_spend", 0))
        sales = float(camp.get("sales", 0))
        camp["roas"] = sales / cost if cost > 0 else 0.0

    sorted_campaigns = sorted(campaigns, key=lambda x: x["roas"], reverse=True)

    # 初步分配
    raw_allocations = []
    total_allocated = 0.0

    for camp in sorted_campaigns:
        roas = camp["roas"]
        current_spend = float(camp.get("current_spend", 0))

        if roas > 4.0:
            allocated = current_spend * 1.2
            strategy = "increase"
        elif roas > 2.5:
            allocated = current_spend
            strategy = "maintain"
        else:
            allocated = current_spend * 0.5
            strategy = "decrease"

        raw_allocations.append({
            "name": camp.get("name", "Unknown"),
            "roas": round(roas, 2),
            "current_spend": round(current_spend, 2),
            "allocated": round(allocated, 2),
            "strategy": strategy
        })
        total_allocated += allocated

    # 预算约束：如果超出 total_budget，按比例压缩
    if total_allocated > total_budget:
        scale = total_budget / total_allocated
        for alloc in raw_allocations:
            alloc["allocated"] = round(alloc["allocated"] * scale, 2)
            alloc["scaled"] = True
        total_allocated = total_budget
    else:
        # 剩余预算追加给最高 ROAS 活动
        remaining = total_budget - total_allocated
        if remaining > 0 and raw_allocations:
            raw_allocations[0]["allocated"] = round(raw_allocations[0]["allocated"] + remaining, 2)
            raw_allocations[0]["extra_budget"] = round(remaining, 2)
        total_allocated = total_budget

    # 预期效果估算
    expected_total_sales = 0.0
    for i, alloc in enumerate(raw_allocations):
        roas = sorted_campaigns[i]["roas"]
        expected_total_sales += alloc["allocated"] * roas

    expected_roas = expected_total_sales / total_allocated if total_allocated > 0 else 0.0

    return {
        "status": "success",
        "total_budget": round(total_budget, 2),
        "total_allocated": round(total_allocated, 2),
        "expected_total_sales": round(expected_total_sales, 2),
        "expected_roas": round(expected_roas, 2),
        "allocations": raw_allocations
    }


def main():
    """主执行函数，从标准输入读取 JSON 并输出预算分配方案。"""
    try:
        input_data = json.loads(sys.stdin.read())

        if "campaigns" not in input_data:
            raise ValueError("Missing required field: campaigns")
        if "total_budget" not in input_data:
            raise ValueError("Missing required field: total_budget")

        campaigns = input_data["campaigns"]
        total_budget = float(input_data["total_budget"])

        result = optimize_budget(campaigns, total_budget)
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
