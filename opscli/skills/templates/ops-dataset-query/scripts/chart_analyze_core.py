"""图表数据异常检测引擎 — CLI / MCP 共用。

提供字段角色识别、当前数据异常检测、环比趋势异常检测、
关键发现生成和结构化报告生成等纯函数。
不依赖 opscli 命令行工具，仅依赖 core.py 中的数值工具函数。
"""

from __future__ import annotations

from core import format_pct, safe_pct, to_float

# ---------------------------------------------------------------------------
# 异常检测阈值（常量，便于统一调整）
# ---------------------------------------------------------------------------

# 毛利率低于此值触发 negative_margin（严重亏损）
NEGATIVE_MARGIN_CRITICAL = -0.20
# 毛利率低于 0 触发 negative_margin（普通亏损）
NEGATIVE_MARGIN_WARNING = 0.0
# 毛利环比下降超过此比例触发 profit_drop
PROFIT_DROP_THRESHOLD = -0.30
# 原价金额环比下降超过此比例触发 revenue_cliff
REVENUE_CLIFF_THRESHOLD = -0.20
# 低毛利警告阈值（毛利率 < 5%）
LOW_MARGIN_THRESHOLD = 0.05

# ---------------------------------------------------------------------------
# 字段业务角色自动检测
# ---------------------------------------------------------------------------

# 角色 → 关键词模式列表（匹配 verbose_name / field_name，不区分大小写）
ROLE_PATTERNS: dict[str, list[str]] = {
    "revenue": ["price", "原价", "revenue", "sales", "gmv", "金额"],
    "profit": ["profit", "毛利", "gross_profit", "利润"],
    "ad_cost": ["advertis", "广告", "ad_fee", "ad_cost", "推广"],
    "quantity": ["qty", "order_qty", "数量", "订单量", "order_count"],
}


def _score_role(name: str, patterns: list[str]) -> int:
    """对字段名按角色模式打分。"""
    name_lower = name.lower()
    score = 0
    for pattern in patterns:
        if pattern.lower() in name_lower:
            score += 10
            # 精确匹配额外加分
            if name_lower == pattern.lower():
                score += 20
    return score


def detect_field_role(field_info: dict) -> str | None:
    """检测字段的业务角色。

    根据字段的 verbose_name / field_name 与预定义模式匹配，
    返回得分最高的角色名。

    Args:
        field_info: 字段元数据（含 verbose_name、field_name 等）

    Returns:
        角色名（如 "revenue"、"profit"、"ad_cost"、"quantity"），或 None
    """
    candidates = []
    for name_key in ("verbose_name", "field_name"):
        name = str(field_info.get(name_key, ""))
        if not name:
            continue
        for role, patterns in ROLE_PATTERNS.items():
            score = _score_role(name, patterns)
            if score > 0:
                candidates.append((score, role))

    if not candidates:
        return None

    # 返回得分最高的角色
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


# ---------------------------------------------------------------------------
# 字段映射辅助
# ---------------------------------------------------------------------------


def build_alias_map(
    queries: list[dict],
) -> dict[str, dict]:
    """构建 global_alias → {name, role, field_info} 的映射。

    Args:
        queries: 图表 query 列表（已添加 _mapping）

    Returns:
        {global_alias: {"name": str, "role": str|None, "field_info": dict}}
    """
    alias_map: dict[str, dict] = {}
    for q in queries:
        mapping = q.get("_mapping", {})
        for fm in mapping.get("field_mappings", []):
            g_alias = fm["alias"]
            if g_alias in alias_map:
                continue
            fi = fm.get("field_info", {})
            role = detect_field_role(fi) if fi else None
            alias_map[g_alias] = {
                "name": fm.get("mapped_name", g_alias),
                "role": role,
                "field_info": fi,
            }
    return alias_map


def find_role_alias(alias_map: dict[str, dict], role: str) -> str | None:
    """从 alias_map 中找到指定角色对应的 alias。"""
    for alias, info in alias_map.items():
        if info["role"] == role:
            return alias
    return None


def compute_margin(price: float, profit: float) -> float:
    """计算毛利率。"""
    return (profit / price * 100) if price else 0.0


# ---------------------------------------------------------------------------
# 异常检测
# ---------------------------------------------------------------------------


