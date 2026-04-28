"""查询 Payload 构造脚本（MCP 无状态模式）。

本脚本为 MCP 环境设计，不依赖 opscli 命令行工具。
将简化参数转换为标准 query payload JSON 文件，供 MCP query_run Tool 使用。

================================================================================
MCP 使用指南
================================================================================

【前置要求】
1. 先检查 session：auth_is_authenticated(session_id="xxx")
2. 如 session 无效，重新 Device Flow 授权

【使用流程】
1. 先用本脚本构造 payload JSON 文件：
   python query_mcp.py build --dataset sales_order_d \
       --dimension date_id --metric "order_cost:sum:total_cost" \
       --where "date_id|>=|\"2024-01-01\"" \
       --output /tmp/query.json

2. 再通过 MCP query_run Tool 执行查询：
   query_run(
       payload_path="/tmp/query.json",
       session_id="860b0636485b5188a2b9b4ed5210e736"
   )

【dataComparison 示例】
   python query_mcp.py build --dataset sales_order_d \
       --dimension dept_name --metric "price:sum:total_price" \
       --where "date_id|>=|\"2026-04-01\"" \
       --data-comparison "date_id,2026-03-01,2026-03-22" \
       --output /tmp/query.json

【本地字段验证】
   python query_mcp.py metadata --dataset sales_order_d

================================================================================

子命令：
    build       构造 query payload 并写入 JSON 文件
    metadata    查看数据集 metadata（本地索引，无需认证）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_map import discover_data_dir, load_local_index


class PayloadError(Exception):
    """Payload 构造错误。"""


# ---------------------------------------------------------------------------
# 字段解析
# ---------------------------------------------------------------------------


def _resolve_field(
    fields: list[dict],
    identifier: str,
    *,
    field_type: str | None = None,
) -> dict:
    """通过本地索引解析字段标识。

    匹配优先级：global_alias > field_name > verbose_name

    Args:
        fields: 本地字段索引列表
        identifier: 字段标识（field_name / global_alias / verbose_name）
        field_type: 可选，限定 field_type 类型（dimension / metric）

    Returns:
        命中的字段记录

    Raises:
        PayloadError: 字段不存在或存在歧义
    """
    normalized = identifier.strip().lower()

    global_alias_matches: list[dict] = []
    field_name_matches: list[dict] = []
    verbose_name_matches: list[dict] = []

    for item in fields:
        current_type = str(item.get("field_type") or "").strip().lower()
        if field_type and current_type and current_type != field_type.lower():
            continue

        global_alias = str(item.get("global_alias") or "").strip().lower()
        field_name = str(item.get("field_name") or "").strip().lower()
        verbose_name = str(item.get("verbose_name") or "").strip().lower()

        if global_alias and global_alias == normalized:
            global_alias_matches.append(item)
        if field_name and field_name == normalized:
            field_name_matches.append(item)
        if verbose_name and verbose_name == normalized:
            verbose_name_matches.append(item)

    for key, matches in (
        ("global_alias", global_alias_matches),
        ("field_name", field_name_matches),
        ("verbose_name", verbose_name_matches),
    ):
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            if key == "field_name" or all(
                m.get("field_name") == matches[0].get("field_name") for m in matches
            ):
                return _pick_primary_field(matches, identifier)
            raise PayloadError(
                f"字段标识存在歧义（{key} 命中多条）: {identifier}，"
                f"请改用 global_alias 或 field_name"
            )

    raise PayloadError(f"字段不存在于当前数据集 metadata 中: {identifier}")


def _pick_primary_field(matches: list[dict], identifier: str) -> dict:
    """当同一个 field_name 命中多条记录时，优先选取原始字段。"""
    def _score(item: dict) -> tuple:
        alias = str(item.get("global_alias") or "")
        vname = str(item.get("verbose_name") or "")
        has_derived_suffix = 1 if re.search(r"_\d+$", alias) else 0
        return (has_derived_suffix, len(vname), len(alias))

    sorted_matches = sorted(matches, key=_score)
    return sorted_matches[0]


def _resolve_output_alias(alias: str | None, field: dict) -> str:
    """解析输出别名。用户未指定时回退到 global_alias，其次 field_name。"""
    if alias:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", alias):
            raise PayloadError(
                f"select alias 仅支持英文、数字和下划线，且不能以数字开头: {alias}"
            )
        return alias

    fallback = (
        str(field.get("global_alias") or "").strip()
        or str(field.get("field_name") or "").strip()
    )
    if not fallback:
        raise PayloadError("字段缺少可用 alias，请检查 query metadata")
    return fallback


# ---------------------------------------------------------------------------
# Dimension / Metric / Where / OrderBy 解析
# ---------------------------------------------------------------------------


def _parse_dimension_spec(spec: str) -> tuple[str, str | None]:
    """解析 dimension 定义：field_name|global_alias|verbose_name[:alias]

    Returns:
        (field_identifier, alias)
    """
    if ":" in spec:
        field_part, alias = spec.rsplit(":", 1)
        return field_part.strip(), alias.strip()
    return spec.strip(), None


def _parse_metric_spec(spec: str) -> tuple[str, str | None, str | None]:
    """解析 metric 定义：field_name|global_alias|verbose_name[:aggregation[:alias]]

    支持三种格式：
    - field_name                  公式字段（has_formula_config=1），由 build_payload 使用 summary_expression
    - field_name:aggregation      普通聚合字段
    - field_name:aggregation:alias  聚合字段 + 自定义别名
    - field_name::alias           公式字段 + 自定义别名（aggregation 留空）

    Returns:
        (field_identifier, aggregation, alias)
    """
    parts = spec.split(":")
    # 仅有字段名：公式字段，aggregation=None
    if len(parts) == 1 and parts[0].strip():
        return parts[0].strip(), None, None
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip() or None, None
    if len(parts) == 3:
        agg = parts[1].strip() or None
        return parts[0].strip(), agg, parts[2].strip() or None
    raise PayloadError(f"无效的 metric 定义: {spec}，格式: field_name[:aggregation[:alias]]")


# 操作符标准化映射：将符号转换为服务端语义操作符
_WHERE_OP_MAP: dict[str, str] = {
    ">=": "gte",
    "<=": "lte",
    ">": "gt",
    "<": "lt",
    "=": "eq",
    "==": "eq",
    "!=": "neq",
    "<>": "neq",
}


def _parse_where_condition(raw: str, *, dataset_alias: str) -> dict:
    """解析 where 条件：field|operator|value_json。

    操作符支持两种写法：
    - 语义操作符（服务端原生）：between, eq, neq, gt, gte, lt, lte, in
    - 符号操作符（自动转换）：>=, <=, >, <, =, ==, !=, <>
    """
    parts = raw.split("|", 2)
    if len(parts) != 3:
        raise PayloadError(f"无效的 --where 定义: {raw}，格式: field|operator|value_json")
    field, operator, value_raw = (item.strip() for item in parts)
    # 将符号操作符标准化为服务端语义操作符
    operator = _WHERE_OP_MAP.get(operator, operator)
    expr = field if "." in field else f"{dataset_alias}.{field}"
    try:
        value = json.loads(value_raw)
    except Exception:
        value = value_raw
    return {"field": expr, "operator": operator, "value": value}


def _resolve_metric_expr(dataset_alias: str, field: dict) -> str:
    """指标字段优先使用汇总公式表达式，否则回退到原始字段。

    公式字段（has_formula_config=1）的 summary_expression 已包含完整聚合逻辑
    （如 ROUND(SUM(gross_profit)/SUM(price), 4)），不应再附加额外聚合函数。
    """
    summary_expression = str(field.get("summary_expression") or "").strip()
    if summary_expression:
        return summary_expression
    return f"{dataset_alias}.{field['field_name']}"


def _build_order_by(order_by: list[str], alias_map: dict[str, str]) -> list[dict]:
    """构建 orderBy 列表。"""
    result = []
    for spec in order_by:
        if ":" in spec:
            expr, direction = spec.rsplit(":", 1)
            expr = expr.strip()
            direction = direction.strip().lower()
            if direction not in ("asc", "desc"):
                expr = spec.strip()
                direction = "asc"
        else:
            expr = spec.strip()
            direction = "asc"

        # 尝试从 alias_map 解析
        resolved = alias_map.get(expr, expr)
        result.append({"expr": resolved, "direction": direction})
    return result


def _build_data_comparison(raw: str, *, dataset_alias: str) -> dict:
    """解析 dataComparison 定义：field,start_date,end_date"""
    parts = [item.strip() for item in raw.split(",")]
    if len(parts) != 3 or not all(parts):
        raise PayloadError(
            "--data-comparison 格式: field,start_date,end_date"
            "（例: date_id,2026-03-01,2026-03-22）"
        )
    field, start_date, end_date = parts
    if "." not in field:
        field = f"{dataset_alias}.{field}"
    return {
        "switch": True,
        "field": field,
        "startDate": start_date,
        "endDate": end_date,
    }


# ---------------------------------------------------------------------------
# Payload 构建核心
# ---------------------------------------------------------------------------


def build_payload(
    *,
    dataset_alias: str,
    table_id: int,
    fields: list[dict],
    dimensions: list[str] | None,
    metrics: list[str] | None,
    where_conditions: list[str] | None,
    where_json: str | None,
    where_file: str | None,
    order_by: list[str] | None,
    limit: int,
    offset: int,
    data_comparison: str | None,
) -> dict:
    """构造标准 query payload JSON。

    Args:
        dataset_alias: 数据集别名
        table_id: 数据集表 ID
        fields: 数据集字段列表（本地索引）
        dimensions: dimension 定义列表
        metrics: metric 定义列表
        where_conditions: where 条件列表
        where_json: where JSON 字符串
        where_file: where JSON 文件路径
        order_by: orderBy 定义列表
        limit: 返回行数上限
        offset: 偏移量
        data_comparison: dataComparison 定义字符串

    Returns:
        标准 query payload 字典
    """
    select_items: list[dict] = []
    group_by: list[str] = []

    # 1. 解析 dimension
    for spec in dimensions or []:
        field_id, alias = _parse_dimension_spec(spec)
        resolved = _resolve_field(fields, field_id, field_type="dimension")
        output_alias = _resolve_output_alias(alias, resolved)
        select_items.append({
            "expr": f"{dataset_alias}.{resolved['field_name']}",
            "alias": output_alias,
        })
        group_by.append(output_alias)

    # 2. 解析 metric
    for spec in metrics or []:
        field_id, aggregation, alias = _parse_metric_spec(spec)
        resolved = _resolve_field(fields, field_id, field_type="metric")
        output_alias = _resolve_output_alias(alias, resolved)
        # 公式字段优先使用 summary_expression，否则回退到原始字段表达式
        metric_expr = _resolve_metric_expr(dataset_alias, resolved)
        select_row: dict[str, Any] = {"expr": metric_expr, "alias": output_alias}
        # 仅当字段无公式（expr 为原始字段）且调用方指定了 aggregation 时才附加聚合函数
        if aggregation and metric_expr == f"{dataset_alias}.{resolved['field_name']}":
            select_row["aggregation"] = aggregation
        select_items.append(select_row)

    # 3. 构建 alias 映射
    alias_map: dict[str, str] = {}
    for item in select_items:
        alias_map[item["alias"]] = item["alias"]
        if "." in item["expr"]:
            alias_map[item["expr"].rsplit(".", 1)[-1]] = item["alias"]

    # 4. 组装 payload
    payload: dict[str, Any] = {
        "tableId": table_id,
        "query": {
            "select": select_items,
            "groupBy": group_by,
            "orderBy": _build_order_by(order_by or [], alias_map=alias_map),
            "limit": limit,
            "offset": offset,
        },
    }

    # 5. Where 条件
    where_payload = _load_where_clause(
        where_conditions=where_conditions or [],
        where_json=where_json,
        where_file=where_file,
        dataset_alias=dataset_alias,
    )
    if where_payload is not None:
        payload["query"]["where"] = where_payload

    # 6. dataComparison
    if data_comparison:
        payload["dataComparison"] = _build_data_comparison(
            data_comparison, dataset_alias=dataset_alias
        )

    return payload


def _load_where_clause(
    where_conditions: list[str],
    where_json: str | None,
    where_file: str | None,
    dataset_alias: str,
) -> dict | None:
    """加载 where 条件。

    优先级：where_file > where_json > where_conditions
    """
    if where_file:
        path = Path(where_file)
        if not path.exists():
            raise PayloadError(f"where 文件不存在: {where_file}")
        return json.loads(path.read_text(encoding="utf-8"))

    if where_json:
        return json.loads(where_json)

    if where_conditions:
        conditions = []
        for raw in where_conditions:
            conditions.append(_parse_where_condition(raw, dataset_alias=dataset_alias))
        return {"logic": "AND", "conditions": conditions}

    return None


# ---------------------------------------------------------------------------
# Metadata 查询（本地索引）
# ---------------------------------------------------------------------------


def get_dataset_metadata(dataset_index: dict, field_index: dict, dataset_alias: str) -> dict:
    """获取数据集 metadata（本地索引）。"""
    dataset = dataset_index.get(dataset_alias)
    if not dataset:
        raise PayloadError(f"数据集不存在: {dataset_alias}")

    fields = []
    for (ds, ga), info in field_index.items():
        if ds == dataset_alias:
            fields.append(info)

    return {
        "dataset_alias": dataset_alias,
        "table_id": dataset.get("table_id"),
        "dataset_name": dataset.get("dataset_name"),
        "fields": fields,
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="查询 Payload 构造工具（MCP 无状态模式）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build 子命令
    build_parser = subparsers.add_parser("build", help="构造 query payload 并写入 JSON 文件")
    build_parser.add_argument("--dataset", help="dataset_alias")
    build_parser.add_argument("--table-id", type=int, help="table_id")
    build_parser.add_argument(
        "--dimension",
        action="append",
        help="维度定义：field_name|global_alias|verbose_name[:alias]",
    )
    build_parser.add_argument(
        "--metric",
        action="append",
        help="指标定义：field_name|global_alias|verbose_name:aggregation[:alias]",
    )
    build_parser.add_argument("--where", action="append", help="筛选条件：field|operator|value_json，可重复")
    build_parser.add_argument("--where-json", help="where JSON 字符串")
    build_parser.add_argument("--where-file", help="where JSON 文件路径")
    build_parser.add_argument("--order-by", action="append", help="排序定义：expr[:asc|desc]")
    build_parser.add_argument("--limit", type=int, default=20, help="limit，默认 20")
    build_parser.add_argument("--offset", type=int, default=0, help="offset，默认 0")
    build_parser.add_argument("--data-comparison", help="数据对比：field,start_date,end_date")
    build_parser.add_argument("--output", default="/tmp/query_payload.json", help="输出 JSON 文件路径（默认 /tmp/query_payload.json）")
    build_parser.add_argument("--skills-dir", help="指定 Skill 安装根目录")
    build_parser.add_argument("--data-dir", help="直接指定数据目录路径")
    build_parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")

    # metadata 子命令
    meta_parser = subparsers.add_parser("metadata", help="查看数据集 metadata（本地索引）")
    meta_parser.add_argument("--dataset", required=True, help="dataset_alias")
    meta_parser.add_argument("--skills-dir", help="指定 Skill 安装根目录")
    meta_parser.add_argument("--data-dir", help="直接指定数据目录路径")
    meta_parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")

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
                        "error": "未找到 ops-dataset-query 数据目录。",
                        "mcp_hint": "调用 skills_upgrade(name='ops-dataset-query') 后重试",
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)
        data_dir = discovered

    dataset_index, field_index = load_local_index(data_dir)

    try:
        if args.command == "metadata":
            metadata = get_dataset_metadata(dataset_index, field_index, args.dataset)
            result = {"success": True, "data": metadata}
        else:  # build
            # 确定 dataset
            if args.dataset:
                dataset_alias = args.dataset
                dataset_info = dataset_index.get(dataset_alias)
                if not dataset_info:
                    raise PayloadError(f"数据集不存在: {dataset_alias}")
                table_id = int(dataset_info.get("table_id", 0))
            elif args.table_id is not None:
                # 通过 table_id 反向查找 dataset_alias
                table_id = args.table_id
                dataset_alias = None
                for alias, info in dataset_index.items():
                    if int(info.get("table_id", 0)) == table_id:
                        dataset_alias = alias
                        break
                if not dataset_alias:
                    raise PayloadError(f"未找到 table_id={table_id} 对应的数据集")
            else:
                raise PayloadError("必须提供 --dataset 或 --table-id 之一")

            # 获取该数据集的所有字段
            fields = []
            for (ds, ga), info in field_index.items():
                if ds == dataset_alias:
                    fields.append(info)

            payload = build_payload(
                dataset_alias=dataset_alias,
                table_id=table_id,
                fields=fields,
                dimensions=args.dimension,
                metrics=args.metric,
                where_conditions=args.where,
                where_json=args.where_json,
                where_file=args.where_file,
                order_by=args.order_by,
                limit=args.limit,
                offset=args.offset,
                data_comparison=args.data_comparison,
            )

            # 写入文件
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            indent = 2 if args.pretty else None
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=indent),
                encoding="utf-8",
            )

            result = {
                "success": True,
                "data": {
                    "output": str(output_path.resolve()),
                    "payload": payload,
                },
            }
    except PayloadError as exc:
        result = {"success": False, "error": str(exc)}
    except Exception as exc:
        result = {"success": False, "error": f"构造失败: {exc}"}

    indent = 2 if getattr(args, "pretty", False) else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))

    if not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
