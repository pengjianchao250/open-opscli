"""ops-product-attribute-analyzer Skill 的核心工具函数。

提供加权份额计算、属性组合分析、市场画像生成等基础能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


DATASET_FIELDS: Dict[str, List[str]] = {
    "ds_d35ac6f3910c": [
        "date_id", "dept_name", "team_name", "asin", "ed_sku", "product_name",
        "category", "platform_name", "country_name", "original_price", "order_qty",
        "gross_profit", "gross_profit_percent", "refund_percent", "refund_qty",
        "channel_uuid", "listing_uuid"
    ],
    "ds_pdTYjvLRCadv": [
        "date_id", "asin", "product_name", "price", "star", "reviews_qty",
        "subclass_rank", "category", "asin_ps_uuid"
    ]
}


def calculate_weighted_share(
    dimension: str,
    data: List[Dict[str, Any]],
    weight_field: str = "order_qty",
    count_field: str = "asin"
) -> Dict[str, Any]:
    """计算指定维度的销售加权市场份额。"""
    if not data:
        return {
            "dimension": dimension, "total_weight": 0, "total_count": 0,
            "shares": [], "status": "warning", "message": "输入数据为空"
        }

    groups: Dict[str, Dict[str, Any]] = {}
    for row in data:
        key = str(row.get(dimension, "Unknown"))
        weight = float(row.get(weight_field, 0) or 0)
        count_val = int(row.get(count_field, 1) or 1)
        if key not in groups:
            groups[key] = {"weight": 0.0, "count": 0}
        groups[key]["weight"] += weight
        groups[key]["count"] += count_val

    total_weight = sum(g["weight"] for g in groups.values())
    total_count = sum(g["count"] for g in groups.values())

    if total_weight == 0:
        return {
            "dimension": dimension, "total_weight": 0, "total_count": total_count,
            "shares": [], "status": "warning", "message": "总销量为 0，无法计算份额"
        }

    shares = []
    for key, agg in groups.items():
        share = agg["weight"] / total_weight if total_weight > 0 else 0.0
        avg_per_unit = agg["weight"] / agg["count"] if agg["count"] > 0 else 0.0
        shares.append({
            "value": key, "weight": round(agg["weight"], 2),
            "count": agg["count"], "share": round(share, 4),
            "avg_per_unit": round(avg_per_unit, 2)
        })

    shares.sort(key=lambda x: x["share"], reverse=True)

    return {
        "dimension": dimension, "total_weight": round(total_weight, 2),
        "total_count": total_count, "shares": shares, "status": "success"
    }


def find_opportunities(
    combo_data: List[Dict[str, Any]],
    threshold_ratio: float = 1.5,
    max_market_share: float = 0.20
) -> Dict[str, Any]:
    """识别属性组合中的供给不足机会点。"""
    if not combo_data:
        return {
            "opportunities": [], "avg_sales_per_asin": 0.0,
            "total_combos": 0, "status": "warning", "message": "输入数据为空"
        }

    total_sales = sum(d.get("total_sales", 0) for d in combo_data)
    total_asins = sum(d.get("asin_count", 0) for d in combo_data)
    avg_sales_per_asin = total_sales / total_asins if total_asins > 0 else 0.0

    if avg_sales_per_asin == 0:
        return {
            "opportunities": [], "avg_sales_per_asin": 0.0,
            "total_combos": len(combo_data), "status": "warning",
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

    opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)

    return {
        "opportunities": opportunities,
        "avg_sales_per_asin": round(avg_sales_per_asin, 2),
        "total_combos": len(combo_data),
        "threshold_ratio": threshold_ratio,
        "max_market_share": max_market_share,
        "status": "success"
    }


def generate_market_portrait(
    category: str,
    shares: List[Dict[str, Any]],
    opportunities: List[Dict[str, Any]],
    analysis_period: str = ""
) -> Dict[str, Any]:
    """根据份额数据和机会点生成 Market Portrait 结构化报告。"""
    if not shares:
        return {
            "category": category,
            "markdown": f"# Market Portrait: {category}\n\n无数据。",
            "status": "warning", "message": "输入 shares 为空"
        }

    total_asins = sum(s.get("count", 0) for s in shares)
    total_sales = sum(s.get("weight", 0) for s in shares)

    sorted_by_share = sorted(shares, key=lambda x: x.get("share", 0), reverse=True)
    top_share = sorted_by_share[0] if sorted_by_share else {}

    over_supplied = [s for s in shares if s.get("share", 0) > 0.30]
    over_supplied.sort(key=lambda x: x.get("avg_per_unit", float("inf")))

    lines = [
        f"# Market Portrait: {category}",
        "",
        "## Executive Summary",
        f"- Total ASINs: {total_asins}",
        f"- Total Sales: {total_sales:,.0f}",
        f"- Analysis Period: {analysis_period or 'N/A'}",
        "",
        "## Market Favorite Archetype",
        f"🏆 {top_share.get('value', 'N/A')}",
        f"- Market Share: {top_share.get('share', 0) * 100:.1f}%",
        f"- ASIN Count: {top_share.get('count', 0)} ({top_share.get('count', 0) / total_asins * 100:.1f}% of total)" if total_asins > 0 else "- ASIN Count: 0",
        f"- Sales per ASIN: {top_share.get('avg_per_unit', 0):,.0f}",
        "- Status: Market leader",
        "",
        "## Top 3 Opportunities",
    ]

    for i, opp in enumerate(opportunities[:3], 1):
        lines.append(
            f"{i}. {opp.get('combo', 'N/A')} — Opportunity Score: {opp.get('opportunity_score', 0):.2f} "
            f"(Sales/ASIN: {opp.get('sales_per_asin', 0):,.0f}, Share: {opp.get('market_share', 0) * 100:.1f}%)"
        )

    if not opportunities:
        lines.append("_No significant under-supplied opportunities detected._")

    lines.extend(["", "## Over-Supplied Segments"])
    for i, seg in enumerate(over_supplied[:3], 1):
        lines.append(
            f"{i}. {seg.get('value', 'N/A')} — Low efficiency, consider reduction "
            f"(Share: {seg.get('share', 0) * 100:.1f}%, Sales/ASIN: {seg.get('avg_per_unit', 0):,.0f})"
        )

    if not over_supplied:
        lines.append("_No over-supplied segments detected._")

    lines.extend(["", "## Recommendations"])
    if opportunities:
        lines.append(f"- 加大对 Top 1 机会组合「{opportunities[0].get('combo', 'N/A')}」的投入，预计 ROI 最高")
    if over_supplied:
        lines.append(f"- 缩减低效组合「{over_supplied[0].get('value', 'N/A')}」的 ASIN 数量，释放资源")
    lines.append("- 持续监控 sales_per_asin 指标，每 30 天更新一次 Market Portrait")

    markdown = "\n".join(lines)

    return {
        "category": category, "analysis_period": analysis_period,
        "total_asins": total_asins, "total_sales": round(total_sales, 2),
        "top_archetype": top_share, "opportunities": opportunities[:3],
        "over_supplied": over_supplied[:3], "markdown": markdown, "status": "success"
    }
