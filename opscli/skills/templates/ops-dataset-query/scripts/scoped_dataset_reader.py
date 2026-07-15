#!/usr/bin/env python3
"""按授权范围读取当前账号元数据 CSV 的统一数据层。

三个元数据文件（datasets / dataset_fields / dataset_select_columns）
的读取、快照一致性检查、列校验和行校验都收敛在本模块，
供 scoped_metadata_index（选表卡片）与 dataset_guidance（字段指导）复用，
避免出现口径不一致的多套读取实现。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import NamedTuple


# 三个授权元数据源文件，顺序固定（指纹计算依赖顺序稳定）
SOURCE_FILES = (
    "datasets.csv",
    "dataset_fields.csv",
    "dataset_select_columns.csv",
)
# datasets.csv 必需列：remarks 是自然语言选表的依据之一，必须存在
DATASET_COLUMNS = frozenset(
    {
        "table_id",
        "dataset_alias",
        "dataset_name",
        "dataset_category",
        "description",
        "remarks",
    }
)
# dataset_fields.csv 必需列：snapshot_metric 标记快照类指标（不可跨期聚合），
# has_formula_config 标记公式字段（禁止二次聚合）
FIELD_COLUMNS = frozenset(
    {
        "dataset_alias",
        "dataset_name",
        "field_name",
        "verbose_name",
        "field_type",
        "summary_expression",
        "detail_expression",
        "snapshot_metric",
        "has_formula_config",
    }
)
SELECT_COLUMNS = frozenset(
    {
        "current_dataset_alias",
        "column_name",
        "verbose_name",
        "component_dataset_alias",
    }
)


class SourceSnapshot(NamedTuple):
    """三个源文件的一次性字节快照，保证同一次处理内容一致。"""

    files: tuple[tuple[str, bytes], ...]

    def content(self, filename: str) -> bytes:
        """按文件名取快照内容，不存在时抛 KeyError。"""
        for source_name, content in self.files:
            if source_name == filename:
                return content
        raise KeyError(filename)


def parse_filter_config(raw: str | None) -> dict | None:
    """解析字段 CSV filter_config 列（可选列，旧数据无此列）。

    空值/缺列返回 None；enabled 非真视为未配置返回 None；
    非法 JSON 抛 ValueError（与本模块 fail-fast 校验哲学一致，
    坏数据应在升级链路暴露而非静默吞掉）。
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_filter_config") from exc
    if not isinstance(config, dict) or not config.get("enabled"):
        return None
    return config


