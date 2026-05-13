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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_analyze_core import build_alias_map, generate_report
from chart_data_loader import load_chart_data, load_dc_data
from chart_map_core import map_chart_queries
from core import check_mapping_hit, discover_data_dir, load_local_index, try_upgrade


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
            if not args.no_auto_upgrade and try_upgrade(caller="chart_analyze"):
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
