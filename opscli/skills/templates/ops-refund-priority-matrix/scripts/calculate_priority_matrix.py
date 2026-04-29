#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
退款优先级矩阵计算脚本

功能：
  1. 接收退款数据和运营建议 JSON（通过 stdin）
  2. 计算退款原因的频率和严重程度
  3. 按 Critical / Important / Nice-to-have 三级分类
  4. 计算每项修复的 ROI 评分并排序
  5. 输出结构化 JSON（含优先级矩阵、排序建议、汇总统计）

使用方式：
  cat input.json | python calculate_priority_matrix.py
  echo '{"target":...}' | python calculate_priority_matrix.py
"""

import json
import sys
import traceback
from typing import Any, Dict, List, Optional


# ============================================================
# 常量定义
# ============================================================

# 退款原因关键词映射（用于自动推断严重程度）
REFUND_REASON_SEVERITY_MAP = {
    # Critical 级别
    "leaking": "high",
    "broken": "high",
    "not working": "high",
    "size mismatch": "high",
    "missing parts": "high",
    "too small": "high",
    # Important 级别
    "poor quality": "medium",
    "not as described": "medium",
    "color mismatch": "medium",
    "late delivery": "medium",
    "too big": "medium",
    "poor insulation": "medium",
    "difficult cleaning": "medium",
    # Nice-to-have 级别
    "scratch": "low",
    "damaged box": "low",
    "limited colors": "low",
    "simple packaging": "low",
    "minor scratches": "low",
}

# 默认修复成本估算（美元）
DEFAULT_FIX_COST = {
    "high": 500,     # 高严重度问题通常需要设计/工程介入
    "medium": 200,   # 中严重度问题通常需要设计/文案调整
    "low": 50,       # 低严重度问题通常仅需简单调整
}

# 严重度映射到中文
SEVERITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

# 优先级映射
PRIORITY_MAP = {
    "critical": "P0",
    "important": "P1",
    "nice_to_have": "P2",
}


# ============================================================
# 核心函数
# ============================================================

def infer_severity(reason: str, suggestions: List[Dict[str, Any]]) -> str:
    """
    推断退款原因的严重程度

    优先级：
      1. 运营建议中匹配的 severity
      2. 退款原因关键词映射
      3. 默认 medium

    Args:
        reason: 退款原因文本
        suggestions: 运营建议列表

    Returns:
        str: "high" / "medium" / "low"
    """
    # 在运营建议中查找匹配项（将下划线替换为空格以统一匹配）
    reason_lower = reason.lower().replace("_", " ")
    for suggest in suggestions:
        issue_type = suggest.get("issue_type", "").lower()
        if issue_type in reason_lower or reason_lower in issue_type:
            sev = suggest.get("severity", "").lower()
            if sev in ("high", "medium", "low"):
                return sev

    # 关键词映射
    for keyword, severity in REFUND_REASON_SEVERITY_MAP.items():
        if keyword in reason_lower:
            return severity

    # 默认
    return "medium"


def classify_priority(severity: str, frequency: float, refund_rate: float) -> str:
    """
    三级优先级分类逻辑

    Args:
        severity: 严重程度（"high" / "medium" / "low"）
        frequency: 该原因占退款总数的频率（0~1）
        refund_rate: 整体退款率（0~1）

    Returns:
        str: "critical" / "important" / "nice_to_have"
    """
    if severity == "high" and (frequency > 0.20 or refund_rate > 0.10):
        return "critical"
    elif severity == "medium" and (frequency > 0.10 or refund_rate > 0.05):
        return "important"
    elif severity == "low" and frequency < 0.10 and refund_rate < 0.05:
        return "nice_to_have"
    elif severity == "high":
        return "important"  # high severity 但频率不够 critical
    elif severity == "medium":
        return "nice_to_have"  # medium severity 但频率不够 important
    else:
        return "nice_to_have"


def calculate_roi(expected_saving: float, fix_cost_estimate: float) -> int:
    """
    计算 ROI 评分（0-100）

    Args:
        expected_saving: 预期月度节省金额
        fix_cost_estimate: 估算修复成本

    Returns:
        int: 0~100 的 ROI 评分
    """
    if fix_cost_estimate <= 0:
        return 100

    # 年化 ROI = (月度节省 * 12) / 修复成本
    annual_roi = (expected_saving * 12) / fix_cost_estimate
    # 映射到 0-100 分
    score = min(100, int(annual_roi * 10))
    return max(0, score)


def generate_recommended_action(reason: str, severity: str) -> str:
    """
    根据退款原因生成修复建议

    Args:
        reason: 退款原因
        severity: 严重程度

    Returns:
        str: 修复建议文本
    """
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
    """
    核心分析函数：构建退款优先级矩阵

    Args:
        data: 输入 JSON 字典

    Returns:
        dict: 分析结果 JSON
    """
    # 提取输入数据
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

    # 统计总退款次数和金额
    total_count = sum(item.get("count", 0) for item in refund_data)
    total_amount = sum(item.get("amount", 0) for item in refund_data)

    # 初始化优先级矩阵
    matrix = {
        "critical": [],
        "important": [],
        "nice_to_have": [],
    }

    # 处理每条退款原因
    for item in refund_data:
        reason = item.get("reason", "unknown")
        count = item.get("count", 0)
        amount = item.get("amount", 0)

        # 计算频率
        frequency = count / total_count if total_count > 0 else 0

        # 推断严重程度和优先级
        severity = infer_severity(reason, suggestions)
        priority = classify_priority(severity, frequency, refund_rate)

        # 生成修复建议
        recommended_action = generate_recommended_action(reason, severity)

        # 查找匹配的运营建议（如有，统一将下划线替换为空格后匹配）
        matched_suggestion = None
        reason_normalized = reason.lower().replace("_", " ")
        for suggest in suggestions:
            issue_type = suggest.get("issue_type", "").lower().replace("_", " ")
            if issue_type in reason_normalized or reason_normalized in issue_type:
                matched_suggestion = suggest.get("suggestion", "")
                break
        if matched_suggestion:
            recommended_action = matched_suggestion

        # 计算预期节省（保守估计：修复后降低 60% 的该原因退款）
        expected_saving = round(amount * 0.6)

        # 估算修复成本
        fix_cost = DEFAULT_FIX_COST.get(severity, 200)

        # 计算 ROI 评分
        roi_score = calculate_roi(expected_saving, fix_cost)

        record = {
            "issue": reason,
            "count": count,
            "frequency": round(frequency, 4),
            "severity": severity,
            "severity_cn": SEVERITY_LABELS.get(severity, severity),
            "monthly_loss": amount,
            "recommended_action": recommended_action,
            "expected_saving": expected_saving,
            "fix_cost_estimate": fix_cost,
            "roi_score": roi_score,
            "priority": PRIORITY_MAP.get(priority, "P2"),
        }

        matrix[priority].append(record)

    # 每个级别内部按 ROI 评分降序排序
    for key in matrix:
        matrix[key].sort(key=lambda x: x["roi_score"], reverse=True)

    # 生成全局排序的行动列表（Critical > Important > Nice-to-have，同级别按 ROI 排序）
    sorted_actions = []
    rank = 1
    for priority_level in ["critical", "important", "nice_to_have"]:
        for item in matrix[priority_level]:
            sorted_actions.append({
                "rank": rank,
                "action": item["recommended_action"],
                "issue": item["issue"],
                "roi_score": item["roi_score"],
                "priority": item["priority"],
                "expected_saving": item["expected_saving"],
                "severity": item["severity"],
            })
            rank += 1

    # 汇总统计
    total_expected_saving = sum(
        item["expected_saving"] for level in matrix.values() for item in level
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
        "target": target_value,
        "target_type": target_type,
        "overall_refund_percent": round(refund_rate, 4),
        "category_benchmark": round(category_avg, 4),
        "period": period_str,
        "total_refund_amount": total_amount,
        "total_refund_count": total_count,
        "priority_matrix": matrix,
        "sorted_actions": sorted_actions,
        "summary": summary,
        "status": "success",
    }


# ============================================================
# 主入口
# ============================================================

def main():
    """主函数：读取 stdin JSON，执行分析，输出 JSON"""
    try:
        # 从 stdin 读取输入
        input_text = sys.stdin.read().strip()
        if not input_text:
            print(json.dumps({
                "error": "缺少输入数据，请通过 stdin 传入 JSON",
                "usage": "cat input.json | python calculate_priority_matrix.py",
                "status": "error"
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        # 解析 JSON
        try:
            data = json.loads(input_text)
        except json.JSONDecodeError as e:
            print(json.dumps({
                "error": f"JSON 解析失败: {str(e)}",
                "status": "error"
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        # 校验必要字段
        if "refund_data" not in data:
            print(json.dumps({
                "error": "缺少必要字段: refund_data",
                "status": "error"
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        # 执行分析
        result = build_priority_matrix(data)

        # 输出结果
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        # 捕获所有未处理异常，输出结构化错误信息
        error_info = {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "status": "error"
        }
        print(json.dumps(error_info, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
