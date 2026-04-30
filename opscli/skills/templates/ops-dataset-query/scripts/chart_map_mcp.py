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

    skills_upgrade(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")

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
from core import discover_data_dir, load_local_index, resolve_dataset_alias, resolve_field_alias


def _extract_dataset_alias_from_expr(expr: str) -> str:
    """从字段表达式中提取数据集别名。

    例如 "ds_d35ac6f3910c.dept_name" → "ds_d35ac6f3910c"
    """
    if "." in expr:
        return expr.split(".")[0].strip()
    return ""


def _extract_server_select_mapping_index(item: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """从服务端返回中提取 select 字段映射索引。"""
    by_alias: dict[str, dict] = {}
    by_expr: dict[str, dict] = {}
    for mapping in item.get("field_mappings", []) or []:
        if not isinstance(mapping, dict):
            continue
        if mapping.get("source") != "select":
            continue
        query_alias = str(mapping.get("query_alias") or mapping.get("alias") or "").strip()
        query_expr = str(mapping.get("query_expr") or mapping.get("expr") or "").strip()
        if query_alias:
            by_alias[query_alias] = mapping
        if query_expr:
            by_expr[query_expr] = mapping
    return by_alias, by_expr


def _build_field_info(
    dataset_alias: str,
    query_alias: str,
    server_mapping: dict | None,
    local_field_info: dict | None,
) -> dict:
    """合并服务端 field_mappings 与本地 CSV 字段信息。"""
    field_info = dict(local_field_info or {})
    if server_mapping:
        for key in ("field_name", "verbose_name", "global_alias", "field_type", "origin_name"):
            value = server_mapping.get(key)
            if value:
                field_info[key] = value
    field_info.setdefault("query_alias", query_alias)
    field_info.setdefault("dataset_alias", dataset_alias)
    return field_info


def map_chart_queries(chart_data: list[dict], dataset_index: dict, field_index: dict, *, map_to: str = "verbose_name") -> list[dict]:
    """为 chart query 的每个字段添加映射信息。

    支持两种数据格式：
    1. 标准 chart query 格式：item.query.from.alias + item.query.select
    2. chart run 格式：item.payload.query.select（无 from，从 expr 中提取 dataset_alias）

    Args:
        chart_data: 后端返回的 chart query 数组
        dataset_index: 数据集索引
        field_index: 字段索引
        map_to: 映射目标字段，"verbose_name" 或 "field_name"

    Returns:
        添加了 _mapping 信息的 chart query 数组
    """
    result = []
    for item in chart_data:
        query = item.get("query", {}) or item.get("payload", {}).get("query", {})
        dataset_alias = query.get("from", {}).get("alias", "") if isinstance(query.get("from"), dict) else ""
        select_items = query.get("select", [])

        if not dataset_alias and select_items:
            first_expr = select_items[0].get("expr", "")
            dataset_alias = _extract_dataset_alias_from_expr(first_expr)

        dataset_info = resolve_dataset_alias(dataset_index, dataset_alias)
        server_by_alias, server_by_expr = _extract_server_select_mapping_index(item)

        field_mappings = []
        for sel in select_items:
            g_alias = sel.get("alias", "")
            expr = sel.get("expr", "")
            server_mapping = server_by_alias.get(g_alias) or server_by_expr.get(expr)
            local_lookup_alias = str((server_mapping or {}).get("global_alias") or g_alias)
            local_field_info = resolve_field_alias(field_index, dataset_alias, local_lookup_alias)
            field_info = _build_field_info(dataset_alias, g_alias, server_mapping, local_field_info)
            mapped_name = field_info.get(map_to, g_alias) if field_info else g_alias
            mapping = {
                "alias": g_alias,
                "expr": expr,
                "mapped_name": mapped_name,
                "field_info": field_info or {},
                "query_alias": g_alias,
                "global_alias": field_info.get("global_alias") if field_info else None,
                "origin_name": field_info.get("origin_name") if field_info else None,
                "aggregation": sel.get("aggregation") or (server_mapping or {}).get("aggregation"),
            }
            field_mappings.append(mapping)

        result.append({
            **item,
            "_mapping": {
                "dataset_alias": dataset_alias,
                "dataset_info": dataset_info or {},
                "field_mappings": field_mappings,
            },
        })

    return result


def map_query_results(results: list[dict], mapped_query: dict, field_index: dict, dataset_alias: str, *, map_to: str = "verbose_name") -> list[dict]:
    """将查询结果中的 global_alias 列名替换为可读名称。

    Args:
        results: chart run 返回的 rows 数组
        field_index: 字段索引
        dataset_alias: 数据集别名
        map_to: 映射目标字段

    Returns:
        列名已替换的结果数组
    """
    alias_map: dict[str, str] = {}
    for mapping in mapped_query.get("_mapping", {}).get("field_mappings", []):
        if not isinstance(mapping, dict):
            continue
        alias = str(mapping.get("alias", "")).strip()
        mapped_name = str(mapping.get("mapped_name", "")).strip()
        if alias and mapped_name and mapped_name != alias:
            alias_map[alias] = mapped_name

    mapped_results = []
    for row in results:
        mapped_row = dict(row)
        for key in list(mapped_row.keys()):
            if key.startswith("_"):
                continue
            if key in alias_map:
                mapped_row[alias_map[key]] = mapped_row.pop(key)
                continue
            field_info = resolve_field_alias(field_index, dataset_alias, key)
            if field_info:
                new_key = field_info.get(map_to, key)
                if new_key and new_key != key:
                    mapped_row[new_key] = mapped_row.pop(key)
        mapped_results.append(mapped_row)
    return mapped_results


def _check_mapping_hit(mapped: list[dict]) -> bool:
    """检查映射结果中是否有任意字段命中了本地索引。"""
    for item in mapped:
        for fm in item.get("_mapping", {}).get("field_mappings", []):
            fi = fm.get("field_info", {})
            if fi and fi.get("field_name"):
                return True
    return False


def _load_chart_data_from_file(input_path: str) -> tuple[list[dict], dict | None]:
    """从文件加载 chart 数据。

    Returns:
        (chart_data, raw_response)
        - chart_data: queries 列表
        - raw_response: 原始完整响应（含 result），用于 map-results
    """
    input_path_obj = Path(input_path)
    with input_path_obj.open("r", encoding="utf-8") as f:
        content = json.load(f)

    chart_data: list[dict] = []
    raw_response: dict | None = None

    if isinstance(content, dict) and "data" in content:
        data = content["data"]
        if isinstance(data, dict) and "queries" in data:
            chart_data = data["queries"]
            raw_response = data
        elif isinstance(data, dict) and "result" in data:
            chart_data = [data]
            raw_response = data
    elif isinstance(content, dict) and "queries" in content:
        chart_data = content["queries"]
        raw_response = content
    elif isinstance(content, list):
        chart_data = content

    return chart_data, raw_response


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
    chart_data, raw_response = _load_chart_data_from_file(args.input)

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
    if not _check_mapping_hit(mapped):
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
