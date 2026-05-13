"""图表数据 Excel 导出脚本（MCP 无状态模式）。

从 MCP query_chart 获取并保存的 chart run 结果中提取明细、小计、总计数据，
按透视表格式写入 Excel 文件（.xlsx）。
自动将 global_alias 列名映射为可读的 verbose_name。

================================================================================
MCP 使用指南
================================================================================

【前置要求】
1. 先检查 session：auth_is_authenticated(session_id="xxx")

【获取图表数据】
通过 MCP query_chart Tool 获取并执行查询：

    query_chart(
        chart_uuid="4NQ5f66sU9",
        run=True,
        session_id="860b0636485b5188a2b9b4ed5210e736"
    )

将返回的 JSON 保存到文件（如 /tmp/chart_result.json），然后通过 --input 传入本脚本。

【本地数据缺失时】
如字段映射失败，调用 MCP skills_upgrade Tool 更新本地索引：

    skills_upgrade(name="ops-dataset-query")

================================================================================

用法：
    python excel_export_mcp.py --input /tmp/chart_result.json --output /tmp/output.xlsx
    python excel_export_mcp.py --input /tmp/chart_result.json --output /tmp/output.xlsx --sheet-name 销售数据

前置依赖：
    pip install openpyxl

格式规范：
    - 表头：蓝色背景（4472C4）白色粗体字，冻结首行
    - 明细行：数值列千分位格式（#,##0.00），百分比列 0.00% 格式
    - 小计行：灰色背景（D9E2F3），粗体字
    - 总计行：深蓝背景（4472C4）白色粗体字
    - 负值：红色字体（FF0000）标注亏损
    - 列宽：根据内容自动调整（最大 50 字符）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_data_loader import load_chart_data_from_file
from chart_map_core import map_chart_queries
from core import check_mapping_hit, discover_data_dir, load_local_index
from excel_export_core import export_to_excel


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """脚本入口：解析参数，加载数据，执行 Excel 导出。"""
    parser = argparse.ArgumentParser(description="图表数据 Excel 导出工具（MCP 无状态模式）")
    parser.add_argument("--input", required=True, help="已保存的 chart run JSON 文件路径（由 MCP query_chart 获取）")
    parser.add_argument("--output", default="/tmp/output.xlsx", help="输出 Excel 文件路径（默认 /tmp/output.xlsx）")
    parser.add_argument("--sheet-name", default="数据透视表", help="Sheet 名称（默认：数据透视表）")
    parser.add_argument("--skills-dir", help="指定 Skill 安装根目录")
    parser.add_argument("--data-dir", help="直接指定数据目录路径（最高优先级）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    # 1. 确定本地数据目录
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        discovered = discover_data_dir(skills_dir=args.skills_dir)
        if discovered is None:
            err = {
                "success": False,
                "error": "未找到 ops-dataset-query 数据目录。请先通过 MCP skills_upgrade 更新数据。",
                "mcp_hint": "调用 skills_upgrade(name='ops-dataset-query') 后重试",
            }
            print(json.dumps(err, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(1)
        data_dir = discovered

    # 2. 加载本地字段索引
    dataset_index, field_index = load_local_index(data_dir)

    # 3. 加载图表查询数据（仅从文件）
    queries, chart_uuid, _merged = load_chart_data_from_file(args.input)

    if not queries:
        err = {"success": False, "error": "未获取到任何 query 数据，请检查 --input 参数"}
        print(json.dumps(err, ensure_ascii=False, indent=2 if args.pretty else None))
        raise SystemExit(1)

    # 4. 字段别名映射
    mapped_queries = map_chart_queries(queries, dataset_index, field_index)

    # 字段映射全部失败时提示
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

    # 5. 导出 Excel
    result = export_to_excel(
        queries=queries,
        mapped_queries=mapped_queries,
        output_path=args.output,
        sheet_name=args.sheet_name,
    )

    if chart_uuid:
        result["chart_uuid"] = chart_uuid

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