def _source_path(data_dir: Path, filename: str) -> Path:
    """定位源文件路径，缺失时抛 FileNotFoundError。"""
    path = Path(data_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(f"required metadata file is missing: {filename}")
    return path


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    """取文件身份指纹（设备号/inode/大小/修改时间/变更时间），用于快照一致性比对。"""
    status = path.stat()
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def read_source_snapshot(data_dir: Path) -> SourceSnapshot:
    """读取三个源文件的字节快照。

    读取前后各做一次文件身份比对，若期间文件被并发替换
    （例如 skills upgrade 原子替换元数据）则重试一次，
    仍不一致时抛 ValueError("metadata_snapshot_changed")。
    """
    paths = {
        filename: _source_path(Path(data_dir), filename) for filename in SOURCE_FILES
    }
    for _attempt in range(2):
        try:
            before = {name: _file_identity(path) for name, path in paths.items()}
            files = tuple((name, paths[name].read_bytes()) for name in SOURCE_FILES)
            after = {name: _file_identity(path) for name, path in paths.items()}
        except OSError:
            continue
        if before == after:
            return SourceSnapshot(files)
    raise ValueError("metadata_snapshot_changed")


def source_fingerprint(
    data_dir: Path,
    *,
    snapshot: SourceSnapshot | None = None,
) -> str:
    """计算三个源文件内容的稳定 SHA256 指纹（含文件名与长度前缀，防拼接歧义）。"""
    snapshot = snapshot or read_source_snapshot(data_dir)
    digest = hashlib.sha256()
    for filename in SOURCE_FILES:
        content = snapshot.content(filename)
        encoded_name = filename.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _read_rows(
    filename: str,
    content: bytes,
    required_columns: frozenset[str],
    *,
    selector_column: str | None = None,
    selector_value: str | None = None,
) -> list[dict]:
    """解析一个 CSV 的行数据并做结构校验。

    - 统一按 utf-8-sig 解码，兼容服务端导出的 BOM 文件头；
    - 校验表头非空、无空列名、无重复列、必需列齐全；
    - 行的列数必须与表头一致；
    - 传入 selector 时只保留指定列等于指定值的行（按数据集过滤）。
    """
    try:
        with io.TextIOWrapper(
            io.BytesIO(content), encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.reader(handle, strict=True)
            try:
                header = next(reader)
            except StopIteration as error:
                raise ValueError(f"{filename} has no header") from error
            if any(not name for name in header) or len(header) != len(set(header)):
                raise ValueError(f"{filename} has invalid columns")
            missing = required_columns.difference(header)
            if missing:
                raise ValueError(
                    f"{filename} missing required columns: {', '.join(sorted(missing))}"
                )
            selector_index = (
                header.index(selector_column) if selector_column is not None else None
            )
            rows = []
            for line_number, values in enumerate(reader, start=2):
                if len(values) != len(header):
                    raise ValueError(f"{filename} has an invalid row at line {line_number}")
                if (
                    selector_index is not None
                    and values[selector_index].strip() != selector_value
                ):
                    continue
                rows.append(dict(zip(header, values)))
            return rows
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"invalid CSV {filename}: {error}") from error


def _source_content(
    data_dir: Path,
    filename: str,
    snapshot: SourceSnapshot | None,
) -> bytes:
    """优先从快照取文件内容，没有快照时直接读盘。"""
    if snapshot is not None:
        return snapshot.content(filename)
    return _source_path(data_dir, filename).read_bytes()


def load_datasets(
    data_dir: Path,
    *,
    snapshot: SourceSnapshot | None = None,
) -> list[dict]:
    """加载并校验 datasets.csv。

    校验规则：数据集列表非空、dataset_alias 非空且全局唯一、
    dataset_category 只允许 normal（业务数据集）或 query_component（权限枚举组件）。
    """
    rows = _read_rows(
        "datasets.csv",
        _source_content(data_dir, "datasets.csv", snapshot),
        DATASET_COLUMNS,
    )
    if not rows:
        raise ValueError("authorized dataset metadata is empty")
    aliases = []
    for row in rows:
        alias = row["dataset_alias"].strip()
        if not alias:
            raise ValueError("empty dataset_alias in datasets.csv")
        if row["dataset_category"] not in {"normal", "query_component"}:
            raise ValueError("invalid dataset_category in datasets.csv")
        row["dataset_alias"] = alias
        aliases.append(alias)
    if len(aliases) != len(set(aliases)):
        raise ValueError("duplicate dataset_alias in datasets.csv")
    return rows


def load_dataset_fields(
    data_dir: Path,
    dataset_alias: str | None = None,
    *,
    snapshot: SourceSnapshot | None = None,
) -> list[dict]:
    """加载并校验 dataset_fields.csv（可按数据集别名过滤）。

    校验规则：
    - field_type 只允许 dimension / metric；
    - has_formula_config=1 的公式字段必须是 metric 且必须带汇总表达式；
      反之带表达式的字段必须标记为公式字段（防止公式配置漂移）；
    - snapshot_metric 只允许 空/0/1，空值视同 0（非快照指标）。
    """
    rows = _read_rows(
        "dataset_fields.csv",
        _source_content(data_dir, "dataset_fields.csv", snapshot),
        FIELD_COLUMNS,
        selector_column="dataset_alias" if dataset_alias is not None else None,
        selector_value=dataset_alias,
    )
    for row in rows:
        row["dataset_alias"] = row["dataset_alias"].strip()
        row["field_name"] = row["field_name"].strip()
        row["field_type"] = row["field_type"].strip().lower()
        if not row["dataset_alias"] or not row["field_name"]:
            raise ValueError("empty field identity in dataset_fields.csv")
        if row["field_type"] not in {"dimension", "metric"}:
            raise ValueError("invalid field_type in dataset_fields.csv")
        formula_flag = row["has_formula_config"]
        summary_expression = row["summary_expression"].strip()
        detail_expression = row["detail_expression"].strip()
        if formula_flag not in {"0", "1"}:
            raise ValueError("invalid_has_formula_config")
        if formula_flag == "1":
            # 公式字段：必须有汇总表达式，且业务上只可能是指标
            if not summary_expression:
                raise ValueError("formula_summary_expression_required")
            if row["field_type"] != "metric":
                raise ValueError("formula_field_must_be_metric")
        elif summary_expression or detail_expression:
            # 非公式字段却带表达式，说明元数据不一致，直接拒绝
            raise ValueError("formula_expression_without_flag")
        snapshot_flag = row["snapshot_metric"].strip()
        if snapshot_flag not in {"", "0", "1"}:
            raise ValueError("invalid_snapshot_metric")
        row["snapshot_metric"] = snapshot_flag or "0"
        # 字段级默认条件（可选列）：服务端 1.4.0+ 下发，旧 CSV 无此列时为 None
        row["filter_config"] = parse_filter_config(row.get("filter_config"))
    return rows


def load_select_columns(
    data_dir: Path,
    dataset_alias: str | None = None,
    *,
    snapshot: SourceSnapshot | None = None,
) -> list[dict]:
    """加载并校验 dataset_select_columns.csv（可按当前数据集别名过滤）。

    每行描述一个可筛选列与其权限枚举组件数据集的关系，三个标识列均不允许为空。
    """
    rows = _read_rows(
        "dataset_select_columns.csv",
        _source_content(data_dir, "dataset_select_columns.csv", snapshot),
        SELECT_COLUMNS,
        selector_column=(
            "current_dataset_alias" if dataset_alias is not None else None
        ),
        selector_value=dataset_alias,
    )
    for row in rows:
        for key in (
            "current_dataset_alias",
            "column_name",
            "component_dataset_alias",
        ):
            row[key] = row[key].strip()
            if not row[key]:
                raise ValueError(f"empty {key} in dataset_select_columns.csv")
    return rows
