"""chart query 字段映射脚本（MCP 无状态模式）。

本脚本为 MCP 环境设计，不依赖 opscli 命令行工具。
核心映射逻辑与 chart_map.py 完全一致，仅数据获取方式改为文件输入。
映射时优先使用服务端返回的字段语义信息，本地 CSV 仅作为兜底。

================================================================================
MCP 使用指南
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

【本地数据缺失时】
如脚本报错提示字段映射失败，先调用 MCP skills_upgrade Tool 更新本地索引：

    skills_upgrade(name="ops-dataset-query")

================================================================================

用法：
    # 仅映射查询结构（默认行为）
    python chart_map_mcp.py --input chart_result.json [--map-to verbose_name|field_name] [--pretty]

    # 映射查询结构 + 映射结果行数据列名
    python chart_map_mcp.py --input chart_result.json --map-results [--pretty]

    # 指定数据目录
    python chart_map_mcp.py --input chart_result.json --data-dir /path/to/ops-dataset-query/data

示例：
    python chart_map_mcp.py --input /tmp/chart_result.json --map-to field_name --pretty
    python chart_map_mcp.py --input /tmp/chart_result.json --map-results --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_data_loader import load_chart_data_from_file
from chart_map_core import map_chart_queries, map_query_results
from core import check_mapping_hit, discover_data_dir, load_local_index


def main() -> None:
    parser = argparse.ArgumentParser(description="chart query 字段映射工具（MCP 无状态模式）")
    parser.add_argument("--input", required=True, help="已保存的 chart query JSON 文件路径（由 MCP query_chart 获取）")
    parser.add_argument("--map-to", choices=["verbose_name", "field_name"], default="verbose_name",
                        help="映射目标字段，默认 verbose_name")
    parser.add_argument("--map-results", action="store_true",
                        help="将查询结果行数据中的 global_alias 列名也映射为可读名称")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    parser.add_argument("--skills-dir", help="指定 Skill 安装根目录（如 ~/.claude/skills）")
    parser.add_argument("--data-dir", help="直接指定数据目录路径（优先级高于自动发现）")
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

    # 从文件加载 chart 数据
    chart_data, _chart_uuid, raw_response = load_chart_data_from_file(args.input)

    if not chart_data:
        print(
            json.dumps(
                {"success": False, "error": "未获取到 chart 数据，请检查 --input 文件内容"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

    # 执行查询结构映射
    mapped = map_chart_queries(chart_data, dataset_index, field_index, map_to=args.map_to)

    # 检查映射命中情况（MCP 模式下不自动 upgrade，仅提示）
    if not check_mapping_hit(mapped):
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

    # 如果需要映射结果行数据的列名
    if args.map_results and raw_response is not None:
        for mq in mapped:
            dataset_alias = mq.get("_mapping", {}).get("dataset_alias", "")
            original = None
            for cd in chart_data:
                if isinstance(cd, dict):
                    q = cd.get("query", cd.get("payload", {}))
                    if isinstance(q, dict):
                        da = q.get("from", {}).get("alias", "") if "from" in q else dataset_alias
                        if da == dataset_alias and "result" in cd:
                            original = cd
                            break
            if original and "result" in original:
                rows = original["result"].get("data", [])
                if rows:
                    mq["mapped_results"] = map_query_results(
                        rows, mq, field_index, dataset_alias, map_to=args.map_to
                    )

    # 输出
    indent = 2 if args.pretty else None
    print(json.dumps(mapped, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
