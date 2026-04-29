"""ops-refund-priority-matrix Skill 的核心工具函数。

提供退款优先级矩阵计算能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


REFUND_REASON_SEVERITY_MAP: Dict[str, str] = {
    "leaking": "high", "broken": "high", "not working": "high",
    "size mismatch": "high", "missing parts": "high", "too small": "high",
    "poor quality": "medium", "not as described": "medium", "color mismatch": "medium",
    "late delivery": "medium", "too big": "medium", "poor insulation": "medium",
    "difficult cleaning": "medium",
    "scratch": "low", "damaged box": "low", "limited colors": "low",
    "simple packaging": "low", "minor scratches": "low",
}

DEFAULT_FIX_COST: Dict[str, int] = {
    "high": 500,
    "medium": 200,
    "low": 50,
}

SEVERITY_LABELS: Dict[str, str] = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

PRIORITY_MAP: Dict[str, str] = {
    "critical": "P0",
    "important": "P1",
    "nice_to_have": "P2",
}


def infer_severity(reason: str, suggestions: List[Dict[str, Any]]) -> str:
    """推断退款原因的严重程度。"""
    reason_lower = reason.lower().replace("_", " ")
    for suggest in suggestions:
        issue_type = suggest.get("issue_type", "").lower()
        if issue_type in reason_lower or reason_lower in issue_type:
            sev = suggest.get("severity", "").lower()
            if sev in ("high", "medium", "low"):
                return sev
    for keyword, severity in REFUND_REASON_SEVERITY_MAP.items():
        if keyword in reason_lower:
            return severity
    return "medium"


def classify_priority(severity: str, frequency: float, refund_rate: float) -> str:
    """三级优先级分类逻辑。"""
    if severity == "high" and (frequency > 0.20 or refund_rate > 0.10):
        return "critical"
    elif severity == "medium" and (frequency > 0.10 or refund_rate > 0.05):
        return "important"
    elif severity == "low" and frequency < 0.10 and refund_rate < 0.05:
        return "nice_to_have"
    elif severity == "high":
        return "important"
    elif severity == "medium":
        return "nice_to_have"
    else:
        return "nice_to_have"


def calculate_roi(expected_saving: float, fix_cost_estimate: float) -> int:
    """计算 ROI 评分（0-100）。"""
    if fix_cost_estimate <= 0:
        return 100
    annual_roi = (expected_saving * 12) / fix_cost_estimate
    score = min(100, int(annual_roi * 10))
    return max(0, score)


def generate_recommended_action(reason: str, severity: str) -> str:
    """根据退款原因生成修复建议。"""
    reason_lower = reason.lower().replace("_", " ")
    action_map = {
        "leaking": "排查密封圈和焊接工艺，修复漏水问题",
        "broken": "加固包装或更换更耐用的材质",
        "not working": "检查电路/组装质检流程，修复功能性故障",
        "size mismatch": "修正尺码表，增加实物对比图",
        "too small": "增加尺寸标注清晰度，提供对比图",
        "too big": "增加尺寸标注清晰度，提供对比图",
        "missing parts": "增加包装清单核对流程",
        "poor quality": "与供应商谈判改进材料或工艺",
        "not as described": "使用实拍图，调整文案描述避免过度美化",
        "color mismatch": "增加色卡标注，管理屏幕色差预期",
        "late delivery": "评估更换物流商或优化发货流程",
        "poor insulation": "升级保温材料或调整用户预期",
        "difficult cleaning": "优化产品设计或增加清洁说明",
        "scratch": "改进包装保护或加强出库质检",
        "damaged box": "加固外包装",
        "limited colors": "开发新颜色变体（资源允许时）",
        "simple packaging": "提升包装设计（资源允许时）",
    }
    for keyword, action in action_map.items():
        if keyword in reason_lower:
            return action
    return f"分析并修复 '{reason}' 相关根因"


def build_priority_matrix(data: Dict[str, Any]) -> Dict[str, Any]:
    """核心分析函数：构建退款优先级矩阵。"""
    target = data.get("target", {})
    period = data.get("period", {})
    refund_data = data.get("refund_data", [])
    suggestions = data.get("operation_suggestions", [])
    financial = data.get("financial_context", {})

    target_type = target.get("type", "unknown")
    target_value = target.get("value", "unknown")

    refund_rate = financial.get("refund_percent", 0)
    category_avg = financial.get("category_avg_refund", 0)
    monthly_sales = financial.get("monthly_sales", 0)
    gross_profit_pct = financial.get("gross_profit_percent", 0)

    total_count = sum(item.get("count", 0) for item in refund_data)
    total_amount = sum(item.get("amount", 0) for item in refund_data)

    matrix: Dict[str, List] = {"critical": [], "important": [], "nice_to_have": []}

    for item in refund_data:
        reason = item.get("reason", "unknown")
        count = item.get("count", 0)
        amount = item.get("amount", 0)

        frequency = count / total_count if total_count > 0 else 0

        severity = infer_severity(reason, suggestions)
        priority = classify_priority(severity, frequency, refund_rate)

        recommended_action = generate_recommended_action(reason, severity)

        matched_suggestion = None
        reason_normalized = reason.lower().replace("_", " ")
        for suggest in suggestions:
            issue_type = suggest.get("issue_type", "").lower().replace("_", " ")
            if issue_type in reason_normalized or reason_normalized in issue_type:
                matched_suggestion = suggest.get("suggestion", "")
                break
        if matched_suggestion:
            recommended_action = matched_suggestion

        expected_saving = round(amount * 0.6)
        fix_cost = DEFAULT_FIX_COST.get(severity, 200)
        roi_score = calculate_roi(expected_saving, fix_cost)

        record = {
            "issue": reason, "count": count, "frequency": round(frequency, 4),
            "severity": severity, "severity_cn": SEVERITY_LABELS.get(severity, severity),
            "monthly_loss": amount, "recommended_action": recommended_action,
            "expected_saving": expected_saving, "fix_cost_estimate": fix_cost,
            "roi_score": roi_score, "priority": PRIORITY_MAP.get(priority, "P2"),
        }
        matrix[priority].append(record)

    for key in matrix:
        matrix[key].sort(key=lambda x: x["roi_score"], reverse=True)

    sorted_actions = []
    rank = 1
    for priority_level in ["critical", "important", "nice_to_have"]:
        for item_item in matrix[priority_level]:
            sorted_actions.append({
                "rank": rank, "action": item_item["recommended_action"],
                "issue": item_item["issue"], "roi_score": item_item["roi_score"],
                "priority": item_item["priority"], "expected_saving": item_item["expected_saving"],
                "severity": item_item["severity"],
            })
            rank += 1

    total_expected_saving = sum(
        item_item["expected_saving"] for level in matrix.values() for item_item in level
    )

    summary = {
        "critical_count": len(matrix["critical"]),
        "important_count": len(matrix["important"]),
        "nice_to_have_count": len(matrix["nice_to_have"]),
        "total_monthly_loss": total_amount,
        "total_expected_saving": total_expected_saving,
    }

    period_str = f"{period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}"

    return {
        "target": target_value, "target_type": target_type,
        "overall_refund_percent": round(refund_rate, 4),
        "category_benchmark": round(category_avg, 4),
        "period": period_str, "total_refund_amount": total_amount,
        "total_refund_count": total_count,
        "priority_matrix": matrix, "sorted_actions": sorted_actions,
        "summary": summary, "status": "success",
    }
