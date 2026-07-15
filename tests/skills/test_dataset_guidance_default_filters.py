"""dataset_guidance 默认条件聚合测试（R5）。

测试 build_guidance() 返回体顶层 default_filters 键的聚合行为：
- 自身字段中 filter_config 已启用的条目；
- select_columns 关联的组件数据集字段中 filter_config 已启用的条目；
- 未配置 filter_config 的数据集返回空列表。
"""
import json
import sys
from pathlib import Path

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

import dataset_guidance  # noqa: E402

# filter_config 启用行（内嵌 JSON 须按 CSV 规范双引号转义）
_ENABLED_FC = json.dumps({
    "type": "required",
    "enabled": True,
    "operator": "equals",
    "filter_type": "enum",
    "enum_value": ["QUARTER"],
    "value": None,
    "filter_agg": "none",
})

# CSV 单元格转义：外层加双引号，内部双引号变为两个双引号
_FC_CELL = '"' + _ENABLED_FC.replace('"', '""') + '"'

# dataset_fields.csv 含 filter_config 列的表头（与 Task 2 的 FIELDS_HEADER 对齐）
_FIELDS_HEADER_WITH_FC = (
    "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
    "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config,filter_config"
)

# dataset_fields.csv 不含 filter_config 列的旧格式表头（向后兼容验证）
_FIELDS_HEADER_NO_FC = (
    "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
    "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config"
)


def _write_metadata_with_filter_config(tmp_path: Path) -> Path:
    """写入带 filter_config 配置的测试元数据：
    - ds_a 自身字段 date_type 配置了 required 默认条件；
    - ds_comp 的 platform_name 字段配置了 required 默认条件；
    - ds_a 通过 select_columns 关联 platform_name → ds_comp。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # VERSION.json：data_state=ready 标记元数据就绪
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.4.0", "data_state": "ready"}),
        encoding="utf-8",
    )

    # datasets.csv：主数据集 ds_a + 组件数据集 ds_comp
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_a,主数据集,normal,0,主数据集说明,\n"
        "2,ds_comp,组件数据集,normal,0,平台枚举组件,\n",
        encoding="utf-8",
    )

    # dataset_fields.csv：含 filter_config 列
    # ds_a.date_type：启用默认条件（QUARTER）；ds_a.gmv：无默认条件
    # ds_comp.platform_name：启用默认条件（QUARTER）；ds_comp.region：无默认条件
    (data_dir / "dataset_fields.csv").write_text(
        _FIELDS_HEADER_WITH_FC + "\n"
        f"1,ds_a,主数据集,date_type,日期类型,f_date_type,dimension,,,,,0,0,{_FC_CELL}\n"
        "1,ds_a,主数据集,gmv,GMV,f_gmv,metric,,,,,0,0,\n"
        f"2,ds_comp,组件数据集,platform_name,平台名称,f_pn,dimension,,,,,0,0,{_FC_CELL}\n"
        "2,ds_comp,组件数据集,region,地区,f_region,dimension,,,,,0,0,\n",
        encoding="utf-8",
    )

    # dataset_select_columns.csv：ds_a 关联 ds_comp 的 platform_name
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_a,platform_name,平台名称,ds_comp\n",
        encoding="utf-8",
    )

    return data_dir


def _write_metadata_without_filter_config(tmp_path: Path) -> Path:
    """写入不带任何 filter_config 配置的测试元数据（旧格式，无 filter_config 列）。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.3.0", "data_state": "ready"}),
        encoding="utf-8",
    )

    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_a,主数据集,normal,0,主数据集说明,\n",
        encoding="utf-8",
    )

    # 旧格式：无 filter_config 列
    (data_dir / "dataset_fields.csv").write_text(
        _FIELDS_HEADER_NO_FC + "\n"
        "1,ds_a,主数据集,date_type,日期类型,f_date_type,dimension,,,,,0,0\n"
        "1,ds_a,主数据集,gmv,GMV,f_gmv,metric,,,,,0,0\n",
        encoding="utf-8",
    )

    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n",
        encoding="utf-8",
    )

    return data_dir


def test_build_guidance_collects_default_filters(tmp_path):
    """build_guidance 应在返回体顶层包含 default_filters 键，聚合自身字段与组件关联字段的默认条件。"""
    data_dir = _write_metadata_with_filter_config(tmp_path)
    result = dataset_guidance.build_guidance(
        data_dir, {"dataset_alias": "ds_a"}, query="按日期看GMV"
    )
    defaults = result["default_filters"]
    by_name = {item["field_name"]: item for item in defaults}
    # 自身字段：ds_a.date_type 配置了 required 默认条件
    assert by_name["date_type"]["source_dataset_alias"] == "ds_a"
    assert by_name["date_type"]["filter_config"]["enum_value"] == ["QUARTER"]
    # 组件关联字段：ds_comp.platform_name 通过 select_columns 关联，配置了 required 默认条件
    assert by_name["platform_name"]["source_dataset_alias"] == "ds_comp"
    # 六键压缩契约：filter_config 不得携带 enabled 键（下游 query_plan 依赖此形态）
    fc = by_name["date_type"]["filter_config"]
    assert "enabled" not in fc
    assert set(fc) <= {"type", "operator", "filter_type", "enum_value", "value", "filter_agg"}


def test_build_guidance_default_filters_empty_when_unconfigured(tmp_path):
    """未配置任何 filter_config 的数据集，default_filters 应返回空列表。"""
    data_dir = _write_metadata_without_filter_config(tmp_path)
    result = dataset_guidance.build_guidance(
        data_dir, {"dataset_alias": "ds_a"}, query="按日期看GMV"
    )
    assert result["default_filters"] == []
