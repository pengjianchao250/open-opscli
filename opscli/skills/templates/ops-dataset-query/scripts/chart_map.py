"""chart query 字段映射脚本（CLI 模式）。

通过 chart_uuid 获取查询结构后，优先使用服务端返回的字段语义信息，
并在必要时回退到本地 CSV 资源进行字段别名映射，
将 global_alias / query_alias 转换为可读的 verbose_name / field_name。

用法：
    # 仅映射查询结构（默认行为）
    python chart_map.py --uuid <chart_uuid> [--map-to verbose_name|field_name] [--pretty]
    python chart_map.py --input chart_result.json [--map-to verbose_name|field_name] [--pretty]

    # 映射查询结构 + 执行查询 + 映射结果行数据列名
    python chart_map.py --uuid <chart_uuid> --run --map-results [--pretty]

    # 对已保存的 chart run 结果进行映射
    python chart_map.py --input chart_result.json --map-results [--pretty]

示例：
    python chart_map.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --pretty
    python chart_map.py --uuid 32f660fd-f62a-45c4-a443-e21f2edb0779 --run --map-results --pretty
    python chart_map.py --input /tmp/chart_result.json --map-to field_name --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_data_loader import load_chart_data
from chart_map_core import map_chart_queries, map_query_results
from core import check_mapping_hit, discover_data_dir, load_local_index, try_upgrade


def main() -> None:
    parser = argparse.ArgumentParser(description="chart query 字段映射工具")
    parser.add_argument("--uuid", help="图表 UUID，直接调用 opscli 获取")
    parser.add_argument("--input", help="已保存的 chart query JSON 文件路径")
    parser.add_argument("--map-to", choices=["verbose_name", "field_name"], default="verbose_name",
                        help="映射目标字段，默认 verbose_name")
    parser.add_argument("--run", action="store_true",
                        help="通过 opscli 执行图表查询（需配合 --uuid）")
    parser.add_argument("--map-results", action="store_true",
                        help="将查询结果行数据中的 global_alias 列名也映射为可读名称")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    parser.add_argument("--skills-dir", help="指定 Skill 安装根目录（如 ~/.claude/skills）")
    parser.add_argument("--data-dir", help="直接指定数据目录路径（优先级高于自动发现）")
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
                caller="chart_map",
            ):
                discovered = discover_data_dir(skills_dir=args.skills_dir)
            if discovered is None:
                print(
                    json.dumps(
                        {
                            "success": False,
                            "error": "未找到 ops-dataset-query 数据目录。"
                                     "请先执行 opscli skills install ops-dataset-query，"
                                     "或通过 --skills-dir / --data-dir 显式指定。"
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )
                raise SystemExit(1)
        data_dir = discovered

    # 加载本地索引
    dataset_index, field_index = load_local_index(data_dir)

    # 获取 chart query 数据（通过 uuid 调用 opscli 或从文件读取）
    chart_data, _chart_uuid, _merged = load_chart_data(args.uuid, args.input)

    if not chart_data:
        print(
            json.dumps(
                {"success": False, "error": "未获取到 chart 数据"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

    # 执行查询结构映射
    mapped = map_chart_queries(chart_data, dataset_index, field_index, map_to=args.map_to)

    # 自动升级兜底：如果所有字段都没映射成功，尝试 upgrade 后重试
    if not args.no_auto_upgrade and not check_mapping_hit(mapped):
        if try_upgrade(data_dir, caller="chart_map"):
            # 重新加载索引并重新映射
            dataset_index, field_index = load_local_index(data_dir)
            mapped = map_chart_queries(chart_data, dataset_index, field_index, map_to=args.map_to)

    # 如果需要映射结果行数据的列名
    if args.map_results:
        for mq in mapped:
            dataset_alias = mq.get("_mapping", {}).get("dataset_alias", "")
            # 查找对应的原始 query（含 result 数据）
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
