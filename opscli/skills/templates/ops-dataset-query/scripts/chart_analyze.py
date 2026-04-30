"""图表数据异常检测脚本。

获取图表查询结果，自动映射字段别名，检测字段业务角色，
执行 5 类异常规则，输出结构化 JSON 报告。

用法：
    # 通过 UUID 获取并分析（自动执行查询 + 映射）
    python chart_analyze.py --uuid <chart_uuid> [--pretty]

    # 分析已保存的 chart run 结果
    python chart_analyze.py --input /tmp/chart_result.json [--pretty]

    # 附带 dataComparison 环比数据（增强趋势异常检测）
    python chart_analyze.py --input /tmp/chart_result.json --dc-input /tmp/dc_result.json [--pretty]

异常检测规则：
    1. negative_margin  — 毛利率 < 0（亏损）
    2. profit_drop      — 毛利环比下降 > 30%
    3. revenue_cliff    — 原价金额环比下降 > 20%
    4. ad_roi_decline   — 广告费上升 + 毛利下降（ROI 恶化）
    5. zero_orders      — 当期订单量归零（对比期 > 0）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_map import map_chart_queries
from core import (
    check_mapping_hit,
    discover_data_dir,
    format_pct,
    load_local_index,
    safe_pct,
    to_float,
    try_upgrade,
)

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
# 图表数据加载
# ---------------------------------------------------------------------------


def load_chart_data(uuid_str: str | None, input_path: str | None) -> tuple[list[dict], str | None, dict | None]:
    """加载图表数据，返回 (queries, chart_uuid, merged_data)。

    Args:
        uuid_str: 图表 UUID（通过 opscli 获取）
        input_path: 已保存的 chart run JSON 文件路径

    Returns:
        (queries, chart_uuid, merged_data)
        - queries: 各 query 的数据列表（含 result）
        - chart_uuid: 图表 UUID
        - merged_data: 合并后的行数据
    """
    if uuid_str:
        result = subprocess.run(
            ["opscli", "query", "chart", "--uuid", uuid_str, "--run", "--pretty"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            print(f"opscli 调用失败: {result.stderr}", file=sys.stderr)
            raise SystemExit(1)
        content = json.loads(result.stdout)
        chart_data = content.get("data", {})
        queries = chart_data.get("queries", [])
        chart_uuid = chart_data.get("chart_uuid")
        merged = chart_data.get("merged", {})
        return queries, chart_uuid, merged
    elif input_path:
        with open(input_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        # 兼容 opscli 输出包装格式和直接 data 数组
        if isinstance(content, dict) and "data" in content:
            data = content["data"]
            if isinstance(data, dict) and "queries" in data:
                # chart run 输出格式
                queries = data["queries"]
                chart_uuid = data.get("chart_uuid")
                merged = data.get("merged")
                return queries, chart_uuid, merged
            elif isinstance(data, dict) and "result" in data:
                # 普通 query build --run 输出格式
                rows = data["result"].get("data", [])
                return [{"index": 0, "result": data["result"]}], None, {"rows": rows}
        elif isinstance(content, dict) and "queries" in content:
            return content["queries"], content.get("chart_uuid"), content.get("merged")
        elif isinstance(content, list):
            # 直接是 queries 数组
            return content, None, None

    return [], None, None


def load_dc_data(dc_input: str | None) -> list[dict] | None:
    """加载 dataComparison 环比结果。

    Args:
        dc_input: DC 结果 JSON 文件路径

    Returns:
        行数据列表，或 None
    """
    if not dc_input:
        return None
    with open(dc_input, "r", encoding="utf-8") as f:
        content = json.load(f)
    # 兼容 opscli 输出包装格式
    if isinstance(content, dict) and "data" in content:
        data = content["data"]
        if isinstance(data, dict) and "result" in data:
            return data["result"].get("data", [])
        if isinstance(data, list):
            return data
    if isinstance(content, list):
        return content
    return None


# ---------------------------------------------------------------------------
# 异常检测引擎
# ---------------------------------------------------------------------------


def build_alias_map(
    queries: list[dict],
) -> dict[str, dict]:
    """构建 global_alias → {name, role, field_info} 的映射。

    Args:
        queries: 图表 query 列表（已添加 _mapping）
        dataset_index: 数据集索引
        field_index: 字段索引

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


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="图表数据异常检测工具")
    parser.add_argument("--uuid", help="图表 UUID，直接调用 opscli 获取并执行")
    parser.add_argument("--input", help="已保存的 chart run JSON 文件路径")
    parser.add_argument("--dc-input", help="已保存的 dataComparison 环比结果 JSON 文件路径")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    parser.add_argument("--skills-dir", help="指定 Skill 安装根目录")
    parser.add_argument("--data-dir", help="直接指定数据目录路径")
    parser.add_argument("--no-auto-upgrade", action="store_true",
                        help="禁用自动升级兜底（映射失败时不自动调用 upgrade）")
    args = parser.parse_args()

    if not args.uuid and not args.input:
        parser.error("必须提供 --uuid 或 --input 之一")

    # 确定数据目录
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        discovered = discover_data_dir(skills_dir=args.skills_dir)
        if discovered is None:
            # 尝试自动升级安装
            if not args.no_auto_upgrade and try_upgrade(
                Path.home() / ".claude" / "skills" / "ops-dataset-query" / "data",
                caller="chart_analyze",
            ):
                discovered = discover_data_dir(skills_dir=args.skills_dir)
            if discovered is None:
                print(
                    json.dumps(
                        {
                            "success": False,
                            "error": "未找到 ops-dataset-query 数据目录。"
                                     "请先执行 opscli skills install ops-dataset-query。",
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )
                raise SystemExit(1)
        data_dir = discovered

    # 加载本地索引
    dataset_index, field_index = load_local_index(data_dir)

    # 加载图表数据
    queries, chart_uuid, _merged = load_chart_data(args.uuid, args.input)

    if not queries:
        print(json.dumps({"success": False, "error": "未获取到图表数据"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

    # 执行字段映射（添加 _mapping 信息）
    mapped_queries = map_chart_queries(queries, dataset_index, field_index)

    # 恢复 result 数据（map_chart_queries 只映射 query 结构，不包含 result）
    for i, mq in enumerate(mapped_queries):
        if i < len(queries) and "result" in queries[i]:
            mq["result"] = queries[i]["result"]

    # 自动升级兜底：如果所有字段都没映射成功，尝试 upgrade 后重试
    if not args.no_auto_upgrade and not check_mapping_hit(mapped_queries):
        if try_upgrade(data_dir, caller="chart_analyze"):
            # 重新加载索引并重新映射
            dataset_index, field_index = load_local_index(data_dir)
            mapped_queries = map_chart_queries(queries, dataset_index, field_index)
            # 恢复 result 数据
            for i, mq in enumerate(mapped_queries):
                if i < len(queries) and "result" in queries[i]:
                    mq["result"] = queries[i]["result"]

    # 构建字段角色映射
    alias_map = build_alias_map(mapped_queries)

    # 加载 DC 环比数据（可选）
    dc_rows = load_dc_data(args.dc_input)

    # 生成报告
    report = generate_report(mapped_queries, chart_uuid, alias_map, dc_rows)

    # 输出
    output = {
        "success": True,
        "data": report,
    }
    indent = 2 if args.pretty else None
    print(json.dumps(output, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
