#!/usr/bin/env python3
"""
Script Name: generate_market_portrait.py
Description: 生成 Market Portrait 摘要报告（Markdown 格式）
Author: opscli Team
Date: 2026-04-28
"""

import sys
import json
from typing import Dict, Any, List


def generate_market_portrait(
    category: str,
    shares: List[Dict[str, Any]],
    opportunities: List[Dict[str, Any]],
    analysis_period: str = ""
) -> Dict[str, Any]:
    """
    根据份额数据和机会点生成 Market Portrait 结构化报告。

    输出包含：
    1. Executive Summary（样本规模、总销量、周期）
    2. Market Favorite Archetype（市场最受欢迎原型组合）
    3. Top 3 Opportunities（供给不足的高价值组合）
    4. Bottom 3 Over-Supplied Segments（过度供给、效率低的组合）
    5. Recommendations（可执行的行动建议）

    Args:
        category: 品类名称
        shares: 各属性组合的份额数据
        opportunities: 机会点列表（来自 analyze_attribute_combo.py 的输出）
        analysis_period: 分析周期字符串，如 "2024-11-01 ~ 2025-01-31"

    Returns:
        包含 markdown 报告和结构化数据的字典
    """
    if not shares:
        return {
            "category": category,
            "markdown": f"# Market Portrait: {category}\n\n无数据。",
            "status": "warning",
            "message": "输入 shares 为空"
        }

    # 计算总体统计
    total_asins = sum(s.get("count", 0) for s in shares)
    total_sales = sum(s.get("weight", 0) for s in shares)

    # Market Favorite Archetype：share 最高且 sales_per_unit 最高的组合
    sorted_by_share = sorted(shares, key=lambda x: x.get("share", 0), reverse=True)
    top_share = sorted_by_share[0] if sorted_by_share else {}

    # 过度供给组合：share 高但 sales_per_unit 低的组合
    over_supplied = [s for s in shares if s.get("share", 0) > 0.30]
    over_supplied.sort(key=lambda x: x.get("avg_per_unit", float("inf")))

    # 构建 Markdown 报告
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
        "category": category,
        "analysis_period": analysis_period,
        "total_asins": total_asins,
        "total_sales": round(total_sales, 2),
        "top_archetype": top_share,
        "opportunities": opportunities[:3],
        "over_supplied": over_supplied[:3],
        "markdown": markdown,
        "status": "success"
    }


def main():
    """主执行函数，从标准输入读取 JSON 并输出 Market Portrait。"""
    try:
        input_data = json.loads(sys.stdin.read())

        if "category" not in input_data:
            raise ValueError("Missing required field: category")
        if "shares" not in input_data:
            raise ValueError("Missing required field: shares")

        category = input_data["category"]
        shares = input_data["shares"]
        opportunities = input_data.get("opportunities", [])
        analysis_period = input_data.get("analysis_period", "")

        result = generate_market_portrait(category, shares, opportunities, analysis_period)

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
