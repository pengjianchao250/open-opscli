"""查询组件字段不能当分组维度的回归测试。

事故形态：select_columns（查询组件）里的字段——platform_name / asin / team_name
等——在 metadata 里可见，也确实是合法的**筛选**字段，但不在 fields 里，
因此不能进 dimensions。此前这种情况要么被放行到服务端换回一句
「dimension 字段不存在于当前数据集 metadata 中: platform_name」，
要么被客户端报成同样笼统的「字段不存在」。两种措辞都在暗示「换个字段名」，
而真正的解法是「把它从 dimensions 挪到 filters」。

线上 3987 条取数反馈里 497 条属字段类失败，其中 275 条正是这一形态
（反馈原文如「table_id=13 的 platform_name 仍仅可筛选不可分组」、
「query_simple rejects select_columns dimension asin」）。
"""

from __future__ import annotations

import pytest

from opscli.query.domain.exceptions import InvalidPayloadError
from opscli.query.services.manager import QueryManager

FIELDS = [
    {"field_name": "date_id", "verbose_name": "日期", "field_type": "dimension"},
    {"field_name": "price", "verbose_name": "销售额", "field_type": "metric"},
]
SELECT_COLUMNS = [
    {"column_name": "platform_name", "verbose_name": "平台"},
    {"column_name": "asin", "verbose_name": "ASIN"},
]


def _validate(dimensions, filters=None, fields=FIELDS):
    QueryManager.__new__(QueryManager)._validate_simple_fields(
        fields,
        dimensions=dimensions,
        metrics=[],
        filters=filters or [],
        data_comparison=None,
        select_columns=SELECT_COLUMNS,
    )


@pytest.mark.parametrize("field_name", ["platform_name", "asin"])
def test_select_column_as_dimension_is_rejected_with_the_real_reason(field_name: str):
    """报错必须点破「只能筛选不能分组」，并给出可执行的处理方式。"""
    with pytest.raises(InvalidPayloadError) as excinfo:
        _validate([{"field": field_name, "alias": field_name}])
    message = str(excinfo.value)
    assert "只能用于 filters 筛选" in message, f"仍是笼统措辞：{message}"
    assert "移到 filters" in message, "没有给出处理方式"


def test_genuinely_missing_field_keeps_the_original_message():
    """真不存在的字段仍报原来的「字段不存在」，两类错误不能混为一谈。"""
    with pytest.raises(InvalidPayloadError) as excinfo:
        _validate([{"field": "no_such_field", "alias": "x"}])
    message = str(excinfo.value)
    assert "字段不存在于当前数据集 metadata 中" in message
    assert "只能用于 filters 筛选" not in message


def test_select_column_as_filter_still_passes():
    """组件字段作为筛选条件是合法用法，不得被这条新校验误伤。"""
    _validate(
        [{"field": "date_id", "alias": "date_id"}],
        filters=[{"field": "platform_name", "operator": "=", "value": "Temu"}],
    )


def test_real_dimension_still_passes():
    """普通维度不受影响。"""
    _validate([{"field": "date_id", "alias": "date_id"}])


def test_component_only_dataset_rejects_dimension_early():
    """数据集只有组件字段、没有普通字段时，分组维度必须当场拒绝。

    此前这条路径直接 return，任何 dimension 都会被放行到服务端。
    """
    with pytest.raises(InvalidPayloadError) as excinfo:
        _validate([{"field": "platform_name", "alias": "p"}], fields=[])
    assert "只能用于 filters 筛选" in str(excinfo.value)


# ── groupable 能力位（服务端 dm_table_columns.groupby 的投影）────────────────
#
# 有些字段就在 fields 里，只是服务端把 groupby 关了——线上反馈原文：
# 「table_id=13 的 platform_name 仍仅可筛选不可分组」。
# select_columns 判据覆盖不到这一形态，必须靠 groupable 标志位。


def _validate_with(fields, dimensions):
    QueryManager.__new__(QueryManager)._validate_simple_fields(
        fields,
        dimensions=dimensions,
        metrics=[],
        filters=[],
        data_comparison=None,
        select_columns=[],
    )


def test_non_groupable_field_is_rejected_with_the_real_reason():
    """字段存在但 groupable=0 时，要说清是「不可分组」而不是「不存在」。"""
    fields = [
        {"field_name": "platform_name", "verbose_name": "平台",
         "field_type": "dimension", "groupable": 0, "filterable": 1},
    ]
    with pytest.raises(InvalidPayloadError) as excinfo:
        _validate_with(fields, [{"field": "platform_name", "alias": "p"}])
    message = str(excinfo.value)
    assert "不可分组" in message
    assert "只能用于 filters 筛选" in message


def test_groupable_field_passes():
    """groupable=1 的字段正常放行。"""
    _validate_with(
        [{"field_name": "date_id", "verbose_name": "日期",
          "field_type": "dimension", "groupable": 1}],
        [{"field": "date_id", "alias": "d"}],
    )


def test_metadata_without_groupable_key_is_treated_as_groupable():
    """老版本 metadata 没有 groupable 键时按可分组处理，升级前后不回退。"""
    _validate_with(
        [{"field_name": "date_id", "verbose_name": "日期", "field_type": "dimension"}],
        [{"field": "date_id", "alias": "d"}],
    )
