"""_validated_dataset_fields 对整行完全重复字段行的自愈能力测试。

背景：2026-08-11/12 元数据事故，服务端偶发下发整行完全重复的字段行，两天内
在 _validated_dataset_fields 的硬失败上打出 69 条 blocked。整行完全重复
（含 filter_config 等全部列都相同）的字段定义没有歧义，应静默去重放行；
同名但定义不同（如 summary_expression 口径不同）去重会静默选中其中一个口径，
属于数据错误，仍须维持阻断。
"""
import sys
from pathlib import Path

import pytest

# 与 test_scoped_reader_duplicate_fields.py 保持一致：将 scripts 目录注入 sys.path
SKILL_ROOT = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import dataset_guidance  # noqa: E402


def test_fully_duplicate_rows_are_self_healed():
    """整行完全重复（2026-08-11 事故形态）应静默去重通过，而不是 blocked。"""
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "qty",
            "field_type": "metric",
            "summary_expression": "",
        },
    ]
    selected = dataset_guidance._validated_dataset_fields(
        rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}
    )
    assert [r["field_name"] for r in selected] == ["sales", "qty"]


def test_same_name_different_definition_still_blocks():
    """同名不同定义去重会静默选错口径，必须维持阻断。"""
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(b)",
        },
    ]
    with pytest.raises(ValueError, match="duplicate_dataset_field"):
        dataset_guidance._validated_dataset_fields(
            rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}
        )


def test_duplicate_rows_deduped_count_surfaces_via_advisory():
    """去重条数需通过 advisory 出参带给调用方，供上层向用户披露。"""
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "summary_expression": "SUM(a)",
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "qty",
            "field_type": "metric",
            "summary_expression": "",
        },
    ]
    advisory: dict = {}
    dataset_guidance._validated_dataset_fields(
        rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}, advisory
    )
    assert advisory["duplicate_fields_deduped_count"] == 1


def test_dict_valued_column_does_not_break_dedup():
    """字段行含 filter_config 这类 dict/None 混合列时，去重不得因不可哈希而报错。

    真实字段行（MetadataAdapter.fields_rows / scoped_dataset_reader）都带
    filter_config 列，取值为 dict 或 None；tuple(sorted(row.items())) 式的
    去重键在遇到 dict 值时会因不可哈希而抛 TypeError，必须改用可序列化的键。
    """
    rows = [
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "filter_config": {"type": "enum", "enabled": True},
        },
        {
            "dataset_alias": "ds_x",
            "dataset_name": "表X",
            "field_name": "sales",
            "field_type": "metric",
            "filter_config": {"type": "enum", "enabled": True},
        },
    ]
    selected = dataset_guidance._validated_dataset_fields(
        rows, {"dataset_alias": "ds_x", "dataset_name": "表X"}
    )
    assert len(selected) == 1
