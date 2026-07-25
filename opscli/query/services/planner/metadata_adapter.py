#!/usr/bin/env python3
"""元数据适配器：query-metadata JSON payload → scoped_dataset_reader 同形行字典。

内核化后取数规划器的数据源从 Skill 的 data/*.csv 改为后端
query-metadata?include_all_fields=1（经用户级元数据缓存）。本模块把
QueryManager.metadata_all() 返回的 payload 映射为与旧 scoped_dataset_reader
三个 load_* 完全同形的行字典，从而下游选表/字段指导/schema linking 逻辑
可近乎逐字移植。

payload 结构（后端全量元数据）：
    {
      "datasets": [
        {..., "select_columns": [ {column_name, verbose_name, component_dataset_alias}... ],
              "filter_configs": [...] },
        ...
      ],
      "fields": [
        {table_id, dataset_alias, field_name, verbose_name, global_alias, field_type,
         summary_expression, detail_expression, snapshot_metric, has_formula_config}, ...
      ],
    }

职责边界：适配器只做数据整形（列映射 + 归一 + 去重合并 + filter_config 解析），
不承担 CSV 路径的完整性校验（快照一致性/列校验等）——数据源改为后端 JSON 后，
这些由后端与 metadata_cache 保证；行级语义正确性由 Task 9 回归对拍兜底。

依赖方向（铁律2）：仅依赖标准库，禁止 import opscli.mcp。
"""

from __future__ import annotations

import json


# select_column_names 多列拼接分隔符（该派生列仅供信息展示，不被读取路径消费）
_SELECT_COLUMN_NAMES_SEP = ","

# 判定重复字段行「执行语义一致」的列集合：这些列决定查询构造与聚合口径，
# 任何一列不一致都不允许自动合并（verbose_name/global_alias 等仅是展示别名）。
# 逐字对齐 scoped_dataset_reader._FIELD_SEMANTIC_KEYS。
_FIELD_SEMANTIC_KEYS = (
    "field_type",
    "summary_expression",
    "detail_expression",
    "snapshot_metric",
    "has_formula_config",
)


def parse_filter_config(raw: object) -> dict | None:
    """解析字段级 filter_config（可选，旧数据/后端未下发时为空）。

    逐字对齐 scoped_dataset_reader.parse_filter_config：空值返回 None；
    enabled 非真视为未配置返回 None；非法 JSON 抛 ValueError（坏数据应显式暴露）。
    兼容 payload 直接下发 dict 的情形（后端 JSON 场景下 filter_config 可能已是对象）。
    """
    # 后端 JSON 可能已把 filter_config 反序列化为 dict，直接判断 enabled
    if isinstance(raw, dict):
        return raw if raw.get("enabled") else None
    text = (str(raw) if raw is not None else "").strip()
    if not text:
        return None
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_filter_config") from exc
    if not isinstance(config, dict) or not config.get("enabled"):
        return None
    return config


def _contains_cjk(text: str) -> bool:
    """判断文本是否包含中日韩统一表意文字（用于挑选中文展示名主行）。"""
    return any("㐀" <= char <= "鿿" for char in text)


def _field_semantic_signature(row: dict) -> tuple:
    """提取字段行的执行语义签名（含 filter_config 的稳定序列化）。"""
    config = row.get("filter_config")
    return tuple(str(row.get(key, "")).strip() for key in _FIELD_SEMANTIC_KEYS) + (
        json.dumps(config, ensure_ascii=False, sort_keys=True) if config else "",
    )


def _mergeable_rows(group: list[dict]) -> list[dict] | None:
    """判定一组同名字段行是否可自动合并，可合并时返回主行候选列表。

    逐字对齐 scoped_dataset_reader._mergeable_rows：
    - 形态一（纯标签差异）：全组语义签名一致，返回全组；
    - 形态二（公式 vs 裸指标）：返回公式注册行；
    - None：语义冲突无法自动裁决，调用方保留原始行。
    """
    signatures = {_field_semantic_signature(row) for row in group}
    if len(signatures) == 1:
        return group
    # 公式列以外的语义（field_type/快照/默认条件）必须一致才可能是形态二
    base_signatures = {
        (
            row["field_type"],
            str(row.get("snapshot_metric", "")).strip() or "0",
            json.dumps(row.get("filter_config"), ensure_ascii=False, sort_keys=True)
            if row.get("filter_config")
            else "",
        )
        for row in group
    }
    if len(base_signatures) != 1:
        return None
    formula_rows = [row for row in group if row.get("has_formula_config") == "1"]
    plain_rows = [row for row in group if row.get("has_formula_config") == "0"]
    if not formula_rows or not plain_rows:
        return None
    # 多行公式注册且表达式不一致时同样无法裁决（实测恒为 1 公式 + 1 裸指标）
    if len({_field_semantic_signature(row) for row in formula_rows}) != 1:
        return None
    return formula_rows