def detect_anomalies_current(
    rows: list[dict],
    alias_map: dict[str, dict],
) -> list[dict]:
    """检测当期数据中的异常（不依赖环比）。

    规则：
    - negative_margin: 毛利率 < 0
    """
    anomalies: list[dict] = []

    profit_alias = find_role_alias(alias_map, "profit")
    revenue_alias = find_role_alias(alias_map, "revenue")

    # 维度字段：所有非 metric 的字段
    dim_aliases = [
        a for a, info in alias_map.items()
        if info["role"] is None and info.get("field_info", {}).get("field_type") == "dimension"
    ]

    for row in rows:
        dims = {alias_map[a]["name"]: row.get(a, "") for a in dim_aliases if a in row}

        # negative_margin: 毛利率 < 0
        if profit_alias and revenue_alias:
            profit = to_float(row.get(profit_alias))
            revenue = to_float(row.get(revenue_alias))
            margin = compute_margin(revenue, profit)
            if margin < NEGATIVE_MARGIN_WARNING:
                severity = "critical" if margin < NEGATIVE_MARGIN_CRITICAL else "warning"
                anomalies.append({
                    "type": "negative_margin",
                    "severity": severity,
                    "dimensions": dims,
                    "details": f"毛利率 {margin:.1f}%，当期毛利 {profit:,.0f}，原价 {revenue:,.0f}",
                    "metric_values": {
                        alias_map[profit_alias]["name"]: profit,
                        alias_map[revenue_alias]["name"]: revenue,
                        "毛利率(%)": round(margin, 2),
                    },
                })

    return anomalies


