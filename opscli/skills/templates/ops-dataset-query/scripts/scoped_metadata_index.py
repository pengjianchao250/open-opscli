#!/usr/bin/env python3
"""把当前账号授权元数据 CSV 编译为内存中的数据集决策卡片。

数据读取与校验统一复用 scoped_dataset_reader（快照一致性 + 列校验），
本模块只负责按数据集聚合出选表用的紧凑卡片（decision card）。
卡片仅在单次进程内构建和消费，不落盘、不加锁。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import scoped_dataset_reader


def _clean(value: object) -> str:
    """把任意值安全转为去首尾空白的字符串（None 归一为空串）。"""
    return str(value or "").strip()


def _sorted_terms(rows: Iterable[dict], keys: Sequence[str]) -> list[str]:
    """从行集合中提取指定列的非空值，去重后按字典序返回。

    卡片中的 terms 用于选表打分的文本匹配，排序保证输出稳定可比。
    """
    terms = {
        cleaned
        for row in rows
        for key in keys
        if (cleaned := _clean(row.get(key)))
    }
    return sorted(terms)


def _build_cards(
    datasets: list[dict],
    fields: list[dict],
    select_columns: list[dict],
) -> list[dict]:
    """按数据集聚合字段与查询组件列，生成选表决策卡片列表。

    每张卡片包含：中文名称/说明/备注（自然语言选表依据）、
    维度词表、指标词表、组件列词表（残差词匹配依据）。
    只聚合归属于已授权数据集别名的行，未知别名的行直接忽略。
    """
    authorized_aliases = {row["dataset_alias"] for row in datasets}
    fields_by_alias: dict[str, dict[str, list[dict]]] = {
        alias: {"dimension": [], "metric": []} for alias in authorized_aliases
    }
    selects_by_alias: dict[str, list[dict]] = {
        alias: [] for alias in authorized_aliases
    }

    for row in fields:
        alias = row["dataset_alias"]
        if alias in authorized_aliases:
            fields_by_alias[alias][row["field_type"]].append(row)
    for row in select_columns:
        alias = row["current_dataset_alias"]
        if alias in authorized_aliases:
            selects_by_alias[alias].append(row)

    cards = []
    for dataset in sorted(datasets, key=lambda row: row["dataset_alias"]):
        alias = dataset["dataset_alias"]
        card_selects = selects_by_alias[alias]
        cards.append(
            {
                "dataset_alias": alias,
                "dataset_name": _clean(dataset["dataset_name"]),
                "dataset_category": _clean(dataset["dataset_category"]),
                "description": _clean(dataset["description"]),
                "remarks": _clean(dataset["remarks"]),
                "dimension_terms": _sorted_terms(
                    fields_by_alias[alias]["dimension"],
                    ("field_name", "verbose_name"),
                ),
                "metric_terms": _sorted_terms(
                    fields_by_alias[alias]["metric"],
                    ("field_name", "verbose_name"),
                ),
                "select_column_terms": _sorted_terms(
                    card_selects,
                    ("column_name", "verbose_name"),
                ),
                "select_column_count": len(card_selects),
            }
        )
    return cards


def build_cards(data_dir: Path) -> list[dict]:
    """读取当前账号三个元数据 CSV 并构建决策卡片。

    通过 scoped_dataset_reader 的快照机制一次性读取三个文件，
    保证同一次构建看到的是一致的文件内容；校验失败直接抛出
    ValueError/FileNotFoundError，由调用方转为规划器错误输出。
    """
    data_dir = Path(data_dir)
    snapshot = scoped_dataset_reader.read_source_snapshot(data_dir)
    datasets = scoped_dataset_reader.load_datasets(data_dir, snapshot=snapshot)
    fields = scoped_dataset_reader.load_dataset_fields(data_dir, snapshot=snapshot)
    select_columns = scoped_dataset_reader.load_select_columns(
        data_dir, snapshot=snapshot
    )
    return _build_cards(datasets, fields, select_columns)
