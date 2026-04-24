"""ops-dataset-query Skill 的核心工具函数。

提供 CSV 加载、过滤和搜索打分能力，供 search.py 和 updater.py 复用。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path


def load_csv_rows(path: Path) -> list[dict]:
    """加载 CSV 文件为字典列表。

    使用 utf-8-sig 编码以兼容带 BOM 的 CSV 文件。
    文件不存在时返回空列表。

    Args:
        path: CSV 文件路径

    Returns:
        每行一个字典，键名为 CSV 表头
    """
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def filter_rows_by_dataset(rows: list[dict], dataset: str | None) -> list[dict]:
    """按数据集别名过滤行。

    Args:
        rows: 原始字段行
        dataset: 数据集别名；为空时不过滤

    Returns:
        过滤后的字段行
    """
    if not dataset:
        return rows

    normalized = dataset.strip().lower()
    if not normalized:
        return rows

    return [
        row for row in rows
        if str(row.get("dataset_alias", "")).strip().lower() == normalized
    ]


def search_rows(rows: list[dict], keyword: str, limit: int = 10) -> list[dict]:
    """按关键词搜索字段行，并返回按相关性排序后的结果。

    排序策略使用简单加权打分，优先匹配：
    - `field_name`
    - `verbose_name`
    - `description`
    - 其他整行内容
    """
    normalized = keyword.strip().lower()
    if not normalized:
        return []

    tokens = _tokenize(normalized)
    if not tokens:
        return []

    scored: list[tuple[int, dict]] = []
    for row in rows:
        score = _score_row(row, normalized, tokens)
        if score <= 0:
            continue
        scored.append((score, row))

    scored.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("dataset_alias", "")),
            str(item[1].get("field_name", "")),
        )
    )

    return [row for _, row in scored[: max(limit, 0)]]


def _tokenize(value: str) -> list[str]:
    """将搜索词切分为 token。"""
    return [token for token in re.split(r"[\s_\-./]+", value.lower()) if token]


def _score_row(row: dict, keyword: str, tokens: list[str]) -> int:
    """为单行结果打分。"""
    field_name = str(row.get("field_name", "")).lower()
    verbose_name = str(row.get("verbose_name", "")).lower()
    global_alias = str(row.get("global_alias", "")).lower()
    description = str(row.get("description", "")).lower()
    dataset_alias = str(row.get("dataset_alias", "")).lower()
    dataset_name = str(row.get("dataset_name", "")).lower()
    fulltext = " ".join(str(value).lower() for value in row.values())

    score = 0

    # 精确/短字段优先
    if keyword == field_name:
        score += 120
    if keyword == global_alias:
        score += 115
    if keyword == verbose_name:
        score += 100
    if keyword == dataset_alias:
        score += 40

    # 连续子串匹配
    if keyword in field_name:
        score += 60
    if keyword in global_alias:
        score += 55
    if keyword in verbose_name:
        score += 45
    if keyword in dataset_name:
        score += 20
    if keyword in description:
        score += 10

    # token 逐项匹配
    score += _token_match_score(field_name, tokens, 16)
    score += _token_match_score(global_alias, tokens, 14)
    score += _token_match_score(verbose_name, tokens, 12)
    score += _token_match_score(dataset_name, tokens, 6)
    score += _token_match_score(description, tokens, 4)
    score += _token_match_score(fulltext, tokens, 2)

    return score


def _token_match_score(text: str, tokens: list[str], weight: int) -> int:
    """计算 token 命中的加权分数。"""
    return sum(weight for token in tokens if token in text)