def detect_anomalies_trend(
    rows: list[dict],
    alias_map: dict[str, dict],
) -> list[dict]:
    """检测环比趋势中的异常（依赖 dataComparison 数据）。

    规则：
    - profit_drop: 毛利环比下降 > 30%
    - revenue_cliff: 原价金额环比下降 > 20%
    - ad_roi_decline: 广告费上升 + 毛利下降
    - zero_orders: 当期订单量归零（对比期 > 0）

    DC 数据的列名格式为 f_xxx / last_f_xxx / diff_f_xxx / pct_f_xxx，
    其中 xxx 是 build 时指定的 alias（如 f_profit / f_price / f_ad / f_qty）。
    本函数通过关键词模式自动匹配角色，不依赖 chart 的 global_alias。
    """
    anomalies: list[dict] = []

    if not rows:
        return anomalies

    # 从 DC 数据的列名自动推断角色
    # 列名格式: f_xxx, last_f_xxx, diff_f_xxx, pct_f_xxx
    sample = rows[0]
    dc_aliases = [k for k in sample.keys() if k.startswith("f_") and not k.startswith("last_") and not k.startswith("diff_") and not k.startswith("pct_")]

    # 为每个 alias 检测角色
    dc_role_map: dict[str, str] = {}  # alias -> role
    for alias in dc_aliases:
        for role, patterns in ROLE_PATTERNS.items():
            alias_lower = alias.lower()
            if any(p.lower() in alias_lower for p in patterns):
                dc_role_map[alias] = role
                break

    # 维度字段：DC 数据中不属于 metric 的 f_ 开头列
    dim_aliases = [a for a in dc_aliases if a not in dc_role_map]

    profit_alias = next((a for a, r in dc_role_map.items() if r == "profit"), None)
    revenue_alias = next((a for a, r in dc_role_map.items() if r == "revenue"), None)
    ad_alias = next((a for a, r in dc_role_map.items() if r == "ad_cost"), None)
    qty_alias = next((a for a, r in dc_role_map.items() if r == "quantity"), None)

    # 构建 alias → 可读名称映射（优先使用 alias_map，否则用 alias 本身）
    def name_of(alias: str) -> str:
        if alias in alias_map:
            return alias_map[alias]["name"]
        # 尝试去掉 f_ 前缀作为可读名称
        return alias[2:] if alias.startswith("f_") else alias

    for row in rows:
        dims = {name_of(a): row.get(a, "") for a in dim_aliases}

        # profit_drop: 毛利环比大幅下降
        if profit_alias:
            pct_key = f"pct_{profit_alias}"
            if pct_key in row:
                pct_profit = to_float(row[pct_key])
                if pct_profit < PROFIT_DROP_THRESHOLD:
                    cur = to_float(row.get(profit_alias))
                    prev = to_float(row.get(f"last_{profit_alias}"))
                    anomalies.append({
                        "type": "profit_drop",
                        "severity": "warning",
                        "dimensions": dims,
                        "details": f"毛利环比 {format_pct(pct_profit)}，当期 {cur:,.0f}，对比期 {prev:,.0f}",
                        "metric_values": {
                            "当期毛利": cur,
                            "对比期毛利": prev,
                            "环比变化率": format_pct(pct_profit),
                        },
                    })

        # revenue_cliff: 原价金额环比大幅下降
        if revenue_alias:
            pct_key = f"pct_{revenue_alias}"
            if pct_key in row:
                pct_revenue = to_float(row[pct_key])
                if pct_revenue < REVENUE_CLIFF_THRESHOLD:
                    cur = to_float(row.get(revenue_alias))
                    prev = to_float(row.get(f"last_{revenue_alias}"))
                    anomalies.append({
                        "type": "revenue_cliff",
                        "severity": "warning",
                        "dimensions": dims,
                        "details": f"原价环比 {format_pct(pct_revenue)}，当期 {cur:,.0f}，对比期 {prev:,.0f}",
                        "metric_values": {
                            "当期原价": cur,
                            "对比期原价": prev,
                            "环比变化率": format_pct(pct_revenue),
                        },
                    })

        # ad_roi_decline: 广告费上升 + 毛利下降
        if ad_alias and profit_alias:
            ad_pct_key = f"pct_{ad_alias}"
            profit_pct_key = f"pct_{profit_alias}"
            if ad_pct_key in row and profit_pct_key in row:
                ad_pct = to_float(row[ad_pct_key])
                profit_pct = to_float(row[profit_pct_key])
                if ad_pct > 0 and profit_pct < 0:
                    anomalies.append({
                        "type": "ad_roi_decline",
                        "severity": "warning",
                        "dimensions": dims,
                        "details": f"广告费环比 {format_pct(ad_pct)}，毛利环比 {format_pct(profit_pct)}",
                        "metric_values": {
                            "广告费环比": format_pct(ad_pct),
                            "毛利环比": format_pct(profit_pct),
                        },
                    })

        # zero_orders: 当期订单量归零
        if qty_alias:
            cur_qty = to_float(row.get(qty_alias))
            prev_qty = to_float(row.get(f"last_{qty_alias}"))
            if cur_qty == 0 and prev_qty > 0:
                anomalies.append({
                    "type": "zero_orders",
                    "severity": "info",
                    "dimensions": dims,
                    "details": f"对比期订单量 {prev_qty:.0f}，当期归零",
                    "metric_values": {
                        "当期订单量": 0,
                        "对比期订单量": prev_qty,
                    },
                })

    return anomalies


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


