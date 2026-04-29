#!/usr/bin/env python3
"""
Script Name: calculate_inventory_health.py
Description: 计算库存健康评级和风险识别
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, List, Optional


def rate_inventory(
    sell_qty_days: float,
    platform_qty: float,
    avg_daily_sales: float
) -> str:
    """
    库存健康度评级（A/B/C/D/F）。

    评级规则：
    - A: 周转 < 45 天 且 平台覆盖 > 14 天 → 健康
    - B: 周转 < 60 天 且 平台覆盖 > 7 天 → 良好
    - C: 周转 < 90 天 且 平台覆盖 > 3 天 → 一般
    - D: 周转 < 120 天 → 预警
    - F: 周转 >= 120 天 → 滞销

    Args:
        sell_qty_days: 可售周转天数
        platform_qty: 平台仓库存数量
        avg_daily_sales: 日均销量

    Returns:
        评级字母 A/B/C/D/F
    """
    platform_days = platform_qty / avg_daily_sales if avg_daily_sales > 0 else 999

    if sell_qty_days < 45 and platform_days > 14:
        return "A"
    elif sell_qty_days < 60 and platform_days > 7:
        return "B"
    elif sell_qty_days < 90 and platform_days > 3:
        return "C"
    elif sell_qty_days < 120:
        return "D"
    else:
        return "F"


def calculate_inventory_health(
    sku: str,
    inventory: Dict[str, Any],
    sales: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    计算库存健康度并识别风险。

    Args:
        sku: SKU 编码
        inventory: 库存数据，包含 platform_qty、transfer_available_qty、
                   transfer_lock_qty、intransit_qty、total_qty
        sales: 销售数据，包含 average_daily_sales_volume、last_7d_avg、last_30d_avg
        thresholds: 可选自定义阈值

    Returns:
        包含健康评级、风险列表、建议行动的字典
    """
    platform_qty = float(inventory.get("platform_qty", 0))
    transfer_available = float(inventory.get("transfer_available_qty", 0))
    transfer_lock = float(inventory.get("transfer_lock_qty", 0))
    intransit = float(inventory.get("intransit_qty", 0))
    total_qty = float(inventory.get("total_qty", 0))

    avg_daily = float(sales.get("average_daily_sales_volume", 0))
    thresholds = thresholds or {}
    stockout_risk_days = thresholds.get("stockout_risk_days", 14)
    warning_days = thresholds.get("warning_days", 90)

    # 计算各仓覆盖天数
    platform_days = platform_qty / avg_daily if avg_daily > 0 else 999
    transfer_days = transfer_available / avg_daily if avg_daily > 0 else 999
    total_available = platform_qty + transfer_available + intransit
    total_days_cover = total_available / avg_daily if avg_daily > 0 else 999

    # 周转天数（优先使用传入值，否则估算）
    sell_qty_days = float(inventory.get("sell_qty_days", total_days_cover))

    # 健康评级
    health_rating = rate_inventory(sell_qty_days, platform_qty, avg_daily)

    # 风险识别
    risks = []
    recommendations = []

    # 断货风险
    if platform_days < stockout_risk_days:
        severity = "high" if platform_days < 7 else "medium"
        risks.append({
            "type": "stockout",
            "severity": severity,
            "days_until_stockout": round(platform_days, 1),
            "message": f"平台仓仅剩 {platform_days:.1f} 天库存（健康线 > {stockout_risk_days} 天）"
        })
        # 计算建议补货量
        target_inventory = stockout_risk_days * 2 * avg_daily
        replenish_qty = max(0, target_inventory - total_available)
        recommendations.append({
            "action": "replenish",
            "quantity": round(replenish_qty),
            "urgency": "high" if severity == "high" else "medium",
            "reason": f"平台仓覆盖天数 {platform_days:.1f} 天低于安全线"
        })

    # 锁定库存风险
    transfer_total = transfer_available + transfer_lock
    lock_ratio = transfer_lock / transfer_total if transfer_total > 0 else 0
    if lock_ratio > 0.20:
        severity = "high" if lock_ratio > 0.50 else "medium"
        risks.append({
            "type": "high_lock_ratio",
            "severity": severity,
            "lock_ratio": round(lock_ratio, 2),
            "message": f"海外仓锁定比例 {lock_ratio * 100:.0f}%（健康线 < 20%）"
        })
        recommendations.append({
            "action": "unlock_investigate",
            "quantity": round(transfer_lock),
            "urgency": severity,
            "reason": "高锁定比例影响可售库存"
        })

    # 滞销风险
    if sell_qty_days > warning_days:
        severity = "high" if sell_qty_days > 120 else "medium"
        risks.append({
            "type": "slow_moving",
            "severity": severity,
            "sell_qty_days": round(sell_qty_days, 1),
            "message": f"周转天数 {sell_qty_days:.0f} 天（健康线 < {warning_days} 天）"
        })
        recommendations.append({
            "action": "clearance_or_promote",
            "quantity": round(total_qty * 0.3),
            "urgency": severity,
            "reason": "库存周转过慢，建议促销或清仓"
        })

    return {
        "sku": sku,
        "health_rating": health_rating,
        "total_days_cover": round(total_days_cover, 1),
        "platform_days_cover": round(platform_days, 1),
        "transfer_days_cover": round(transfer_days, 1),
        "lock_ratio": round(lock_ratio, 2),
        "risks": risks,
        "recommendations": recommendations,
        "status": "success"
    }


def main():
    """主执行函数，从标准输入读取 JSON 并输出库存健康度结果。"""
    try:
        input_data = json.loads(sys.stdin.read())

        if "sku" not in input_data:
            raise ValueError("Missing required field: sku")
        if "inventory" not in input_data:
            raise ValueError("Missing required field: inventory")
        if "sales" not in input_data:
            raise ValueError("Missing required field: sales")

        sku = input_data["sku"]
        inventory = input_data["inventory"]
        sales = input_data["sales"]
        thresholds = input_data.get("thresholds")

        result = calculate_inventory_health(sku, inventory, sales, thresholds)
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
