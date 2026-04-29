"""ops-profit-structure-analyzer Skill 的核心工具函数。

提供成本结构偏离度计算、四行动框架分类、策略生成等基础能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


COST_ITEM_LABELS: Dict[str, str] = {
    "purchase_cost_percent": "采购成本",
    "first_leg_percent": "头程运费",
    "freight_percent": "运费",
    "storage_charges_percent": "仓租",
    "advertising_fee_percent": "广告费",
    "fee_percent": "平台手续费",
    "tax_fee_percent": "税金",
    "fixed_cost_percent": "固定成本",
    "refund_percent": "退款占比",
    "compensate_percent": "赔偿占比",
}

FIXED_COST_ITEMS = {"fee_percent", "tax_fee_percent", "fixed_cost_percent"}

ACTION_MAP: Dict[str, str] = {
    "refund_percent": "eliminate",
    "compensate_percent": "eliminate",
    "storage_charges_percent": "eliminate",
    "advertising_fee_percent": "reduce",
    "purchase_cost_percent": "reduce",
    "first_leg_percent": "reduce",
    "freight_percent": "reduce",
}

DEFAULT_BENCHMARK: Dict[str, float] = {
    "purchase_cost_percent": 0.25,
    "first_leg_percent": 0.065,
    "freight_percent": 0.05,
    "storage_charges_percent": 0.04,
    "advertising_fee_percent": 0.18,
    "fee_percent": 0.15,
    "tax_fee_percent": 0.08,
    "fixed_cost_percent": 0.03,
    "refund_percent": 0.035,
    "compensate_percent": 0.005,
}

SEVERITY_THRESHOLDS: Dict[str, float] = {
    "critical": 0.05,
    "warning": 0.02,
}


def calculate_deviation(current: float, benchmark: float) -> Dict[str, Any]:
    """计算偏离度并分级。"""
    deviation = current - benchmark
    abs_dev = abs(deviation)
    if abs_dev > SEVERITY_THRESHOLDS["critical"]:
        severity = "critical"
    elif abs_dev > SEVERITY_THRESHOLDS["warning"]:
        severity = "warning"
    else:
        severity = "normal"
    direction = "higher" if deviation > 0 else "lower" if deviation < 0 else "equal"
    return {
        "deviation": round(deviation, 4),
        "abs_deviation": round(abs_dev, 4),
        "severity": severity,
        "direction": direction,
    }


def classify_action(cost_item: str, deviation_info: Dict[str, Any]) -> str:
    """将成本项映射到四行动框架。"""
    if cost_item in FIXED_COST_ITEMS:
        return "fixed"
    if deviation_info["severity"] == "normal":
        return "normal"
    if deviation_info["direction"] == "lower":
        return "normal"
    return ACTION_MAP.get(cost_item, "review")


def generate_action_suggestions(
    cost_item: str, current: float, benchmark: float,
    deviation: float, severity: str, action_category: str,
    sales_amount: float
) -> Optional[str]:
    """根据成本项和偏离度生成具体的行动建议文本。"""
    if action_category in ("fixed", "normal"):
        return None
    label = COST_ITEM_LABELS.get(cost_item, cost_item)
    saving = round(deviation * sales_amount)
    if action_category == "eliminate":
        if cost_item == "refund_percent":
            return f"修复导致高退款率的质量问题，将退款占比从 {current*100:.1f}% 降至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
        elif cost_item == "compensate_percent":
            return f"排查赔偿根因，降低赔偿占比从 {current*100:.1f}% 至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
        elif cost_item == "storage_charges_percent":
            return f"清理库龄 > 90 天的滞销库存，降低仓租占比从 {current*100:.1f}% 至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
    elif action_category == "reduce":
        if cost_item == "purchase_cost_percent":
            return f"与供应商谈判或替换供应商，降低采购成本占比从 {current*100:.1f}% 至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
        elif cost_item == "first_leg_percent":
            return f"整合货量或更换货代，降低头程运费占比从 {current*100:.1f}% 至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
        elif cost_item == "freight_percent":
            return f"合并发货或谈判运费折扣，降低运费占比从 {current*100:.1f}% 至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
        elif cost_item == "advertising_fee_percent":
            return f"优化广告关键词和 ACOS，降低广告费占比从 {current*100:.1f}% 至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"
    return f"优化 {label}，从 {current*100:.1f}% 降至 {benchmark*100:.1f}% （预计月节省 ${saving:,}）"


def calculate_expected_impact(
    deviations: List[Dict[str, Any]], current_gross_profit: float,
    sales_amount: float
) -> Dict[str, Any]:
    """计算执行策略后的预期效果。"""
    total_savable = sum(
        d["deviation"] for d in deviations
        if d["action_category"] not in ("fixed", "normal") and d["deviation"] > 0
    )
    target_margin_low = current_gross_profit + total_savable * 0.5
    target_margin_high = current_gross_profit + total_savable * 0.8
    monthly_value = round(total_savable * sales_amount * 0.5)
    return {
        "current_margin": round(current_gross_profit, 4),
        "target_margin_low": round(max(0, target_margin_low), 4),
        "target_margin_high": round(max(0, target_margin_high), 4),
        "monthly_value": monthly_value,
    }


def analyze_cost_structure(data: Dict[str, Any]) -> Dict[str, Any]:
    """核心分析函数：拆解成本结构并生成四行动策略。"""
    target = data.get("target", {})
    period = data.get("period", {})
    cost_structure = data.get("cost_structure", {})
    benchmark = data.get("benchmark", DEFAULT_BENCHMARK)
    sales_amount = data.get("sales_amount", 0)
    target_type = target.get("type", "unknown")
    target_value = target.get("value", "unknown")
    target_name = target.get("name", target_value)

    total_cost = sum(cost_structure.get(k, 0) for k in COST_ITEM_LABELS.keys())
    gross_profit = max(0.0, min(1.0, 1.0 - total_cost))

    deviations = []
    four_actions = {"eliminate": [], "reduce": [], "raise": [], "create": []}

    for cost_item in COST_ITEM_LABELS.keys():
        current = cost_structure.get(cost_item, 0)
        bench = benchmark.get(cost_item, DEFAULT_BENCHMARK.get(cost_item, 0))
        dev_info = calculate_deviation(current, bench)
        action_category = classify_action(cost_item, dev_info)

        deviation_record = {
            "item": cost_item,
            "item_cn": COST_ITEM_LABELS.get(cost_item, cost_item),
            "current": round(current, 4),
            "benchmark": round(bench, 4),
            "deviation": dev_info["deviation"],
            "abs_deviation": dev_info["abs_deviation"],
            "severity": dev_info["severity"],
            "direction": dev_info["direction"],
            "action_category": action_category,
        }

        if action_category not in ("fixed", "normal"):
            suggestion = generate_action_suggestions(
                cost_item, current, bench, dev_info["deviation"],
                dev_info["severity"], action_category, sales_amount
            )
            if suggestion:
                deviation_record["suggestion"] = suggestion
                four_actions[action_category].append(suggestion)

        deviations.append(deviation_record)

    deviations.sort(key=lambda x: x["abs_deviation"], reverse=True)
    expected_impact = calculate_expected_impact(deviations, gross_profit, sales_amount)
    period_str = f"{period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}"

    return {
        "target": target_value, "target_name": target_name,
        "target_type": target_type,
        "gross_profit_percent": round(gross_profit, 4),
        "period": period_str, "sales_amount": sales_amount,
        "deviations": deviations, "four_actions": four_actions,
        "expected_impact": expected_impact,
        "data_completeness": round(total_cost, 4),
        "status": "success",
    }
