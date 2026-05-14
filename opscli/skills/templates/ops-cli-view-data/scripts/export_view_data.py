#!/usr/bin/env python3
"""Analysis View 图表数据导出。

通过 ops-dataset-query 获取 chart query 结构、执行注入参数后的 payload，
再复用 ops-dataset-query 的 Excel 导出脚本生成 .xlsx。
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_error(message: str, *, code: str = "VIEW_DATA_ERROR") -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message}}


def _load_json_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ValueError(f"JSON 文件不存在: {file_path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象: {file_path}")
    return payload


def _run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    result = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(message)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"命令未输出合法 JSON: {' '.join(command)}") from exc
    if isinstance(payload, dict) and payload.get("success") is False:
        error = payload.get("error")
        if isinstance(error, dict):
            raise RuntimeError(str(error.get("message") or error))
        raise RuntimeError(str(error or "命令返回失败"))
    return payload


def _skill_root_from_scripts_dir(scripts_dir: Path) -> Path:
    return scripts_dir.resolve().parent


def _find_dataset_query_scripts(skills_dir: str | None = None) -> Path:
    current_skill_root = _skill_root_from_scripts_dir(Path(__file__).resolve().parent)
    candidates: list[Path] = []
    if skills_dir:
        candidates.append(Path(skills_dir).expanduser() / "ops-dataset-query" / "scripts")

    candidates.extend(
        [
            current_skill_root.parent / "ops-dataset-query" / "scripts",
            Path.cwd() / ".claude" / "skills" / "ops-dataset-query" / "scripts",
            Path.home() / ".claude" / "skills" / "ops-dataset-query" / "scripts",
            Path.home() / ".openclaw" / "skills" / "ops-dataset-query" / "scripts",
            Path.home() / ".codex" / "skills" / "ops-dataset-query" / "scripts",
            Path.home() / ".config" / "opencode" / "skills" / "ops-dataset-query" / "scripts",
            Path(__file__).resolve().parents[2] / "ops-dataset-query" / "scripts",
        ]
    )

    for scripts_dir in candidates:
        if (scripts_dir / "query.py").exists() and (scripts_dir / "excel_export.py").exists():
            return scripts_dir
    raise RuntimeError("未找到 ops-dataset-query，请先安装该 Skill")


def _unwrap_chart_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict) and isinstance(data.get("queries"), list):
        return data
    if isinstance(payload.get("queries"), list):
        return payload
    raise ValueError("chart 返回结构缺少 queries")


def _field_id(rule: dict[str, Any]) -> str:
    return str(rule.get("fieldId") or rule.get("field_id") or rule.get("field") or "").strip()


def _rule_lookup_keys(rule: dict[str, Any]) -> list[str]:
    """提取运行时规则可用于匹配图表字段的候选键。"""
    keys = [
        rule.get("fieldId"),
        rule.get("field_id"),
        rule.get("field"),
        rule.get("globalAlias"),
        rule.get("global_alias"),
        rule.get("fieldName"),
        rule.get("field_name"),
        rule.get("description"),
        rule.get("fieldLabel"),
        rule.get("field_label"),
        rule.get("title"),
        rule.get("name"),
    ]
    result: list[str] = []
    for key in keys:
        text = str(key or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _rule_value(rule: dict[str, Any]) -> Any:
    if "value" in rule:
        return rule.get("value")
    if "enumValue" in rule:
        return rule.get("enumValue")
    if "enum_value" in rule:
        return rule.get("enum_value")
    return None


def _normalize_operator(operator: str, value: Any) -> str:
    normalized = str(operator or "equals").strip()
    mapping = {
        "equals": "eq",
        "equal": "eq",
        "eq": "eq",
        "notEquals": "ne",
        "not_equals": "ne",
        "ne": "ne",
        "gt": "gt",
        "gte": "gte",
        "lt": "lt",
        "lte": "lte",
        "in": "in",
        "not_in": "not_in",
        "between": "between",
        "contains": "like",
        "like": "like",
    }
    if isinstance(value, list) and len(value) == 2 and normalized in ("equals", "eq"):
        return "between"
    if isinstance(value, list) and normalized in ("equals", "eq"):
        return "in"
    return mapping.get(normalized, normalized)


def _normalize_rule_value(rule: dict[str, Any], value: Any) -> Any:
    """按输入字段类型规整运行时参数。"""
    field_type = str(
        rule.get("fieldType")
        or rule.get("field_type")
        or rule.get("type")
        or ""
    ).lower()
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value) and ("date" in field_type or "time" in field_type):
        year, month = [int(part) for part in value.split("-")]
        last_day = calendar.monthrange(year, month)[1]
        return [f"{value}-01", f"{value}-{last_day:02d}"]
    return value


def _extract_dataset_alias(query_item: dict[str, Any]) -> str:
    query = query_item.get("query") or {}
    from_block = query.get("from") if isinstance(query, dict) else None
    if isinstance(from_block, dict) and from_block.get("alias"):
        return str(from_block["alias"])
    for select_item in query.get("select") or []:
        expr = str(select_item.get("expr") or "")
        if "." in expr:
            return expr.split(".", 1)[0]
    return str(query_item.get("dataset_alias") or "")


def _candidate_field_refs(query_item: dict[str, Any], datasets: list[dict[str, Any]]) -> dict[str, str]:
    dataset_alias = _extract_dataset_alias(query_item)
    table_id = query_item.get("tableId")
    refs: dict[str, str] = {}

    for mapping in query_item.get("field_mappings") or []:
        if not isinstance(mapping, dict):
            continue
        origin = str(mapping.get("origin_name") or mapping.get("query_expr") or mapping.get("expr") or "")
        if not origin and mapping.get("field_name") and dataset_alias:
            origin = f"{dataset_alias}.{mapping['field_name']}"
        for key in (
            mapping.get("global_alias"),
            mapping.get("query_alias"),
            mapping.get("alias"),
            mapping.get("field_name"),
            mapping.get("origin_name"),
            mapping.get("query_field"),
        ):
            key_text = str(key or "").strip()
            if key_text and origin:
                refs[key_text] = origin

    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        same_alias = not dataset_alias or str(dataset.get("dataset_alias") or "") == dataset_alias
        same_table = table_id is None or dataset.get("tableId") == table_id
        if not same_alias and not same_table:
            continue
        ds_alias = str(dataset.get("dataset_alias") or dataset_alias)
        for field in dataset.get("fields") or []:
            if not isinstance(field, dict):
                continue
            origin = str(field.get("origin_name") or "")
            if not origin and field.get("field_name") and ds_alias:
                origin = f"{ds_alias}.{field['field_name']}"
            for key in (
                field.get("global_alias"),
                field.get("field_name"),
                field.get("origin_name"),
                *(field.get("query_aliases") or []),
            ):
                key_text = str(key or "").strip()
                if key_text and origin:
                    refs[key_text] = origin
        for field in dataset.get("filterable_fields") or []:
            if not isinstance(field, dict):
                continue
            column = str(field.get("column_name") or field.get("source_column_name") or "").strip()
            if not column or not ds_alias:
                continue
            origin = f"{ds_alias}.{column}"
            for key in (column, field.get("source_column_name"), field.get("verbose_name"), field.get("global_alias")):
                key_text = str(key or "").strip()
                if key_text:
                    refs[key_text] = origin
    return refs


def _remove_conditions_for_fields(node: Any, fields: set[str]) -> Any:
    if not isinstance(node, dict):
        return node
    conditions = node.get("conditions")
    if not isinstance(conditions, list):
        return None if str(node.get("field") or "") in fields else node

    kept = []
    for child in conditions:
        next_child = _remove_conditions_for_fields(child, fields)
        if next_child is not None:
            kept.append(next_child)
    if not kept:
        return None
    next_node = dict(node)
    next_node["conditions"] = kept
    return next_node


def _merge_where(existing: Any, runtime_conditions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runtime_conditions:
        return existing if isinstance(existing, dict) else None
    runtime_fields = {str(item.get("field") or "") for item in runtime_conditions}
    active_runtime_conditions = [item for item in runtime_conditions if not item.get("_clear")]
    cleaned = _remove_conditions_for_fields(existing, runtime_fields) if existing else None
    conditions: list[dict[str, Any]] = []
    if isinstance(cleaned, dict):
        conditions.append(cleaned)
    conditions.extend(active_runtime_conditions)
    if not conditions:
        return None
    return {"operator": "AND", "conditions": conditions}


def _runtime_conditions(
    query_item: dict[str, Any],
    datasets: list[dict[str, Any]],
    filter_rule: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = _candidate_field_refs(query_item, datasets)
    conditions: list[dict[str, Any]] = []
    for rule in filter_rule.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        lookup_keys = _rule_lookup_keys(rule)
        if not lookup_keys:
            continue
        field = next((refs[key] for key in lookup_keys if key in refs), None)
        if not field:
            continue
        value = _rule_value(rule)
        if value in (None, ""):
            conditions.append({"field": field, "_clear": True})
            continue
        value = _normalize_rule_value(rule, value)
        operator = _normalize_operator(str(rule.get("operator") or "equals"), value)
        if operator == "like" and isinstance(value, str) and "%" not in value:
            value = f"%{value}%"
        conditions.append({"field": field, "operator": operator, "value": value})
    return conditions


def _build_payload(query_item: dict[str, Any], datasets: list[dict[str, Any]], filter_rule: dict[str, Any]) -> dict[str, Any]:
    table_id = query_item.get("tableId")
    if table_id is None:
        raise ValueError("chart query 缺少 tableId")
    query = deepcopy(query_item.get("query") or {})
    if not isinstance(query, dict):
        raise ValueError("chart query.query 必须是对象")
    query.pop("from", None)
    query["where"] = _merge_where(query.get("where"), _runtime_conditions(query_item, datasets, filter_rule))
    payload: dict[str, Any] = {"tableId": int(table_id), "query": query}
    if isinstance(query_item.get("dataComparison"), dict):
        payload["dataComparison"] = query_item["dataComparison"]
    return payload


def _normalize_query_result(wrapper: dict[str, Any]) -> dict[str, Any]:
    remote = wrapper.get("data") if isinstance(wrapper, dict) else wrapper
    rows: list[Any] = []
    meta: dict[str, Any] = {}

    if isinstance(remote, dict):
        inner = remote.get("data")
        if isinstance(inner, list):
            rows = inner
            meta = remote.get("meta") if isinstance(remote.get("meta"), dict) else {}
        elif isinstance(inner, dict):
            if isinstance(inner.get("data"), list):
                rows = inner["data"]
            elif isinstance(inner.get("rows"), list):
                rows = inner["rows"]
            meta = inner.get("meta") if isinstance(inner.get("meta"), dict) else {}
        elif isinstance(remote.get("rows"), list):
            rows = remote["rows"]
            meta = remote.get("meta") if isinstance(remote.get("meta"), dict) else {}
    return {"data": rows, "meta": meta, "raw": remote}


def _execute_chart(
    dataset_scripts: Path,
    chart_uuid: str,
    filter_rule: dict[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    query_script = dataset_scripts / "query.py"
    chart_payload = _run_json(
        [sys.executable, str(query_script), "chart", "--uuid", chart_uuid, "--pretty"],
        cwd=dataset_scripts,
    )
    chart_bundle = _unwrap_chart_bundle(chart_payload)
    datasets = chart_bundle.get("datasets") or []
    queries = chart_bundle.get("queries") or []
    if not isinstance(datasets, list) or not isinstance(queries, list) or not queries:
        raise ValueError("chart bundle 缺少 datasets 或 queries")

    executed_queries: list[dict[str, Any]] = []
    merged_rows: list[dict[str, Any]] = []
    success_count = 0
    row_count = 0

    for index, query_item in enumerate(queries):
        payload = _build_payload(query_item, datasets, filter_rule)
        payload_file = work_dir / f"query_{index}.json"
        payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            run_payload = _run_json(
                [sys.executable, str(query_script), "run", "--payload", str(payload_file), "--pretty"],
                cwd=dataset_scripts,
            )
            result = _normalize_query_result(run_payload)
            error = None
            success_count += 1
            for row in result.get("data") or []:
                if isinstance(row, dict):
                    merged_rows.append({"_query_index": index, **row})
            row_count += int((result.get("meta") or {}).get("rowCount") or len(result.get("data") or []))
        except Exception as exc:
            result = {"data": [], "meta": {}}
            error = {"code": "QUERY_ERROR", "message": str(exc)}
        executed_queries.append(
            {
                "index": index,
                "table_id": query_item.get("tableId"),
                "data_source": query_item.get("dataSource"),
                "query_structure": query_item.get("query"),
                "field_mappings": query_item.get("field_mappings") or [],
                "payload": payload,
                "result": result,
                "error": error,
            }
        )

    return {
        "chart_uuid": chart_bundle.get("chart_uuid") or chart_uuid,
        "datasets": datasets,
        "queries": executed_queries,
        "merged": {
            "rows": merged_rows,
            "meta": {
                "rowCount": row_count,
                "queryCount": len(queries),
                "successCount": success_count,
            },
        },
    }


def _export_excel(
    dataset_scripts: Path,
    chart_result_file: Path,
    output: str,
    sheet_name: str,
    skills_dir: str | None,
    pretty: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(dataset_scripts / "excel_export.py"),
        "--input",
        str(chart_result_file),
        "--output",
        output,
        "--sheet-name",
        sheet_name,
    ]
    if skills_dir:
        command.extend(["--skills-dir", skills_dir])
    if pretty:
        command.append("--pretty")
    return _run_json(command, cwd=dataset_scripts)


def _default_output_path(chart_uuid: str) -> str:
    """生成带时间戳的默认导出文件名，避免重复运行覆盖旧文件。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_chart_uuid = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in chart_uuid)
    return str(Path.cwd() / f"chart-data-{safe_chart_uuid}-{timestamp}.xlsx")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 Analysis View 图表数据 Excel")
    parser.add_argument("--chart-uuid", required=True, help="图表 UUID")
    parser.add_argument("--filter-rule", help="Analysis View 的 source.chartInfo.filterRule JSON 文件")
    parser.add_argument("--output", default="", help="Excel 输出路径；不传时自动生成带时间戳的文件名")
    parser.add_argument("--sheet-name", default="视图数据", help="Sheet 名称")
    parser.add_argument("--skills-dir", help="Skill 安装根目录")
    parser.add_argument("--work-dir", help="中间文件目录")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    try:
        filter_rule = _load_json_file(args.filter_rule)
        dataset_scripts = _find_dataset_query_scripts(args.skills_dir)
        output = args.output or _default_output_path(args.chart_uuid)
        output_path = Path(output).expanduser()
        safe_chart_uuid = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in args.chart_uuid)
        work_dir = (
            Path(args.work_dir).expanduser()
            if args.work_dir
            else output_path.parent / ".ops-cli-view-data" / safe_chart_uuid
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        chart_result = _execute_chart(dataset_scripts, args.chart_uuid, filter_rule, work_dir)
        chart_result_file = work_dir / "chart_result.json"
        chart_result_file.write_text(json.dumps(chart_result, ensure_ascii=False, indent=2), encoding="utf-8")
        excel_result = _export_excel(
            dataset_scripts,
            chart_result_file,
            output,
            args.sheet_name,
            args.skills_dir,
            args.pretty,
        )
        result = {
            "success": bool(excel_result.get("success", True)),
            "chart_uuid": chart_result.get("chart_uuid"),
            "chart_result": str(chart_result_file.resolve()),
            "excel": excel_result,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    except Exception as exc:
        print(json.dumps(_json_error(str(exc)), ensure_ascii=False, indent=2 if args.pretty else None), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
