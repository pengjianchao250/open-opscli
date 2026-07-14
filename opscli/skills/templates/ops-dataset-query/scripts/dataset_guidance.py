#!/usr/bin/env python3
"""为单个已授权数据集产出紧凑的字段与权限筛选指导合同。

输入：当前账号元数据目录 + 数据集别名 + 用户查询（可选点名字段）。
输出：dataset_guidance_v1 合同，包含字段选择（含公式/快照聚合口径）、
权限筛选范围（查询组件可用性）与下一步动作。
本模块只读本地授权元数据，由 query_plan 组合入口调用。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import scoped_dataset_reader


CONTRACT = "dataset_guidance_v1"
# 公式字段口径：直接使用公式表达式，禁止再叠加普通聚合
FORMULA_RULE = "formula_expression_without_extra_aggregation"
# 快照字段口径：取最新快照，禁止跨期（跨日）累加聚合
SNAPSHOT_RULE = "latest_snapshot_no_period_aggregation"
ASCII_WORD_RE = re.compile(r"[a-z0-9]+")
CHINESE_RE = re.compile(r"[\u3400-\u9fff]+")
MAX_CONTRACT_BYTES = 6000
MAX_FULL_BYTES = 16000
MAX_QUERY_CHARS = 4096
MAX_REQUESTED_FIELDS = 32
MAX_FIELD_TEXT_CHARS = 256
ASCII_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _normalize(value: object) -> str:
    """NFKC 归一化 + casefold + 去首尾空白；非字符串归一为空串。"""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _tokens(value: object) -> set[str]:
    """把文本切成匹配用 token：ASCII 单词 + 中文单字/相邻二字组合。"""
    text = _normalize(value)
    tokens = set(ASCII_WORD_RE.findall(text))
    for chunk in CHINESE_RE.findall(text):
        if len(chunk) == 1:
            tokens.add(chunk)
        else:
            tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return tokens


def _find_dataset(datasets: list[dict], lookup: dict) -> dict:
    """按数据集别名精确定位目标数据集。

    只支持 dataset_alias 一种定位方式（组合入口的唯一用法），
    未命中抛 LookupError，命中多个（元数据异常）抛 ValueError。
    """
    if not isinstance(lookup, dict) or set(lookup) != {"dataset_alias"}:
        raise ValueError("lookup_requires_dataset_alias")
    value = str(lookup["dataset_alias"]).strip()
    if not value:
        raise ValueError("lookup_value_required")
    needle = _normalize(value)
    matches = [
        row
        for row in datasets
        if _normalize(row.get("dataset_alias", "")) == needle
    ]
    if not matches:
        raise LookupError("dataset_not_found_in_current_scope")
    if len(matches) != 1:
        raise ValueError("ambiguous_dataset_lookup")
    return matches[0]


def _contains_identifier(text: str, identifier: str) -> bool:
    """判断技术标识是否以完整单词形式出现在文本中（前后不能连着标识字符）。"""
    start = 0
    while True:
        index = text.find(identifier, start)
        if index < 0:
            return False
        end = index + len(identifier)
        left_ok = index == 0 or text[index - 1] not in ASCII_IDENTIFIER_CHARS
        right_ok = end == len(text) or text[end] not in ASCII_IDENTIFIER_CHARS
        if left_ok and right_ok:
            return True
        start = index + 1


def _field_score(
    field: dict,
    normalized_query: str,
    query_tokens: set[str],
) -> int:
    """字段与查询的匹配打分。

    优先级：技术字段名完整命中(100) > 中文全名子串命中(90+)
    > 去括号后的中文基础名命中(80+) > token 交集数量兜底。
    """
    field_name = _normalize(field.get("field_name"))
    verbose_name = _normalize(field.get("verbose_name"))
    base_name = re.split(r"[（(]", verbose_name, maxsplit=1)[0].strip()
    if field_name and _contains_identifier(normalized_query, field_name):
        return 100
    if verbose_name and verbose_name in normalized_query:
        return 90 + min(len(verbose_name), 9)
    if len(base_name) >= 2 and base_name in normalized_query:
        return 80 + min(len(base_name), 9)
    return len(_tokens(base_name).intersection(query_tokens))


def _is_formula(field: dict) -> bool:
    """判断是否公式字段：显式标记或带任一公式表达式。"""
    return bool(
        field.get("has_formula_config") == "1"
        or str(field.get("summary_expression", "")).strip()
        or str(field.get("detail_expression", "")).strip()
    )


def _is_date_field(field: dict) -> bool:
    """判断日期类维度：技术名含 date/time 或中文名含 日期/时间。

    为什么需要：时间过滤与 dataComparison 都必须使用授权日期字段，
    但用户几乎从不口头点名日期字段，合同必须无条件携带日期字段引用，
    否则模型只能靠扫盘或猜字段名补齐（e2e 实测的高频探查形态）。
    """
    name = str(field.get("field_name", "")).casefold()
    label = str(field.get("verbose_name", ""))
    return "date" in name or "time" in name or "日期" in label or "时间" in label


def _is_snapshot(field: dict) -> bool:
    """判断是否快照类指标（如库存量），此类字段不可跨期累加。"""
    return field.get("snapshot_metric") == "1"


def _compact_field(field: dict, selection_source: str, output_mode: str) -> dict:
    """把一个字段压缩为指导合同中的紧凑表示。

    aggregation_policy 优先级：公式口径 > 快照口径 > 服务端元数据默认。
    """
    formula = _is_formula(field)
    snapshot = _is_snapshot(field)
    result = {
        "field_name": field["field_name"],
        "verbose_name": field.get("verbose_name", ""),
        "selection_source": selection_source,
        "is_formula": formula,
        "is_snapshot": snapshot,
        "aggregation_policy": (
            FORMULA_RULE
            if formula
            else (SNAPSHOT_RULE if snapshot else "service_metadata_or_query_contract")
        ),
    }
    if output_mode == "full":
        result["field_type"] = field["field_type"]
    if formula and output_mode == "full":
        result.update(
            {
                "summary_expression": field.get("summary_expression", ""),
                "detail_expression": field.get("detail_expression", ""),
            }
        )
    return result


def _select_fields(
    fields: Iterable[dict],
    query: str,
    limit: int,
    explicit_names: set[str],
    output_mode: str,
) -> list[dict]:
    """选出进入指导合同的字段列表。

    显式点名字段固定 1000 分必选（limit 自动放宽到点名数量）；
    其余字段按匹配分降序补足；仍不足 limit 时按原始顺序兜底填充，
    并用 selection_source 标注来源（explicit / query / fallback）。
    """
    normalized_query = _normalize(query)
    query_tokens = _tokens(normalized_query)
    ranked = [
        (
            (
                1000
                if field["field_name"] in explicit_names
                else _field_score(field, normalized_query, query_tokens)
            ),
            index,
            field,
        )
        for index, field in enumerate(fields)
    ]
    explicit_count = sum(row[2]["field_name"] in explicit_names for row in ranked)
    limit = max(limit, explicit_count)
    matched = sorted((row for row in ranked if row[0] > 0), key=lambda row: (-row[0], row[1]))
    selected = matched[:limit]
    selected_indexes = {row[1] for row in selected}
    for row in ranked:
        if len(selected) >= limit:
            break
        if row[1] not in selected_indexes:
            selected.append(row)
    return [
        _compact_field(
            field,
            (
                "explicit"
                if field["field_name"] in explicit_names
                else ("query" if score > 0 else "fallback")
            ),
            output_mode,
        )
        for score, _index, field in selected
    ]


def _validated_dataset_fields(fields: list[dict], dataset: dict) -> list[dict]:
    """校验目标数据集的字段集合：非空、字段名唯一、dataset_name 一致。"""
    dataset_alias = dataset["dataset_alias"]
    selected = [row for row in fields if row["dataset_alias"] == dataset_alias]
    names = [row["field_name"] for row in selected]
    if not selected:
        raise ValueError("dataset_has_no_fields")
    if len(names) != len(set(names)):
        raise ValueError("duplicate_dataset_field")
    if any(row["dataset_name"] != dataset["dataset_name"] for row in selected):
        raise ValueError("field_dataset_name_mismatch")
    return selected


def _resolve_requested_fields(
    fields: list[dict], requested_fields: Iterable[str]
) -> tuple[set[str], list[str]]:
    """把用户点名字段解析为技术字段名。

    优先按 field_name 精确匹配，其次按 verbose_name 精确匹配；
    无法唯一确定的点名进入 unknown 列表，触发字段澄清。
    """
    if isinstance(requested_fields, (str, bytes)):
        raise TypeError("requested_fields_must_be_iterable_of_strings")
    try:
        requested = list(requested_fields)
    except TypeError as error:
        raise TypeError("requested_fields_must_be_iterable_of_strings") from error
    if any(not isinstance(item, str) or not item.strip() for item in requested):
        raise TypeError("requested_fields_must_be_iterable_of_strings")
    if len(requested) > MAX_REQUESTED_FIELDS or any(
        len(item) > MAX_FIELD_TEXT_CHARS for item in requested
    ):
        raise ValueError("requested_fields_too_large")
    selected = set()
    unknown = []
    for raw_value in dict.fromkeys(requested):
        value = _normalize(raw_value)
        name_matches = [
            field
            for field in fields
            if value == _normalize(field.get("field_name"))
        ]
        matches = name_matches or [
            field
            for field in fields
            if value == _normalize(field.get("verbose_name"))
        ]
        if len(matches) == 1:
            selected.add(matches[0]["field_name"])
        else:
            unknown.append(raw_value)
    return selected, unknown


def _permission_scope(
    dataset_alias: str,
    datasets: list[dict],
    fields: list[dict],
    select_columns: list[dict],
    query: str,
    explicit_names: set[str],
    output_mode: str,
    max_components: int,
) -> dict:
    """构建权限筛选范围合同。

    每个可筛选列的组件数据集必须在当前授权范围内才允许显式筛选；
    组件缺失时该列标记为 blocked，只阻断该筛选、不扩大查询范围。
    contract 模式只保留与查询相关或被阻断的列，控制输出体积。
    """
    rows = [
        row
        for row in select_columns
        if row["current_dataset_alias"] == dataset_alias
    ]
    column_names = [row["column_name"] for row in rows]
    if len(column_names) != len(set(column_names)):
        raise ValueError("duplicate_dataset_select_column")
    authorized_aliases = {row["dataset_alias"] for row in datasets}
    dataset_field_names = {
        row["field_name"] for row in fields if row["dataset_alias"] == dataset_alias
    }
    normalized_query = _normalize(query)
    query_tokens = _tokens(normalized_query)
    ranked = sorted(
        (
            (
                1000
                if row["column_name"] in explicit_names
                else _field_score(
                    {
                        "field_name": row["column_name"],
                        "verbose_name": row.get("verbose_name", ""),
                    },
                    normalized_query,
                    query_tokens,
                ),
                index,
                row,
            )
            for index, row in enumerate(rows)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if output_mode == "contract":
        relevant = [
            item
            for item in ranked
            if item[0] > 0
            or item[2]["component_dataset_alias"] not in authorized_aliases
        ]
    else:
        relevant = ranked
    selected_rows = [row for _score, _index, row in relevant[:max_components]]
    # 组件 alias → table_id 映射：contract 模式也要携带组件执行引用，
    # 否则部门/国家等非平台筛选没有任何合规枚举入口（e2e 实测缺口）
    alias_to_table = {
        row["dataset_alias"]: row.get("table_id", "") for row in datasets
    }
    filter_fields = []
    for row in selected_rows:
        available = row["component_dataset_alias"] in authorized_aliases
        item = {
            "field_name": row["column_name"],
            "verbose_name": row.get("verbose_name", ""),
            "component_status": (
                "component_available"
                if available
                else "blocked_missing_authorized_component"
            ),
        }
        if available:
            # 两种输出模式都带组件引用：这是显式筛选唯一的合规枚举入口
            item["component_dataset_alias"] = row["component_dataset_alias"]
            item["component_table_id"] = alias_to_table.get(
                row["component_dataset_alias"], ""
            )
        if output_mode == "full":
            item.update(
                {
                    "field_in_dataset_fields": row["column_name"]
                    in dataset_field_names,
                    "explicit_filter_allowed": available,
                }
            )
        filter_fields.append(item)
    blocked = list(
        dict.fromkeys(
            row["column_name"]
            for row in rows
            if row["component_dataset_alias"] not in authorized_aliases
        )
    )
    return {
        "default_scope": "current_authenticated_account",
        "client_may_expand_scope": False,
        "default_filter_invention_allowed": False,
        "explicit_filter_requires_component_validation": True,
        "filter_fields": filter_fields,
        "filter_field_count": len(rows),
        "components_truncated": len(rows) > len(filter_fields),
        "blocked_filter_fields": blocked,
    }


def _validate_output_size(result: dict, output_mode: str) -> None:
    """守卫输出体积，防止异常元数据把合同撑爆到模型上下文。"""
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    limit = MAX_CONTRACT_BYTES if output_mode == "contract" else MAX_FULL_BYTES
    if len(payload) > limit:
        raise ValueError("dataset_guidance_output_too_large")


def _load_target_metadata(data_dir: Path, lookup: dict) -> tuple:
    """基于同一份文件快照加载目标数据集的全部相关元数据，保证口径一致。"""
    snapshot = scoped_dataset_reader.read_source_snapshot(data_dir)
    datasets = scoped_dataset_reader.load_datasets(data_dir, snapshot=snapshot)
    dataset = _find_dataset(datasets, lookup)
    dataset_alias = dataset["dataset_alias"]
    fields = scoped_dataset_reader.load_dataset_fields(
        data_dir, dataset_alias, snapshot=snapshot
    )
    select_columns = scoped_dataset_reader.load_select_columns(
        data_dir, dataset_alias, snapshot=snapshot
    )
    fingerprint = scoped_dataset_reader.source_fingerprint(
        data_dir, snapshot=snapshot
    )
    return dataset, datasets, fields, select_columns, fingerprint


def build_guidance(
    data_dir: Path,
    lookup: dict,
    *,
    query: str = "",
    requested_fields: Iterable[str] = (),
    output_mode: str = "contract",
    max_dimensions: int = 8,
    max_metrics: int = 8,
    max_components: int = 32,
) -> dict:
    """为一个已授权数据集产出字段与权限指导合同。

    guidance_status 取值：
    - ready：可继续校验筛选并构造查询；
    - clarify_required：存在无法唯一解析的点名字段，需要澄清；
    - permission_enum_only：目标是权限枚举组件，只能用于枚举查询。
    """
    if not isinstance(query, str):
        raise TypeError("query_must_be_string")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query_too_long")
    if output_mode not in {"contract", "full"}:
        raise ValueError("unsupported_output_mode")
    if any(type(value) is not int or value < 1 for value in (max_dimensions, max_metrics, max_components)):
        raise ValueError("invalid_output_limit")

    dataset, datasets, fields, select_columns, fingerprint = _load_target_metadata(
        Path(data_dir), lookup
    )
    dataset_alias = dataset["dataset_alias"]
    dataset_fields = _validated_dataset_fields(fields, dataset)
    explicit_names, unknown_fields = _resolve_requested_fields(
        dataset_fields, requested_fields
    )
    dimensions = [row for row in dataset_fields if row["field_type"] == "dimension"]
    metrics = [row for row in dataset_fields if row["field_type"] == "metric"]
    selected_dimensions = _select_fields(
        dimensions,
        query,
        max_dimensions,
        explicit_names,
        output_mode,
    )
    selected_metrics = _select_fields(
        metrics,
        query,
        max_metrics,
        explicit_names,
        output_mode,
    )
    category = dataset.get("dataset_category", "")
    status = (
        "clarify_required"
        if unknown_fields
        else ("permission_enum_only" if category == "query_component" else "ready")
    )
    result = {
        "contract": CONTRACT,
        "guidance_status": status,
        "query_execution_allowed": False,
        "metadata_fingerprint": fingerprint,
        "dataset": {
            "dataset_alias": dataset_alias,
            "dataset_name": dataset.get("dataset_name", ""),
            "display_name_zh": dataset.get("description", ""),
            "table_id": dataset.get("table_id", ""),
            "dataset_category": category,
        },
        "field_guidance": {
            "output_mode": output_mode,
            "dimensions": selected_dimensions,
            "metrics": selected_metrics,
            "dimension_count": len(dimensions),
            "metric_count": len(metrics),
            "formula_field_count": sum(_is_formula(row) for row in metrics),
            "snapshot_field_count": sum(_is_snapshot(row) for row in metrics),
            "formula_rule": FORMULA_RULE,
            "snapshot_rule": SNAPSHOT_RULE,
            "unknown_requested_fields": unknown_fields,
            # 日期类维度无条件输出（上限 5 个）：时间过滤/dataComparison 的构造依据，
            # 不受点名/打分筛选影响
            "date_fields": [
                {
                    "field_name": row["field_name"],
                    "verbose_name": row.get("verbose_name", ""),
                }
                for row in dimensions
                if _is_date_field(row)
            ][:5],
            "truncated": (
                len(dimensions) > len(selected_dimensions)
                or len(metrics) > len(selected_metrics)
            ),
        },
        "permission_scope": _permission_scope(
            dataset_alias,
            datasets,
            fields,
            select_columns,
            query,
            explicit_names,
            output_mode,
            max_components,
        ),
        "missing_information": ["fields"] if unknown_fields else [],
        "next_action": (
            "clarify_fields"
            if status == "clarify_required"
            else (
                "permission_enum_lookup_only"
                if status == "permission_enum_only"
                else "validate_filters_then_construct_query"
            )
        ),
    }
    _validate_output_size(result, output_mode)
    return result
