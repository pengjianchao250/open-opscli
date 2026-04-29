#!/usr/bin/env python3
"""
Script Name: calculate_health_score.py
Description: Calculate ASIN health score from operational metrics
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, Optional, List

# Default weights for 6 core metrics
DEFAULT_WEIGHTS = {
    "gross_profit_percent": 0.30,
    "convert_percent": 0.20,
    "ads_acos": 0.20,
    "refund_percent": 0.15,
    "inventory_days": 0.10,
    "star": 0.05,
}

# Default benchmarks (healthy / warning thresholds)
DEFAULT_BENCHMARKS = {
    "gross_profit_percent": {"healthy": 0.20, "warning": 0.10, "direction": "higher_is_better"},
    "convert_percent": {"healthy": 0.10, "warning": 0.05, "direction": "higher_is_better"},
    "ads_acos": {"healthy": 0.20, "warning": 0.30, "direction": "lower_is_better"},
    "refund_percent": {"healthy": 0.05, "warning": 0.10, "direction": "lower_is_better"},
    "inventory_days": {"healthy": 45, "warning": 90, "direction": "lower_is_better"},
    "star": {"healthy": 4.3, "warning": 4.0, "direction": "higher_is_better"},
}

# Action recommendations by metric
ACTION_RECOMMENDATIONS = {
    "gross_profit_percent": {
        "critical": "立即排查成本结构，重点优化采购成本和广告费",
        "warning": "评估采购成本谈判空间，优化广告ACOS",
        "good": "毛利率健康，保持当前策略",
    },
    "convert_percent": {
        "critical": "Listing优化：主图/A+/价格/Review，排查流量质量问题",
        "warning": "优化产品页面，补充QA，考虑降价或促销",
        "good": "转化率健康，可尝试提价测试",
    },
    "ads_acos": {
        "critical": "紧急优化广告：暂停高ACOS词，加大精准匹配投入",
        "warning": "优化广告结构，降低大词竞价，增加长尾词",
        "good": "广告效率良好，可适当增加预算扩大销售",
    },
    "refund_percent": {
        "critical": "紧急排查产品质量：分析退款原因，联系供应商改进",
        "warning": "关注退款趋势，优化产品描述减少预期差",
        "good": "退款率健康，保持品质控制",
    },
    "inventory_days": {
        "critical": "滞销风险高：考虑降价清仓或站外Deals",
        "warning": "库存周转偏慢，评估促销或调整补货节奏",
        "good": "库存周转健康",
    },
    "star": {
        "critical": "星级危机：分析差评原因，制定改进计划",
        "warning": "关注Review趋势，主动跟进差评客户",
        "good": "星级健康，继续维护产品质量",
    },
}


def normalize(value: float, benchmark: Dict[str, Any]) -> float:
    """
    Normalize a metric value to 0-100 score.

    For higher_is_better: 100 at healthy, 0 at warning
    For lower_is_better: 100 at healthy, 0 at warning
    Linear interpolation between healthy and warning.
    """
    healthy = benchmark["healthy"]
    warning = benchmark["warning"]
    direction = benchmark["direction"]

    if value is None:
        return 50.0  # Default mid score for missing data

    if direction == "higher_is_better":
        if value >= healthy:
            return 100.0
        if value <= warning:
            return 0.0
        return (value - warning) / (healthy - warning) * 100.0
    else:  # lower_is_better
        if value <= healthy:
            return 100.0
        if value >= warning:
            return 0.0
        return (warning - value) / (warning - healthy) * 100.0


def get_status(score: float) -> str:
    """Get status label from normalized score."""
    if score >= 80:
        return "good"
    elif score >= 50:
        return "warning"
    else:
        return "critical"


def get_status_emoji(status: str) -> str:
    """Get emoji for status."""
    return {"good": "✅", "warning": "⚠️", "critical": "🔴"}.get(status, "❓")


def calculate_health_score(
    metrics: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
    benchmarks: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Calculate composite health score from ASIN metrics.

    Args:
        metrics: Dict of metric values (e.g., {"gross_profit_percent": 0.185, ...})
        weights: Optional custom weights (defaults to DEFAULT_WEIGHTS)
        benchmarks: Optional custom benchmarks (defaults to DEFAULT_BENCHMARKS)

    Returns:
        Dict containing health score, level, metric details, issues, and actions.
    """
    weights = weights or DEFAULT_WEIGHTS
    benchmarks = benchmarks or DEFAULT_BENCHMARKS

    # Handle missing star rating gracefully
    effective_weights = dict(weights)
    if metrics.get("star") is None:
        # Redistribute star weight proportionally to other metrics
        star_weight = effective_weights.pop("star", 0.05)
        remaining_total = sum(effective_weights.values())
        for key in effective_weights:
            effective_weights[key] += star_weight * (effective_weights[key] / remaining_total)

    total_score = 0.0
    metrics_detail = []
    issues = []
    prioritized_actions = []

    for metric, weight in effective_weights.items():
        value = metrics.get(metric)
        benchmark = benchmarks.get(metric, {})

        normalized = normalize(value, benchmark)
        status = get_status(normalized)

        total_score += normalized * weight

        detail = {
            "metric": metric,
            "value": value,
            "normalized_score": round(normalized, 1),
            "status": status,
            "weight": round(weight, 3),
            "weighted_score": round(normalized * weight, 1),
            "benchmark": benchmark,
        }
        metrics_detail.append(detail)

        # Collect issues for warning/critical metrics
        if status in ("warning", "critical"):
            recommendation = ACTION_RECOMMENDATIONS.get(metric, {}).get(status, "")
            issues.append({
                "metric": metric,
                "severity": status,
                "value": value,
                "description": f"{metric} = {value} ({status})",
                "recommendation": recommendation,
            })

    health_score = round(total_score)

    # Determine health level
    if health_score >= 80:
        health_level = "Excellent"
    elif health_score >= 60:
        health_level = "Good"
    elif health_score >= 40:
        health_level = "Fair"
    else:
        health_level = "Poor"

    # Prioritize actions: critical first, then warning, sort by weighted impact
    issues.sort(key=lambda x: (0 if x["severity"] == "critical" else 1, x.get("value", 0)))

    for i, issue in enumerate(issues):
        priority = "P0" if issue["severity"] == "critical" else "P1"
        prioritized_actions.append({
            "rank": i + 1,
            "priority": priority,
            "metric": issue["metric"],
            "action": issue["recommendation"],
            "severity": issue["severity"],
        })

    return {
        "health_score": health_score,
        "health_level": health_level,
        "metrics_detail": metrics_detail,
        "issues": issues,
        "prioritized_actions": prioritized_actions,
    }


