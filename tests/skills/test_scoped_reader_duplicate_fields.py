"""scoped_dataset_reader 对同名字段重复注册的兼容性合并测试。

背景：BI 发布包 dataset_fields.csv 中同一物理字段可能挂多个全局别名
（2026-07-15 实测即时综合数据集 44 个字段双注册），曾令下游
duplicate_dataset_field 硬失败、整个数据集不可查且升级无法自愈。
"""
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

import dataset_guidance  # noqa: E402
import scoped_dataset_reader  # noqa: E402


FIELDS_HEADER = (
    "dataset_alias,dataset_name,field_name,verbose_name,field_type,"
    "summary_expression,detail_expression,snapshot_metric,has_formula_config"
)


def _write_fields_csv(data_dir: Path, rows: list[str]) -> Path:
    """写入最小 dataset_fields.csv 测试夹具。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "dataset_fields.csv").write_text(
        "\n".join([FIELDS_HEADER] + rows) + "\n", encoding="utf-8"
    )
    return data_dir


def test_label_only_duplicate_merged_with_alt_names(tmp_path):
    """形态一：纯标签差异的双注册合并为一行，中文展示名优先，旧标签进 alt。"""
    data_dir = _write_fields_csv(
        tmp_path,
        [
            # 英文占位标签的旧注册在前，中文标签注册在后 → 主行仍应取中文标签
            "ds_a,set_a,development_type,development_type,dimension,,,0,0",
            "ds_a,set_a,development_type,开发类型,dimension,,,0,0",
        ],
    )
    rows = scoped_dataset_reader.load_dataset_fields(data_dir, "ds_a")
    assert len(rows) == 1
    assert rows[0]["verbose_name"] == "开发类型"
    assert rows[0]["alt_verbose_names"] == ["development_type"]


def test_formula_vs_plain_duplicate_prefers_formula(tmp_path):
    """形态二：公式 vs 裸指标双注册优先采纳公式口径（均值/比率不可再累加）。"""
    data_dir = _write_fields_csv(
        tmp_path,
        [
            "ds_a,set_a,avg_price_cny,销售价,metric,,,0,0",
            (
                "ds_a,set_a,avg_price_cny,平均交易价,metric,"
                '"ROUND(SUM(price) / SUM(order_qty), 4)",'
                '"ROUND(price / order_qty, 4)",0,1'
            ),
        ],
    )
    rows = scoped_dataset_reader.load_dataset_fields(data_dir, "ds_a")
    assert len(rows) == 1
    assert rows[0]["has_formula_config"] == "1"
    assert rows[0]["verbose_name"] == "平均交易价"
    # 裸注册的旧标签保留为备选名，供点名解析与打分识别
    assert rows[0]["alt_verbose_names"] == ["销售价"]


def test_conflicting_duplicate_kept_for_downstream_hard_fail(tmp_path):
    """形态外冲突（维度 vs 指标）不合并，下游唯一性校验仍硬失败。"""
    data_dir = _write_fields_csv(
        tmp_path,
        [
            "ds_a,set_a,mixed_field,标签甲,dimension,,,0,0",
            "ds_a,set_a,mixed_field,标签乙,metric,,,0,0",
        ],
    )
    rows = scoped_dataset_reader.load_dataset_fields(data_dir, "ds_a")
    assert len(rows) == 2
    with pytest.raises(ValueError, match="duplicate_dataset_field"):
        dataset_guidance._validated_dataset_fields(
            rows, {"dataset_alias": "ds_a", "dataset_name": "set_a"}
        )


def test_identical_duplicate_rows_deduplicated(tmp_path):
    """完全相同的重复行静默去重（发布管线幂等导出的兜底）。"""
    data_dir = _write_fields_csv(
        tmp_path,
        [
            "ds_a,set_a,channel_name,渠道,dimension,,,0,0",
            "ds_a,set_a,channel_name,渠道,dimension,,,0,0",
        ],
    )
    rows = scoped_dataset_reader.load_dataset_fields(data_dir, "ds_a")
    assert len(rows) == 1
    assert "alt_verbose_names" not in rows[0]


def test_alt_labels_participate_in_matching():
    """打分与点名解析覆盖 alt_verbose_names（旧标签查询不丢命中）。"""
    field = {
        "field_name": "price_ds",
        "verbose_name": "销售额(自发货)",
        "alt_verbose_names": ["交易额(自发货)"],
    }
    query = dataset_guidance._normalize("近7天交易额(自发货)按渠道汇总")
    score = dataset_guidance._field_score(field, query, dataset_guidance._tokens(query))
    assert score >= 90
    selected, unknown = dataset_guidance._resolve_requested_fields(
        [field], ["交易额(自发货)"]
    )
    assert selected == {"price_ds"}
    assert unknown == []


def test_ambiguous_alt_label_triggers_clarification():
    """同一旧标签挂在多个字段上时点名进入澄清而非静默择一。"""
    fields = [
        {
            "field_name": "avg_price_cny",
            "verbose_name": "平均交易价",
            "alt_verbose_names": ["销售价"],
        },
        {
            "field_name": "avg_original_price_cny",
            "verbose_name": "平均原价",
            "alt_verbose_names": ["销售价"],
        },
    ]
    selected, unknown = dataset_guidance._resolve_requested_fields(fields, ["销售价"])
    assert selected == set()
    assert unknown == ["销售价"]


def test_requested_field_preserves_case_sensitive_technical_identity():
    """同表 SPU/spu 技术字段先按原始大小写精确匹配，不被 casefold 合并。"""
    fields = [
        {"field_name": "SPU", "verbose_name": "SPU"},
        {"field_name": "spu", "verbose_name": "spu"},
    ]
    assert dataset_guidance._resolve_requested_fields(fields, ["SPU"]) == ({"SPU"}, [])
    assert dataset_guidance._resolve_requested_fields(fields, ["spu"]) == ({"spu"}, [])


def test_exact_label_precedes_casefolded_technical_name():
    """VCPM 展示名精确命中优先于另一字段 vcpm 的大小写不敏感技术名。"""
    fields = [
        {"field_name": "vcpm", "verbose_name": "VCPM(原币)"},
        {"field_name": "vcpm_cny", "verbose_name": "VCPM"},
    ]
    assert dataset_guidance._resolve_requested_fields(fields, ["VCPM"]) == (
        {"vcpm_cny"},
        [],
    )
    assert dataset_guidance._resolve_requested_fields(fields, ["vcpm"]) == ({"vcpm"}, [])
