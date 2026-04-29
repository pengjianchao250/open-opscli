#!/usr/bin/env python3
"""
Script Name: analyze_ads_efficiency.py
Description: 广告效率分析主脚本，接收广告数据并输出诊断报告
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, List, Optional


def calculate_metrics(cost: float, sales: float, clicks: float, impressions: float, conversions: float) -> Dict[str, float]:
    """
    计算广告核心指标。

    Args:
        cost: 广告花费
        sales: 广告销售额
        clicks: 点击量
        impressions: 曝光量
        conversions: 转化订单数

    Returns:
        包含 ACOS、ROAS、CPC、CTR、CVR 的字典
    """
    acos = cost / sales if sales > 0 else 1.0
    roas = sales / cost if cost > 0 else 0.0
    cpc = cost / clicks if clicks > 0 else 0.0
    ctr = clicks / impressions if impressions > 0 else 0.0
    cvr = conversions / clicks if clicks > 0 else 0.0
    return {
        "acos": round(acos, 4),
        "roas": round(roas, 2),
        "cpc": round(cpc, 2),
        "ctr": round(ctr, 4),
        "cvr": round(cvr, 4)
    }


def diagnose_campaign(campaign: Dict[str, Any], benchmarks: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    诊断单个广告活动的问题。

    判定规则：
    - ACOS > target * 1.5 → critical (high_acos)
    - ACOS > target → warning (high_acos)
    - ROAS < target * 0.5 → critical (low_roas)
    - ROAS < target → warning (low_roas)
    - CPC > target → warning (high_cpc)
    - CTR < target → warning (low_ctr)

    Args:
        campaign: 单条活动数据，包含 cost、sales、clicks、impressions、conversions
        benchmarks: 阈值配置，如 {"acos_target": 0.20, "roas_target": 5.0, ...}

    Returns:
        问题列表，每项包含 severity、type、value、recommendation
    """
    issues = []
    cost = float(campaign.get("cost", 0))
    sales = float(campaign.get("sales", 0))
    clicks = float(campaign.get("clicks", 0))
    impressions = float(campaign.get("impressions", 0))
    conversions = float(campaign.get("conversions", 0))

    metrics = calculate_metrics(cost, sales, clicks, impressions, conversions)

    acos_target = benchmarks.get("acos_target", 0.20)
    roas_target = benchmarks.get("roas_target", 5.0)
    cpc_target = benchmarks.get("cpc_target", 1.5)
    ctr_target = benchmarks.get("ctr_target", 0.003)

    # ACOS 诊断
    if metrics["acos"] > acos_target * 1.5:
        issues.append({
            "severity": "critical",
            "type": "high_acos",
            "value": metrics["acos"],
            "recommendation": "紧急优化：暂停高ACOS词，降低大词竞价15-20%"
        })
    elif metrics["acos"] > acos_target:
        issues.append({
            "severity": "warning",
            "type": "high_acos",
            "value": metrics["acos"],
            "recommendation": "优化广告结构，增加精准匹配和长尾词占比"
        })

    # ROAS 诊断
    if metrics["roas"] < roas_target * 0.5:
        issues.append({
            "severity": "critical",
            "type": "low_roas",
            "value": metrics["roas"],
            "recommendation": "ROAS 严重偏低，建议暂停或大幅削减预算"
        })
    elif metrics["roas"] < roas_target:
        issues.append({
            "severity": "warning",
            "type": "low_roas",
            "value": metrics["roas"],
            "recommendation": "优化受众/关键词定位，提升转化效率"
        })

    # CPC 诊断
    if metrics["cpc"] > cpc_target:
        issues.append({
            "severity": "warning",
            "type": "high_cpc",
            "value": metrics["cpc"],
            "recommendation": "CPC 偏高，尝试降低竞价或优化质量得分"
        })

    # CTR 诊断
    if metrics["ctr"] < ctr_target:
        issues.append({
            "severity": "warning",
            "type": "low_ctr",
            "value": metrics["ctr"],
            "recommendation": "CTR 偏低，优化主图/标题/广告文案"
        })

    return issues


def analyze_ad_efficiency(
    campaigns: List[Dict[str, Any]],
    benchmarks: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    主分析函数：批量诊断广告活动效率。

    Args:
        campaigns: 广告活动列表
        benchmarks: 可选自定义阈值

    Returns:
        诊断结果，包含各活动问题、汇总统计、优化建议排序
    """
    if not campaigns:
        return {
            "status": "warning",
            "message": "输入活动列表为空",
            "diagnoses": []
        }

    default_benchmarks = {
        "acos_target": 0.20,
        "roas_target": 5.0,
        "cpc_target": 1.5,
        "ctr_target": 0.003
    }
    benchmarks = benchmarks or default_benchmarks

    diagnoses = []
    total_cost = 0.0
    total_sales = 0.0

    for campaign in campaigns:
        cost = float(campaign.get("cost", 0))
        sales = float(campaign.get("sales", 0))
        total_cost += cost
        total_sales += sales

        issues = diagnose_campaign(campaign, benchmarks)
        metrics = calculate_metrics(
            cost, sales,
            float(campaign.get("clicks", 0)),
            float(campaign.get("impressions", 0)),
            float(campaign.get("conversions", 0))
        )

        diagnoses.append({
            "campaign_name": campaign.get("campaign_name", "Unknown"),
            "ad_group_name": campaign.get("ad_group_name", ""),
            "ad_type": campaign.get("ad_type", ""),
            "metrics": metrics,
            "issues": issues,
            "issue_count": len(issues)
        })

    # 汇总统计
    overall_acos = total_cost / total_sales if total_sales > 0 else 1.0
    overall_roas = total_sales / total_cost if total_cost > 0 else 0.0

    # 按问题严重程度排序：critical 优先
    diagnoses.sort(key=lambda x: (
        0 if any(i["severity"] == "critical" for i in x["issues"]) else 1,
        -x["issue_count"]
    ))

    # 生成优化建议
    recommendations = []
    for d in diagnoses:
        for issue in d["issues"]:
            priority = "P0" if issue["severity"] == "critical" else "P1"
            recommendations.append({
                "priority": priority,
                "campaign": d["campaign_name"],
                "type": issue["type"],
                "severity": issue["severity"],
                "action": issue["recommendation"]
            })

    return {
        "status": "success",
        "overall": {
            "total_cost": round(total_cost, 2),
            "total_sales": round(total_sales, 2),
            "acos": round(overall_acos, 4),
            "roas": round(overall_roas, 2)
        },
        "diagnoses": diagnoses,
        "recommendations": recommendations,
        "critical_count": sum(1 for d in diagnoses if any(i["severity"] == "critical" for i in d["issues"])),
        "warning_count": sum(1 for d in diagnoses if any(i["severity"] == "warning" for i in d["issues"]))
    }


def main():
    """主执行函数，从标准输入读取 JSON 并输出诊断报告。"""
    try:
        input_data = json.loads(sys.stdin.read())

        if "campaigns" not in input_data:
            raise ValueError("Missing required field: campaigns")

        campaigns = input_data["campaigns"]
        benchmarks = input_data.get("benchmarks")

        result = analyze_ad_efficiency(campaigns, benchmarks)
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