def format_diagnosis(result: Dict[str, Any], asin: str, product_name: str, date_range: str) -> str:
    """Format diagnosis result as human-readable text."""
    lines = [
        f"【ASIN】{asin}（{product_name}）",
        f"【健康度评分】{result['health_score']}/100（{result['health_level']}）",
        "【分项指标】",
    ]

    for detail in result["metrics_detail"]:
        metric = detail["metric"]
        value = detail["value"]
        status = detail["status"]
        emoji = get_status_emoji(status)

        # Format value based on metric type
        if metric in ("gross_profit_percent", "convert_percent", "ads_acos", "refund_percent"):
            value_str = f"{value * 100:.1f}%"
        elif metric == "star":
            value_str = f"{value:.1f}⭐"
        else:
            value_str = f"{value:.0f}天"

        lines.append(f"  ├─ {metric}：{value_str} {emoji}（{status}）")

    if result["issues"]:
        lines.append("【主要问题】")
        for issue in result["issues"]:
            lines.append(f"  - {issue['metric']}: {issue['description']}")

    if result["prioritized_actions"]:
        lines.append("【建议行动】")
        for action in result["prioritized_actions"]:
            lines.append(f"  {action['rank']}. [{action['priority']}] {action['action']}")

    lines.append(f"【数据时间】{date_range}")

    return "\n".join(lines)


def main():
    """Main execution function."""
    try:
        input_data = json.loads(sys.stdin.read())

        # Validate required fields
        if "metrics" not in input_data:
            raise ValueError("Missing required field: metrics")

        asin = input_data.get("asin", "Unknown")
        product_name = input_data.get("product_name", "")
        date_range = input_data.get("date_range", "")
        metrics = input_data["metrics"]
        weights = input_data.get("weights")
        benchmarks = input_data.get("benchmarks")

        # Calculate health score
        result = calculate_health_score(metrics, weights, benchmarks)

        # Add metadata
        result["asin"] = asin
        result["product_name"] = product_name
        result["date_range"] = date_range

        # Generate formatted text output
        result["formatted_diagnosis"] = format_diagnosis(result, asin, product_name, date_range)

        # Output result as JSON
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except ValueError as e:
        error_result = {"status": "error", "error_type": "ValueError", "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False))
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    except json.JSONDecodeError as e:
        error_result = {"status": "error", "error_type": "JSONDecodeError", "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False))
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        error_result = {"status": "error", "error_type": type(e).__name__, "message": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False))
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