def _merge_duplicate_field_rows(rows: list[dict]) -> list[dict]:
    """合并同数据集内 field_name 重复且执行语义一致的字段行。

    逐字对齐 scoped_dataset_reader._merge_duplicate_field_rows：BI 侧同一物理字段
    可挂多个全局别名（global_alias），后端会导出多行——field_name 相同、
    verbose_name/global_alias 不同。合并规则见原实现（形态一纯标签差异、
    形态二公式 vs 裸指标），其余冲突保留全部行交由下游硬失败。
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (row["dataset_alias"], row["field_name"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    merged: list[dict] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        candidates = _mergeable_rows(group)
        if candidates is None:
            # 无法自动裁决的语义冲突：保留全部行让下游唯一性校验硬失败
            merged.extend(group)
            continue
        primary = next(
            (
                row
                for row in candidates
                if _contains_cjk(row.get("verbose_name", ""))
                and row.get("verbose_name", "").strip().casefold()
                != row["field_name"].casefold()
            ),
            candidates[0],
        )
        primary_label = primary.get("verbose_name", "").strip()
        alt_labels: list[str] = []
        for row in group:
            label = row.get("verbose_name", "").strip()
            if label and label != primary_label and label not in alt_labels:
                alt_labels.append(label)
        if alt_labels:
            # 备选展示名仅用于匹配增强，additive 键不影响既有消费方
            primary["alt_verbose_names"] = alt_labels
        merged.append(primary)
    return merged


class MetadataAdapter:
    """把后端全量元数据 payload 映射为 scoped_dataset_reader 同形行字典。

    三个方法分别对应旧 load_datasets / load_dataset_fields / load_select_columns
    的返回形态，供选表卡片构建与字段指导逻辑消费。
    """

    def __init__(self, payload: dict) -> None:
        """接收 QueryManager.metadata_all().payload。

        Args:
            payload: 后端全量元数据，含 datasets（内嵌 select_columns/filter_configs）
                与 fields（扁平列表）。缺失键按空列表处理。
        """
        self._datasets = list(payload.get("datasets") or [])
        self._fields = list(payload.get("fields") or [])

    def datasets_rows(self) -> list[dict]:
        """返回数据集行，同形于 datasets.csv 列。

        列：table_id/dataset_alias/dataset_name/dataset_category/inner_where_enabled/
        description/remarks，并从内嵌 select_columns 派生 select_column_count（列数）
        与 select_column_names（列名按逗号拼接，仅供信息展示）。
        """
        rows: list[dict] = []
        for dataset in self._datasets:
            selects = list(dataset.get("select_columns") or [])
            column_names = [
                str(item.get("column_name") or "").strip()
                for item in selects
                if str(item.get("column_name") or "").strip()
            ]
            rows.append(
                {
                    "table_id": dataset.get("table_id"),
                    "dataset_alias": str(dataset.get("dataset_alias") or "").strip(),
                    "dataset_name": dataset.get("dataset_name") or "",
                    "dataset_category": dataset.get("dataset_category") or "",
                    "inner_where_enabled": dataset.get("inner_where_enabled"),
                    "description": dataset.get("description") or "",
                    "remarks": dataset.get("remarks") or "",
                    "select_column_count": len(selects),
                    "select_column_names": _SELECT_COLUMN_NAMES_SEP.join(column_names),
                }
            )
        return rows

    def fields_rows(self) -> list[dict]:
        """返回字段行，同形于 dataset_fields.csv 列（经去重合并）。

        归一化：dataset_alias/field_name strip；field_type 转小写；
        has_formula_config、snapshot_metric 归一为字符串 "0"/"1"（缺省视同 "0"），
        与 CSV 路径一致以保证合并去重与下游打分口径不变；filter_config 解析为
        dict 或 None。最后套用 _merge_duplicate_field_rows 合并同物理字段双注册。
        """
        normalized: list[dict] = []
        for field in self._fields:
            row = dict(field)
            row["dataset_alias"] = str(field.get("dataset_alias") or "").strip()
            row["field_name"] = str(field.get("field_name") or "").strip()
            row["field_type"] = str(field.get("field_type") or "").strip().lower()
            row["verbose_name"] = field.get("verbose_name") or ""
            row["global_alias"] = field.get("global_alias") or ""
            row["summary_expression"] = str(field.get("summary_expression") or "").strip()
            row["detail_expression"] = str(field.get("detail_expression") or "").strip()
            # 公式标记与快照标记归一为字符串（int 1/0 → "1"/"0"，缺省 "0"）
            row["has_formula_config"] = (
                str(field.get("has_formula_config")).strip()
                if field.get("has_formula_config") is not None
                else "0"
            )
            row["snapshot_metric"] = (
                str(field.get("snapshot_metric")).strip()
                if field.get("snapshot_metric") is not None
                else "0"
            ) or "0"
            # 字段级默认条件（可选）：后端可能下发 dict 或 JSON 串，统一解析
            row["filter_config"] = parse_filter_config(field.get("filter_config"))
            normalized.append(row)
        return _merge_duplicate_field_rows(normalized)

    def select_columns_rows(self) -> list[dict]:
        """返回查询组件列行，同形于 dataset_select_columns.csv 列。

        把每个 dataset 内嵌的 select_columns 展平为行，补 current_dataset_alias=
        外层 dataset_alias，列为 current_dataset_alias/column_name/verbose_name/
        component_dataset_alias。
        """
        rows: list[dict] = []
        for dataset in self._datasets:
            current_alias = str(dataset.get("dataset_alias") or "").strip()
            for item in dataset.get("select_columns") or []:
                rows.append(
                    {
                        "current_dataset_alias": current_alias,
                        "column_name": str(item.get("column_name") or "").strip(),
                        "verbose_name": item.get("verbose_name") or "",
                        "component_dataset_alias": str(
                            item.get("component_dataset_alias") or ""
                        ).strip(),
                    }
                )
        return rows
