"""ops-advertising-efficiency-optimizer Skill 的核心工具函数。

提供广告效率计算、ROAS/ACOS 计算、预算分配等基础能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


DEFAULT_BENCHMARKS: Dict[str, float] = {
    "acos_target": 0.20,
    "roas_target": 5.0,
    "cpc_target": 1.5,
    "ctr_target": 0.003,
    "cvr_target": 0.10,
}

SEVERITY_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "acos": {"healthy": 0.20, "warning": 0.30, "direction": "lower_is_better"},
    "roas": {"healthy": 5.0, "warning": 3.3, "direction": "higher_is_better"},
    "cpc": {"healthy": 1.5, "warning": 2.5, "direction": "lower_is_better"},
    "ctr": {"healthy": 0.003, "warning": 0.002, "direction": "higher_is_better"},
    "cvr": {"healthy": 0.10, "warning": 0.05, "direction": "higher_is_better"},
}


def calculate_metrics(
    cost: float, sales: float, clicks: float, impressions: float, conversions: float
) -> Dict[str, Any]:
    """计算广告核心指标。"""
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
        "cvr": round(cvr, 4),
    }


def calculate_roas_acos(
    cost: float,
    sales: float,
    clicks: Optional[float] = None,
    impressions: Optional[float] = None,
    conversions: Optional[float] = None,
) -> Dict[str, Any]:
    """快速 ROAS/ACOS 计算，支持可选的 CPC/CTR/CVR。"""
    if cost < 0 or sales < 0:
        raise ValueError("cost 和 sales 必须为非负数")

    acos = cost / sales if sales > 0 else None
    roas = sales / cost if cost > 0 else None

    result: Dict[str, Any] = {
        "acos": round(acos, 4) if acos is not None else None,
        "acos_percent": f"{acos * 100:.2f}%" if acos is not None else "N/A",
        "roas": round(roas, 2) if roas is not None else None,
        "status": "success",
    }

    if clicks is not None and clicks > 0:
        result["cpc"] = round(cost / clicks, 2)
        if conversions is not None:
            result["cvr"] = round(conversions / clicks, 4)
            result["cvr_percent"] = f"{conversions / clicks * 100:.2f}%"

    if impressions is not None and impressions > 0 and clicks is not None:
        result["ctr"] = round(clicks / impressions, 4)
        result["ctr_percent"] = f"{clicks / impressions * 100:.2f}%"

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


def diagnose_campaign(
    campaign: Dict[str, Any], benchmarks: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """诊断单个广告活动的问题。"""
    issues = []
    metrics = calculate_metrics(
        float(campaign.get("cost", 0)),
        float(campaign.get("sales", 0)),
        float(campaign.get("clicks", 0)),
        float(campaign.get("impressions", 0)),
        float(campaign.get("conversions", 0)),
    )

    acos_target = benchmarks.get("acos_target", 0.20)
    roas_target = benchmarks.get("roas_target", 5.0)
    cpc_target = benchmarks.get("cpc_target", 1.5)
    ctr_target = benchmarks.get("ctr_target", 0.003)

    if metrics["acos"] > acos_target * 1.5:
        issues.append({"severity": "critical", "type": "high_acos", "value": metrics["acos"], "recommendation": "紧急优化：暂停高ACOS词，降低大词竞价15-20%"})
    elif metrics["acos"] > acos_target:
        issues.append({"severity": "warning", "type": "high_acos", "value": metrics["acos"], "recommendation": "优化广告结构，增加精准匹配和长尾词占比"})

    if metrics["roas"] < roas_target * 0.5:
        issues.append({"severity": "critical", "type": "low_roas", "value": metrics["roas"], "recommendation": "ROAS 严重偏低，建议暂停或大幅削减预算"})
    elif metrics["roas"] < roas_target:
        issues.append({"severity": "warning", "type": "low_roas", "value": metrics["roas"], "recommendation": "优化受众/关键词定位，提升转化效率"})

    if metrics["cpc"] > cpc_target:
        issues.append({"severity": "warning", "type": "high_cpc", "value": metrics["cpc"], "recommendation": "CPC 偏高，尝试降低竞价或优化质量得分"})

    if metrics["ctr"] < ctr_target:
        issues.append({"severity": "warning", "type": "low_ctr", "value": metrics["ctr"], "recommendation": "CTR 偏低，优化主图/标题/广告文案"})

    return issues


def analyze_ad_efficiency(
    campaigns: List[Dict[str, Any]],
    benchmarks: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """批量诊断广告活动效率。"""
    if not campaigns:
        return {"status": "warning", "message": "输入活动列表为空", "diagnoses": []}

    benchmarks = benchmarks or DEFAULT_BENCHMARKS.copy()
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
            float(campaign.get("conversions", 0)),
        )

        diagnoses.append({
            "campaign_name": campaign.get("campaign_name", "Unknown"),
            "ad_group_name": campaign.get("ad_group_name", ""),
            "ad_type": campaign.get("ad_type", ""),
            "metrics": metrics,
            "issues": issues,
            "issue_count": len(issues),
        })

    overall_acos = total_cost / total_sales if total_sales > 0 else 1.0
    overall_roas = total_sales / total_cost if total_cost > 0 else 0.0

    diagnoses.sort(key=lambda x: (0 if any(i["severity"] == "critical" for i in x["issues"]) else 1, -x["issue_count"]))

    recommendations = []
    for d in diagnoses:
        for issue in d["issues"]:
            priority = "P0" if issue["severity"] == "critical" else "P1"
            recommendations.append({"priority": priority, "campaign": d["campaign_name"], "type": issue["type"], "severity": issue["severity"], "action": issue["recommendation"]})

    return {
        "status": "success",
        "overall": {"total_cost": round(total_cost, 2), "total_sales": round(total_sales, 2), "acos": round(overall_acos, 4), "roas": round(overall_roas, 2)},
        "diagnoses": diagnoses,
        "recommendations": recommendations,
        "critical_count": sum(1 for d in diagnoses if any(i["severity"] == "critical" for i in d["issues"])),
        "warning_count": sum(1 for d in diagnoses if any(i["severity"] == "warning" for i in d["issues"])),
    }


def optimize_budget(
    campaigns: List[Dict[str, Any]], total_budget: float
) -> Dict[str, Any]:
    """基于 ROAS 的广告预算重新分配优化器。"""
    if not campaigns:
        return {"status": "warning", "message": "输入活动列表为空", "allocations": []}

    if total_budget <= 0:
        raise ValueError("total_budget 必须大于 0")

    for camp in campaigns:
        cost = float(camp.get("current_spend", 0))
        sales = float(camp.get("sales", 0))
        camp["roas"] = sales / cost if cost > 0 else 0.0

    sorted_campaigns = sorted(campaigns, key=lambda x: x["roas"], reverse=True)

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

        raw_allocations.append({"name": camp.get("name", "Unknown"), "roas": round(roas, 2), "current_spend": round(current_spend, 2), "allocated": round(allocated, 2), "strategy": strategy})
        total_allocated += allocated

    if total_allocated > total_budget:
        scale = total_budget / total_allocated
        for alloc in raw_allocations:
            alloc["allocated"] = round(alloc["allocated"] * scale, 2)
            alloc["scaled"] = True
        total_allocated = total_budget
    else:
        remaining = total_budget - total_allocated
        if remaining > 0 and raw_allocations:
            raw_allocations[0]["allocated"] = round(raw_allocations[0]["allocated"] + remaining, 2)
            raw_allocations[0]["extra_budget"] = round(remaining, 2)
        total_allocated = total_budget

    expected_total_sales = sum(alloc["allocated"] * sorted_campaigns[i]["roas"] for i, alloc in enumerate(raw_allocations))
    expected_roas = expected_total_sales / total_allocated if total_allocated > 0 else 0.0

    return {
        "status": "success",
        "total_budget": round(total_budget, 2),
        "total_allocated": round(total_allocated, 2),
        "expected_total_sales": round(expected_total_sales, 2),
        "expected_roas": round(expected_roas, 2),
        "allocations": raw_allocations,
    }