def generate_findings(
    rows: list[dict],
    dc_rows: list[dict] | None,
    alias_map: dict[str, dict],
    anomalies: list[dict],
) -> list[str]:
    """根据异常检测结果生成人类可读的关键发现。

    Args:
        rows: 当期数据行
        dc_rows: dataComparison 数据行（可选）
        alias_map: 字段映射
        anomalies: 已检测到的异常列表

    Returns:
        发现列表（字符串数组）
    """
    findings: list[str] = []

    profit_alias = find_role_alias(alias_map, "profit")
    revenue_alias = find_role_alias(alias_map, "revenue")

    # 1. 整体毛利率
    if profit_alias and revenue_alias:
        total_revenue = sum(to_float(r.get(revenue_alias)) for r in rows)
        total_profit = sum(to_float(r.get(profit_alias)) for r in rows)
        margin = compute_margin(total_revenue, total_profit)
        findings.append(f"整体毛利率 {margin:.2f}%（总原价 {total_revenue:,.0f}，总毛利 {total_profit:,.0f}）")

    # 2. 汇总异常统计
    critical_count = sum(1 for a in anomalies if a["severity"] == "critical")
    warning_count = sum(1 for a in anomalies if a["severity"] == "warning")
    info_count = sum(1 for a in anomalies if a["severity"] == "info")

    if critical_count > 0:
        findings.append(f"发现 {critical_count} 个严重异常（{warning_count} 警告，{info_count} 提示）")

    # 3. 环比整体趋势（如果有 DC 数据）
    if dc_rows and profit_alias and revenue_alias:
        # 从 DC 数据计算总体环比
        dc_revenue_alias = f"f_{revenue_alias}" if f"f_{revenue_alias}" in dc_rows[0] else revenue_alias
        dc_profit_alias = f"f_{profit_alias}" if f"f_{profit_alias}" in dc_rows[0] else profit_alias

        if dc_revenue_alias in dc_rows[0]:
            total_cur_rev = sum(to_float(r.get(dc_revenue_alias)) for r in dc_rows)
            total_prev_rev = sum(to_float(r.get(f"last_{dc_revenue_alias}")) for r in dc_rows)
            total_cur_profit = sum(to_float(r.get(dc_profit_alias)) for r in dc_rows)
            total_prev_profit = sum(to_float(r.get(f"last_{dc_profit_alias}")) for r in dc_rows)

            rev_pct = safe_pct(total_cur_rev, total_prev_rev)
            profit_pct = safe_pct(total_cur_profit, total_prev_profit)
            findings.append(
                f"原价环比 {format_pct(rev_pct)}，毛利环比 {format_pct(profit_pct)}"
            )

    # 4. 毛利为负的渠道数量
    neg_margin_count = sum(1 for a in anomalies if a["type"] == "negative_margin")
    if neg_margin_count > 0:
        findings.append(f"{neg_margin_count} 个渠道毛利为负（亏损运营）")

    # 5. 广告 ROI 恶化渠道
    ad_roi_count = sum(1 for a in anomalies if a["type"] == "ad_roi_decline")
    if ad_roi_count > 0:
        findings.append(f"{ad_roi_count} 个渠道广告投入增加但毛利下降（ROI 恶化）")

    return findings


def generate_report(
    queries: list[dict],
    chart_uuid: str | None,
    alias_map: dict[str, dict],
    dc_rows: list[dict] | None,
) -> dict:
    """生成完整的异常检测报告。

    Args:
        queries: 已映射的 query 列表（含 result）
        chart_uuid: 图表 UUID
        alias_map: 字段映射
        dc_rows: dataComparison 数据行（可选）

    Returns:
        结构化报告字典
    """
    # 收集所有行数据
    all_rows: list[dict] = []
    period_info: dict = {}

    for q in queries:
        result = q.get("result", {})
        rows = result.get("data", [])
        all_rows.extend(rows)

        # 提取时间范围（从 WHERE 条件）
        payload = q.get("payload", {})
        where = payload.get("query", {}).get("where", {})
        conditions = where.get("conditions", [])
        for cond in conditions:
            field = cond.get("field", "")
            if "date_id" in field and cond.get("operator") == "between":
                values = cond.get("value", [])
                if len(values) == 2:
                    period_info = {"start": values[0], "end": values[1]}

    # 执行异常检测
    anomalies = detect_anomalies_current(all_rows, alias_map)

    if dc_rows:
        anomalies.extend(detect_anomalies_trend(dc_rows, alias_map))

    # 按严重度排序
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    anomalies.sort(key=lambda a: severity_order.get(a["severity"], 3))

    # 生成关键发现
    findings = generate_findings(all_rows, dc_rows, alias_map, anomalies)

    # 汇总统计
    dimensions = [info["name"] for info in alias_map.values() if info["role"] is None]
    metrics = [info["name"] for info in alias_map.values() if info["role"] is not None]

    summary = {
        "total_rows": len(all_rows),
        "dimensions": dimensions,
        "metrics": metrics,
        "anomaly_count": len(anomalies),
        "anomaly_by_type": {},
        "anomaly_by_severity": {"critical": 0, "warning": 0, "info": 0},
    }
    for a in anomalies:
        summary["anomaly_by_type"][a["type"]] = summary["anomaly_by_type"].get(a["type"], 0) + 1
        summary["anomaly_by_severity"][a["severity"]] = summary["anomaly_by_severity"].get(a["severity"], 0) + 1

    return {
        "chart_uuid": chart_uuid,
        "period": period_info,
        "summary": summary,
        "anomalies": anomalies,
        "findings": findings,
    }
