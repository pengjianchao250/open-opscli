"""ops-asin-health-diagnoser Skill 的核心工具函数。

提供健康评分计算、格式化、数据合并等基础能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 默认权重与阈值
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "gross_profit_percent": 0.30,
    "convert_percent": 0.20,
    "ads_acos": 0.20,
    "refund_percent": 0.15,
    "inventory_days": 0.10,
    "star": 0.05,
}

DEFAULT_BENCHMARKS: dict[str, dict[str, Any]] = {
    "gross_profit_percent": {"healthy": 0.20, "warning": 0.10, "direction": "higher_is_better"},
    "convert_percent": {"healthy": 0.10, "warning": 0.05, "direction": "higher_is_better"},
    "ads_acos": {"healthy": 0.20, "warning": 0.30, "direction": "lower_is_better"},
    "refund_percent": {"healthy": 0.05, "warning": 0.10, "direction": "lower_is_better"},
    "inventory_days": {"healthy": 45, "warning": 90, "direction": "lower_is_better"},
    "star": {"healthy": 4.3, "warning": 4.0, "direction": "higher_is_better"},
}

ACTION_RECOMMENDATIONS: dict[str, dict[str, str]] = {
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


# ---------------------------------------------------------------------------
# 评分计算核心函数
# ---------------------------------------------------------------------------

def normalize(value: float | None, benchmark: dict[str, Any]) -> float:
    """将指标值标准化为 0-100 分。

    higher_is_better: 100 at healthy, 0 at warning
    lower_is_better: 100 at healthy, 0 at warning
    线性插值。
    """
    healthy = benchmark["healthy"]
    warning = benchmark["warning"]
    direction = benchmark["direction"]

    if value is None:
        return 50.0

    if direction == "higher_is_better":
        if value >= healthy:
            return 100.0
        if value <= warning:
            return 0.0
        return (value - warning) / (healthy - warning) * 100.0
    else:
        if value <= healthy:
            return 100.0
        if value >= warning:
            return 0.0
        return (warning - value) / (warning - healthy) * 100.0


def get_status(score: float) -> str:
    """根据标准化分数获取状态标签。"""
    if score >= 80:
        return "good"
    elif score >= 50:
        return "warning"
    else:
        return "critical"


def get_status_emoji(status: str) -> str:
    """获取状态对应的标识符号（GBK 兼容）。"""
    return {"good": "√", "warning": "!", "critical": "X"}.get(status, "?")


def calculate_health_score(
    metrics: dict[str, Any],
    weights: Optional[dict[str, float]] = None,
    benchmarks: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """从 ASIN 指标计算综合健康评分。

    Args:
        metrics: 指标值字典（如 {"gross_profit_percent": 0.185, ...}）
        weights: 可选自定义权重（默认 DEFAULT_WEIGHTS）
        benchmarks: 可选自定义阈值（默认 DEFAULT_BENCHMARKS）

    Returns:
        包含健康评分、等级、指标详情、问题和优先行动的字典。
    """
    weights = weights or DEFAULT_WEIGHTS
    benchmarks = benchmarks or DEFAULT_BENCHMARKS

    effective_weights = dict(weights)
    if metrics.get("star") is None:
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

        normalized_val = normalize(value, benchmark)
        status = get_status(normalized_val)

        total_score += normalized_val * weight

        detail = {
            "metric": metric,
            "value": value,
            "normalized_score": round(normalized_val, 1),
            "status": status,
            "weight": round(weight, 3),
            "weighted_score": round(normalized_val * weight, 1),
            "benchmark": benchmark,
        }
        metrics_detail.append(detail)

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

    if health_score >= 80:
        health_level = "Excellent"
    elif health_score >= 60:
        health_level = "Good"
    elif health_score >= 40:
        health_level = "Fair"
    else:
        health_level = "Poor"

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


def format_diagnosis(result: dict[str, Any], asin: str, product_name: str, date_range: str) -> str:
    """将诊断结果格式化为可读文本。"""
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

        if metric in ("gross_profit_percent", "convert_percent", "ads_acos", "refund_percent"):
            value_str = f"{value * 100:.1f}%"
        elif metric == "star":
            value_str = f"{value:.1f}"
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


# ---------------------------------------------------------------------------
# 查询结果数据提取与合并
# ---------------------------------------------------------------------------

def extract_metrics_from_query_result(
    query_data: dict[str, Any],
    *,
    dataset_alias: str = "ds_d35ac6f3910c",
    star_data: dict[str, Any] | None = None,
    star_dataset_alias: str = "ds_pdTYjvLRCadv",
) -> dict[str, Any]:
    """从 opscli query 查询结果中提取并合并 ASIN 健康指标。

    Args:
        query_data: 主数据集查询结果（包含 result.data 字段）
        dataset_alias: 主数据集别名
        star_data: 辅助数据集查询结果（包含星级数据），可选
        star_dataset_alias: 辅助数据集别名

    Returns:
        以 ASIN 为 key 的指标字典映射
    """
    result_map: dict[str, dict[str, Any]] = {}

    rows = _extract_rows(query_data)
    for row in rows:
        asin = _extract_field(row, "asin", dataset_alias) or row.get("asin", "")
        if not asin:
            continue

        product_name = _extract_field(row, "product_name", dataset_alias) or row.get("product_name", "")

        metrics = {
            "gross_profit_percent": _to_float_safe(_extract_field(row, "gross_profit_percent", dataset_alias)),
            "convert_percent": _to_float_safe(_extract_field(row, "convert_percent", dataset_alias)),
            "ads_acos": _to_float_safe(_extract_field(row, "ads_acos", dataset_alias)),
            "refund_percent": _to_float_safe(_extract_field(row, "refund_percent", dataset_alias)),
            "inventory_days": _to_float_safe(_extract_field(row, "sell_qty_days", dataset_alias)),
            "star": None,
        }

        result_map[asin] = {
            "asin": asin,
            "product_name": product_name,
            "metrics": metrics,
        }

    # 合并星级数据
    if star_data:
        star_rows = _extract_rows(star_data)
        star_map: dict[str, float | None] = {}
        for row in star_rows:
            star_asin = _extract_field(row, "asin", star_dataset_alias) or row.get("asin", "")
            if star_asin:
                star_map[star_asin] = _to_float_safe(_extract_field(row, "star", star_dataset_alias))

        for asin, info in result_map.items():
            if asin in star_map:
                info["metrics"]["star"] = star_map[asin]

    return result_map


def _extract_rows(data: dict[str, Any]) -> list[dict]:
    """从查询结果中提取行数据，兼容多种返回格式。"""
    if isinstance(data, list):
        return data
    if "data" in data:
        inner = data["data"]
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict) and "result" in inner:
            result = inner["result"]
            if isinstance(result, dict) and "data" in result:
                return result["data"]
            if isinstance(result, list):
                return result
    if "result" in data:
        result = data["result"]
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        if isinstance(result, list):
            return result
    return []


def _extract_field(row: dict, field_name: str, dataset_alias: str) -> Any:
    """从查询结果行中提取字段值，兼容 global_alias 和 field_name。"""
    # 先尝试精确匹配
    if field_name in row:
        return row[field_name]
    # 再尝试 global_alias 前缀匹配
    for key, val in row.items():
        if key.startswith("f_") and field_name in str(val):
            continue
    # 直接返回 None
    return row.get(field_name)


def _to_float_safe(v: Any) -> float | None:
    """安全转换为 float，None 和空值保持 None。"""
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 数据目录发现
# ---------------------------------------------------------------------------

def discover_data_dir(*, skills_dir: str | None = None) -> Path | None:
    """发现 ops-dataset-query 的 data 目录。

    按以下优先级扫描：
    1. OPSCLI_SKILLS_DIR 环境变量
    2. skills_dir 参数
    3. 常见安装路径
    """
    candidates: list[Path] = []

    env_dir = __import__("os").environ.get("OPSCLI_SKILLS_DIR")
    if env_dir:
        candidates.append(Path(env_dir) / "ops-dataset-query" / "data")

    if skills_dir:
        candidates.append(Path(skills_dir) / "ops-dataset-query" / "data")

    candidates.extend([
        Path.home() / ".claude" / "skills" / "ops-dataset-query" / "data",
        Path.home() / ".openclaw" / "skills" / "ops-dataset-query" / "data",
        Path.home() / ".codex" / "skills" / "ops-dataset-query" / "data",
        Path.home() / ".config" / "opencode" / "skills" / "ops-dataset-query" / "data",
    ])

    for d in candidates:
        if d.exists() and (d / "dataset_fields.csv").exists():
            return d

    return None