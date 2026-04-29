"""ops-inventory-health-monitor Skill 的核心工具函数。

提供库存健康评级和补货计划计算能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def rate_inventory(
    sell_qty_days: float,
    platform_qty: float,
    avg_daily_sales: float
) -> str:
    """库存健康度评级（A/B/C/D/F）。"""
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
    """计算库存健康度并识别风险。"""
    platform_qty = float(inventory.get("platform_qty", 0))
    transfer_available = float(inventory.get("transfer_available_qty", 0))
    transfer_lock = float(inventory.get("transfer_lock_qty", 0))
    intransit = float(inventory.get("intransit_qty", 0))
    total_qty = float(inventory.get("total_qty", 0))

    avg_daily = float(sales.get("average_daily_sales_volume", 0))
    thresholds = thresholds or {}
    stockout_risk_days = thresholds.get("stockout_risk_days", 14)
    warning_days = thresholds.get("warning_days", 90)

    platform_days = platform_qty / avg_daily if avg_daily > 0 else 999
    transfer_days = transfer_available / avg_daily if avg_daily > 0 else 999
    total_available = platform_qty + transfer_available + intransit
    total_days_cover = total_available / avg_daily if avg_daily > 0 else 999

    sell_qty_days = float(inventory.get("sell_qty_days", total_days_cover))

    health_rating = rate_inventory(sell_qty_days, platform_qty, avg_daily)

    risks = []
    recommendations = []

    if platform_days < stockout_risk_days:
        severity = "high" if platform_days < 7 else "medium"
        risks.append({
            "type": "stockout",
            "severity": severity,
            "days_until_stockout": round(platform_days, 1),
            "message": f"平台仓仅剩 {platform_days:.1f} 天库存（健康线 > {stockout_risk_days} 天）"
        })
        target_inventory = stockout_risk_days * 2 * avg_daily
        replenish_qty = max(0, target_inventory - total_available)
        recommendations.append({
            "action": "replenish",
            "quantity": round(replenish_qty),
            "urgency": "high" if severity == "high" else "medium",
            "reason": f"平台仓覆盖天数 {platform_days:.1f} 天低于安全线"
        })

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


def calculate_replenishment(
    sku_data: Dict[str, Any],
    target_days: int,
    lead_time_days: int,
    safety_factor: float = 1.5,
    buffer_days: int = 7,
    reference_date: Optional[str] = None
) -> Dict[str, Any]:
    """计算补货量和建议发货时间。"""
    daily_sales = float(sku_data.get("average_daily_sales_volume", 0))
    platform_qty = float(sku_data.get("platform_qty", 0))
    transfer_available = float(sku_data.get("transfer_available_qty", 0))
    intransit = float(sku_data.get("intransit_qty", 0))

    if daily_sales <= 0:
        return {
            "status": "warning",
            "message": "日均销量为 0，无法计算补货计划",
            "replenishment_qty": 0,
            "recommended_qty": 0,
            "ship_by_date": None,
            "urgency": "low"
        }

    current_available = platform_qty + transfer_available + intransit
    target_inventory = target_days * daily_sales
    replenishment_qty = max(0, target_inventory - current_available)
    safety_stock = lead_time_days * daily_sales * safety_factor
    recommended_qty = replenishment_qty + safety_stock
    platform_days = platform_qty / daily_sales

    ref_date_str = sku_data.get("reference_date") or reference_date
    if ref_date_str:
        try:
            ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            ref_date = datetime.now()
    else:
        ref_date = datetime.now()

    days_until_ship = max(0, platform_days - lead_time_days - buffer_days)
    ship_by_date = (ref_date + timedelta(days=int(days_until_ship))).strftime("%Y-%m-%d")

    if platform_days < 14: urgency = "high"
    elif platform_days < 30: urgency = "medium"
    else: urgency = "low"

    return {
        "status": "success",
        "replenishment_qty": round(replenishment_qty),
        "safety_stock": round(safety_stock),
        "recommended_qty": round(recommended_qty),
        "ship_by_date": ship_by_date,
        "urgency": urgency,
        "platform_days": round(platform_days, 1),
        "current_available": round(current_available),
        "target_inventory": round(target_inventory)
    }
