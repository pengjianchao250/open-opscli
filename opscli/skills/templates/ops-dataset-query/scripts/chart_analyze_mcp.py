"""图表数据异常检测脚本（MCP 无状态模式）。

本脚本为 MCP 环境设计，不依赖 opscli 命令行工具。
核心分析逻辑与 chart_analyze.py 完全一致，仅数据获取方式改为文件输入。

================================================================================
MCP 使用指南（供 AI Agent 参考）
================================================================================

【前置要求】
1. 先检查 session：auth_is_authenticated(session_id="xxx")
2. 如 session 无效，重新 Device Flow 授权

【获取图表数据】
通过 MCP query_chart Tool 获取图表结构并执行查询：

    query_chart(
        chart_uuid="4NQ5f66sU9",
        run=True,
        session_id="860b0636485b5188a2b9b4ed5210e736"
    )

将返回的 JSON 保存到文件（如 /tmp/chart_result.json），然后通过 --input 传入本脚本。

【获取环比数据（可选）】
如需趋势异常检测（profit_drop / revenue_cliff / ad_roi_decline / zero_orders），
通过 MCP query_build_and_run Tool 执行 dataComparison 查询：

    query_build_and_run(
        table_id=1104,
        dimensions=["dept_name"],
        metrics=["price:sum:total_price", "order_qty:sum:total_qty"],
        where_conditions=["date_id|>=|\"2026-04-01\""],
        data_comparison="date_id,2026-03-01,2026-03-22",
        session_id="860b0636485b5188a2b9b4ed5210e736"
    )

将返回的 JSON 保存到文件（如 /tmp/dc_result.json），然后通过 --dc-input 传入本脚本。

【本地数据缺失时】
如脚本报错提示字段映射失败，先调用 MCP skills_upgrade Tool 更新本地索引：

    skills_upgrade(name="ops-dataset-query")

================================================================================

用法：
    # 分析已保存的 chart run 结果（由 MCP query_chart 获取）
    python chart_analyze_mcp.py --input /tmp/chart_result.json [--pretty]

    # 附带 dataComparison 环比数据（由 MCP query_build_and_run 获取）
    python chart_analyze_mcp.py --input /tmp/chart_result.json --dc-input /tmp/dc_result.json [--pretty]

    # 指定数据目录（当自动发现失败时）
    python chart_analyze_mcp.py --input /tmp/chart_result.json --data-dir /path/to/ops-dataset-query/data

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_analyze_core import build_alias_map, generate_report
from chart_data_loader import load_chart_data_from_file, load_dc_data
from chart_map_core import map_chart_queries
from core import check_mapping_hit, discover_data_dir, load_local_index


# ---------------------------------------------------------------------------
# MCP 模式入口
# ---------------------------------------------------------------------------


def main() -> None:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="图表数据异常检测工具（MCP 无状态模式）")
    parser.add_argument("--input", required=True, help="已保存的 chart run JSON 文件路径（由 MCP query_chart 获取）")
    parser.add_argument("--dc-input", help="已保存的 dataComparison 环比结果 JSON 文件路径（由 MCP query_build_and_run 获取）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    parser.add_argument("--skills-dir", help="指定 Skill 安装根目录")
    parser.add_argument("--data-dir", help="直接指定数据目录路径")
    args = parser.parse_args()

    # 确定数据目录
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        discovered = discover_data_dir(skills_dir=args.skills_dir)
        if discovered is None:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "未找到 ops-dataset-query 数据目录。"
                                 "请先通过 MCP skills_upgrade 更新数据，"
                                 "或通过 --skills-dir / --data-dir 显式指定。",
                        "mcp_hint": "调用 skills_upgrade(name='ops-dataset-query') 后重试",
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)
        data_dir = discovered

    # 加载本地索引
    dataset_index, field_index = load_local_index(data_dir)

    # 加载图表数据（仅从文件）
    queries, chart_uuid, _merged = load_chart_data_from_file(args.input)

    if not queries:
        print(
            json.dumps({"success": False, "error": "未获取到图表数据，请检查 --input 文件内容"}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1)

    # 执行字段映射（添加 _mapping 信息）
    mapped_queries = map_chart_queries(queries, dataset_index, field_index)

    # 恢复 result 数据（map_chart_queries 只映射 query 结构，不包含 result）
    for i, mq in enumerate(mapped_queries):
        if i < len(queries) and "result" in queries[i]:
            mq["result"] = queries[i]["result"]

    # 检查映射命中情况（MCP 模式下不自动 upgrade，仅提示）
    if not check_mapping_hit(mapped_queries):
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "本地字段映射未命中任何字段，可能本地数据已过期。",
                    "mcp_hint": "调用 skills_upgrade(name='ops-dataset-query', force=True) 后重试",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

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
