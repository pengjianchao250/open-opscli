#!/usr/bin/env python3
"""
Script Name: generate_replenishment_plan.py
Description: 生成补货计划，计算补货量和建议发货时间
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


def calculate_replenishment(
    sku_data: Dict[str, Any],
    target_days: int,
    lead_time_days: int,
    safety_factor: float = 1.5,
    buffer_days: int = 7,
    reference_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    计算补货量和建议发货时间。

    算法步骤：
    1. 当前可用库存 = 平台仓 + 海外仓可售 + 在途
    2. 目标库存量 = 目标天数 × 日均销量
    3. 基础补货量 = max(0, 目标库存量 - 当前可用库存)
    4. 安全库存 = lead_time × 日均销量 × 安全系数
    5. 最终建议补货量 = 基础补货量 + 安全库存
    6. 建议发货日期 = 参考日期 + (平台库存天数 - lead_time - buffer)

    Args:
        sku_data: SKU 数据，包含 platform_qty、transfer_available_qty、
                  intransit_qty、average_daily_sales_volume
        target_days: 目标库存覆盖天数
        lead_time_days: 供应链交期（海运/空运/生产）
        safety_factor: 安全系数，默认 1.5
        buffer_days: 缓冲天数，默认 7 天
        reference_date: 参考日期（格式 YYYY-MM-DD），默认为当天

    Returns:
        包含补货量、建议发货日期、紧急程度的字典
    """
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

    # 当前可用库存
    current_available = platform_qty + transfer_available + intransit

    # 目标库存量
    target_inventory = target_days * daily_sales

    # 基础补货量
    replenishment_qty = max(0, target_inventory - current_available)

    # 安全库存
    safety_stock = lead_time_days * daily_sales * safety_factor

    # 最终建议补货量
    recommended_qty = replenishment_qty + safety_stock

    # 平台库存覆盖天数
    platform_days = platform_qty / daily_sales

    # 建议发货日期（支持外部传入参考日期，便于测试和回测）
    ref_date_str = sku_data.get("reference_date") or reference_date
    if ref_date_str:
        try:
            ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            ref_date = datetime.now()
    else:
        ref_date = datetime.now()

    # 建议发货日期
    days_until_ship = max(0, platform_days - lead_time_days - buffer_days)
    ship_by_date = (ref_date + timedelta(days=int(days_until_ship))).strftime("%Y-%m-%d")

    # 紧急程度判定
    if platform_days < 14:
        urgency = "high"
    elif platform_days < 30:
        urgency = "medium"
    else:
        urgency = "low"

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


def main():
    """主执行函数，从标准输入读取 JSON 并输出补货计划。"""
    try:
        input_data = json.loads(sys.stdin.read())

        if "sku_data" not in input_data:
            raise ValueError("Missing required field: sku_data")
        if "target_days" not in input_data:
            raise ValueError("Missing required field: target_days")
        if "lead_time_days" not in input_data:
            raise ValueError("Missing required field: lead_time_days")

        sku_data = input_data["sku_data"]
        target_days = int(input_data["target_days"])
        lead_time_days = int(input_data["lead_time_days"])
        safety_factor = float(input_data.get("safety_factor", 1.5))
        buffer_days = int(input_data.get("buffer_days", 7))
        reference_date = input_data.get("reference_date")

        result = calculate_replenishment(sku_data, target_days, lead_time_days, safety_factor, buffer_days, reference_date)
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
