"""ops-dataset-query Skill 的核心工具函数。

提供 CSV 加载、过滤、搜索打分、数据目录发现、本地索引加载、
字段解析、自动升级兜底和数值转换格式化等基础能力，
供 chart_map.py、chart_analyze.py、excel_export.py 等复用。
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# CSV 加载与搜索
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 数据目录发现与本地索引加载
# ---------------------------------------------------------------------------


def discover_data_dir(skills_dir: str | None = None) -> Path | None:
    """自动发现 ops-dataset-query 的数据目录。

    扫描优先级（与 opscli SkillDetector 保持一致）：
    1. 显式指定的 skills_dir
    2. 环境变量 OPSCLI_SKILLS_DIR
    3. 当前目录下的 .claude/skills
    4. 用户主目录下的 .claude/skills
    5. 用户主目录下的 .openclaw/skills
    6. 用户主目录下的 .codex/skills
    7. 用户主目录下的 .config/opencode/skills
    8. 脚本自身所在目录的相对路径（回退，用于开发/模板场景）

    Returns:
        第一个找到的 data/ 目录路径，或 None
    """
    candidates: list[Path] = []

    if skills_dir:
        candidates.append(Path(skills_dir).expanduser())

    env_dir = os.getenv("OPSCLI_SKILLS_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    home = Path.home()
    current = Path.cwd()
    candidates.extend([
        current / ".claude" / "skills",
        home / ".claude" / "skills",
        home / ".openclaw" / "skills",
        home / ".codex" / "skills",
        home / ".config" / "opencode" / "skills",
    ])

    # 检查每个候选目录下是否存在 ops-dataset-query/data/dataset_fields.csv
    for base_dir in candidates:
        data_dir = base_dir / "ops-dataset-query" / "data"
        if (data_dir / "dataset_fields.csv").exists():
            return data_dir

    # 回退：脚本自身所在目录的相对路径
    fallback = Path(__file__).resolve().parent.parent / "data"
    if (fallback / "dataset_fields.csv").exists():
        return fallback

    return None


def load_local_index(data_dir: Path) -> tuple[dict, dict]:
    """加载本地 CSV，构建数据集和字段的索引。

    Returns:
        (dataset_index, field_index)
        - dataset_index: {dataset_alias: {"table_id": ..., "dataset_name": ...}}
        - field_index: {(dataset_alias, global_alias): {"field_name": ..., "verbose_name": ...}}
    """
    datasets = load_csv_rows(data_dir / "datasets.csv")
    fields = load_csv_rows(data_dir / "dataset_fields.csv")

    dataset_index: dict[str, dict] = {}
    for row in datasets:
        alias = str(row.get("dataset_alias", "")).strip()
        if alias:
            dataset_index[alias] = {
                "table_id": row.get("table_id", ""),
                "dataset_name": row.get("dataset_name", ""),
                "dataset_alias": alias,
                "remarks": row.get("remarks", ""),
            }

    field_index: dict[tuple[str, str], dict] = {}
    for row in fields:
        ds_alias = str(row.get("dataset_alias", "")).strip()
        g_alias = str(row.get("global_alias", "")).strip()
        if ds_alias and g_alias:
            field_index[(ds_alias, g_alias)] = {
                "field_name": row.get("field_name", ""),
                "verbose_name": row.get("verbose_name", ""),
                "global_alias": g_alias,
                "field_type": row.get("field_type", ""),
                "remarks": row.get("remarks", ""),
            }

    return dataset_index, field_index


def resolve_dataset_alias(dataset_index: dict, alias: str) -> dict | None:
    """通过数据集别名查找数据集信息。"""
    return dataset_index.get(alias)


def resolve_field_alias(field_index: dict, dataset_alias: str, global_alias: str) -> dict | None:
    """通过数据集别名 + 字段别名查找字段信息。

    当 dataset_alias 为空时，遍历所有数据集尝试匹配。
    """
    if dataset_alias:
        return field_index.get((dataset_alias, global_alias))
    # dataset_alias 为空时，尝试所有数据集
    for (ds, ga), info in field_index.items():
        if ga == global_alias:
            return info
    return None


# ---------------------------------------------------------------------------
# 自动升级兜底
# ---------------------------------------------------------------------------


def try_upgrade(data_dir: Path | None = None, *, caller: str = "core") -> bool:
    """调用 opscli skills upgrade 更新本地数据。

    当本地索引无法匹配字段时，可能是本地数据过期或未同步，
    通过 upgrade 拉取最新远端数据后再重试。

    Args:
        data_dir: 保留参数（未使用），调用方可传入 data_dir 方便将来扩展
        caller: 调用来源标识（日志前缀）

    Returns:
        True 表示升级成功，False 表示升级失败
    """
    print(f"[{caller}] 本地字段映射未命中，尝试 opscli skills upgrade 更新数据...", file=sys.stderr)
    result = subprocess.run(
        ["opscli", "skills", "upgrade", "ops-dataset-query", "--force"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"[{caller}] upgrade 失败: {result.stderr}", file=sys.stderr)
        return False
    print(f"[{caller}] upgrade 成功，重新加载本地索引", file=sys.stderr)
    return True


def check_mapping_hit(mapped_queries: list[dict]) -> bool:
    """检查映射结果中是否有任意字段命中了本地索引。

    至少有一个 field_info 非空（包含 field_name / verbose_name 等）才算命中。

    Args:
        mapped_queries: map_chart_queries 的返回结果

    Returns:
        True 表示至少有一个字段映射成功
    """
    for q in mapped_queries:
        for fm in q.get("_mapping", {}).get("field_mappings", []):
            fi = fm.get("field_info", {})
            if fi and fi.get("field_name"):
                return True
    return False


# ---------------------------------------------------------------------------
# 通用数据类型转换与格式化工具
# ---------------------------------------------------------------------------

def to_float(v) -> float:
    """安全转换查询结果值为 float。

    查询结果中的数值字段可能是 int / float / str / None，
    统一转为 float 避免 TypeError。空字符串和 None 返回 0.0。

    Args:
        v: 待转换的值

    Returns:
        float 类型的数值
    """
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def safe_pct(cur: float, prev: float) -> float | None:
    """计算环比变化率（百分比小数形式）。

    分母为 0 时：cur 也为 0 返回 None（无变化），cur 不为 0 返回 float('inf')。

    Args:
        cur: 当期值
        prev: 对比期值

    Returns:
        变化率（如 -0.15 表示 -15%），或 None / float('inf')
    """
    if prev == 0:
        return None if cur == 0 else float("inf")
    return (cur - prev) / abs(prev)


def format_pct(value: float | None) -> str:
    """将 safe_pct 返回的变化率格式化为可读字符串。

    Args:
        value: safe_pct 的返回值

    Returns:
        格式化字符串，如 "+12.34%" / "-7.89%" / "N/A" / "+∞"
    """
    if value is None:
        return "N/A"
    if value == float("inf"):
        return "+∞"
    return f"{value * 100:+.2f}%"
