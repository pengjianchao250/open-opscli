"""chart query 字段映射核心逻辑 — CLI / MCP 共用。

提供字段别名映射的纯函数，不涉及数据获取、命令行参数解析、
自动升级兜底等运行模式差异化逻辑。
"""

from __future__ import annotations

from core import resolve_dataset_alias, resolve_field_alias


def extract_dataset_alias_from_expr(expr: str) -> str:
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


def map_chart_queries(
    chart_data: list[dict],
    dataset_index: dict,
    field_index: dict,
    *,
    map_to: str = "verbose_name",
) -> list[dict]:
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
        # 兼容两种格式：标准 query 或 chart run 的 payload.query
        query = item.get("query", {}) or item.get("payload", {}).get("query", {})
        dataset_alias = query.get("from", {}).get("alias", "") if isinstance(query.get("from"), dict) else ""
        select_items = query.get("select", [])

        # 如果没有 from.alias，尝试从第一个 select 的 expr 中提取
        if not dataset_alias and select_items:
            first_expr = select_items[0].get("expr", "")
            dataset_alias = extract_dataset_alias_from_expr(first_expr)

        # 数据集映射
        dataset_info = resolve_dataset_alias(dataset_index, dataset_alias)
        server_by_alias, server_by_expr = _extract_server_select_mapping_index(item)

        # 字段映射
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


def map_query_results(
    results: list[dict],
    mapped_query: dict,
    field_index: dict,
    dataset_alias: str,
    *,
    map_to: str = "verbose_name",
) -> list[dict]:
    """将查询结果中的 global_alias 列名替换为可读名称。

    Args:
        results: chart run 返回的 rows 数组
        mapped_query: 含 _mapping 的映射结果
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
            if key.startswith("_"):  # 保留内部字段
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
