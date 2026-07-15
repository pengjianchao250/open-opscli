"""scoped_dataset_reader 对字段 CSV filter_config 可选列的解析测试。"""
import json
import sys
from pathlib import Path

import pytest

# 与 test_dataset_query_planner.py 保持一致：将 scripts 目录注入 sys.path
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

import scoped_dataset_reader  # noqa: E402


FIELDS_HEADER = (
    "dataset_alias,dataset_name,field_name,verbose_name,field_type,"
    "summary_expression,detail_expression,snapshot_metric,has_formula_config,filter_config"
)
ENABLED_FC = json.dumps({
    "type": "required", "enabled": True, "operator": "equals",
    "filter_type": "enum", "enum_value": ["QUARTER"], "value": None, "filter_agg": "none",
})


def _write_fields_csv(data_dir, rows):
    data_dir.mkdir(parents=True, exist_ok=True)
    lines = [FIELDS_HEADER] + rows
    (data_dir / "dataset_fields.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 若 _source_content 的快照一致性校验要求三个源文件齐全，
    # 此处同时写入最小 datasets.csv / dataset_select_columns.csv（列头照抄 SOURCE 常量）


def test_parse_filter_config_enabled():
    result = scoped_dataset_reader.parse_filter_config(ENABLED_FC)
    assert result["type"] == "required"
    assert result["enum_value"] == ["QUARTER"]


def test_parse_filter_config_empty_and_disabled():
    assert scoped_dataset_reader.parse_filter_config("") is None
    assert scoped_dataset_reader.parse_filter_config(
        json.dumps({"enabled": False, "operator": "equals"})
    ) is None


def test_parse_filter_config_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid_filter_config"):
        scoped_dataset_reader.parse_filter_config("{not json")


def test_load_dataset_fields_attaches_filter_config(tmp_path):
    """带 filter_config 列的字段 CSV：启用行解析为 dict，空行为 None。"""
    fc_cell = '"' + ENABLED_FC.replace('"', '""') + '"'  # CSV 内嵌 JSON 转义
    _write_fields_csv(tmp_path, [
        f"ds_a,主数据集,date_type,日期类型,dimension,,,0,0,{fc_cell}",
        "ds_a,主数据集,gmv,GMV,metric,,,0,0,",
    ])
    rows = scoped_dataset_reader.load_dataset_fields(tmp_path, "ds_a")
    assert rows[0]["filter_config"]["type"] == "required"
    assert rows[1]["filter_config"] is None


def test_load_dataset_fields_without_column_is_compatible(tmp_path):
    """旧版 CSV 无 filter_config 列：所有行为 None，不报错（验收标准 12）。"""
    header = FIELDS_HEADER.rsplit(",", 1)[0]  # 去掉最后一列
    (tmp_path / "dataset_fields.csv").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "dataset_fields.csv").write_text(
        header + "\n" + "ds_a,主数据集,date_id,日期,dimension,,,0,0\n",
        encoding="utf-8",
    )
    rows = scoped_dataset_reader.load_dataset_fields(tmp_path, "ds_a")
    assert rows[0]["filter_config"] is None
