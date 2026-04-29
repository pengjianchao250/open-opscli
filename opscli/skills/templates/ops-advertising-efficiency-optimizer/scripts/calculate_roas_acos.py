#!/usr/bin/env python3
"""
Script Name: calculate_roas_acos.py
Description: 快速 ROAS/ACOS 计算器，支持多种输入格式
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, Optional


def calculate_roas_acos(
    cost: float,
    sales: float,
    clicks: Optional[float] = None,
    impressions: Optional[float] = None,
    conversions: Optional[float] = None
) -> Dict[str, Any]:
    """
    计算广告核心指标。

    Args:
        cost: 广告花费
        sales: 广告销售额
        clicks: 点击量（可选）
        impressions: 曝光量（可选）
        conversions: 转化订单数（可选）

    Returns:
        包含 ACOS、ROAS 及可选指标的字典
    """
    if cost < 0 or sales < 0:
        raise ValueError("cost 和 sales 必须为非负数")

    acos = cost / sales if sales > 0 else None
    roas = sales / cost if cost > 0 else None

    result = {
        "acos": round(acos, 4) if acos is not None else None,
        "acos_percent": f"{acos * 100:.2f}%" if acos is not None else "N/A",
        "roas": round(roas, 2) if roas is not None else None,
        "status": "success"
    }

    if clicks is not None and clicks > 0:
        result["cpc"] = round(cost / clicks, 2)
        if conversions is not None:
            result["cvr"] = round(conversions / clicks, 4)
            result["cvr_percent"] = f"{conversions / clicks * 100:.2f}%"

    if impressions is not None and impressions > 0 and clicks is not None:
        result["ctr"] = round(clicks / impressions, 4)
        result["ctr_percent"] = f"{clicks / impressions * 100:.2f}%"

    # 健康评级
    if acos is not None:
        if acos < 0.20:
            result["acos_rating"] = "healthy"
        elif acos < 0.30:
            result["acos_rating"] = "warning"
        else:
            result["acos_rating"] = "critical"

    if roas is not None:
        if roas > 5.0:
            result["roas_rating"] = "healthy"
        elif roas > 3.3:
            result["roas_rating"] = "warning"
        else:
            result["roas_rating"] = "critical"

    return result


def main():
    """主执行函数，从标准输入读取 JSON 并输出计算结果。"""
    try:
        input_data = json.loads(sys.stdin.read())

        # 支持两种输入格式：直接传字段 或 传 campaign 对象
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
            conversions=float(conversions) if conversions is not None else None
        )

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
