"""组件数据集查不到时必须指向真实成因的回归测试。

事故形态：query-metadata 会在每个数据集的 select_columns 里下发
component_dataset_alias，客户端与规划器据此枚举筛选项可选值（部门/团队/平台/渠道）。
但组件表是否在用户授权列表里取决于角色是否单独授予过——多数角色没有。
于是接口一边把 alias 发出去，一边又在按该 alias 查询时返回空集，
客户端只回一句「未找到目标数据集: ds_xxx」，调用方误以为自己写错了 alias，
反复改名重试。线上 3987 条取数反馈里这是单项量最大的根因（607 条 / 15.2% / 94 人）。
"""

from __future__ import annotations

import pytest

from opscli.query.services.manager import QueryManager

DATASETS = [
    {
        "table_id": 2,
        "dataset_alias": "ds_sales",
        "dataset_name": "sale_trend_set",
        "description": "发货数据集",
        "select_columns": [
            {"column_name": "team_name", "component_dataset_alias": "ds_team"},
            {"column_name": "platform_name", "component_dataset_alias": "ds_channel"},
        ],
    },
    {
        "table_id": 3,
        "dataset_alias": "ds_ads",
        "dataset_name": "ads_set",
        "description": "广告费数据集",
        "select_columns": [
            {"column_name": "team_name", "component_dataset_alias": "ds_team"},
        ],
    },
]


def _owners(needle: str):
    return QueryManager._component_owner_datasets(DATASETS, needle)


def test_component_alias_is_traced_back_to_its_owner_datasets():
    """能认出该 alias 是哪些已授权数据集下发的组件。"""
    assert _owners("ds_team") == ["发货数据集", "广告费数据集"]


def test_owner_is_listed_once_per_dataset():
    """同一数据集引用多次也只记一次。"""
    assert _owners("ds_channel") == ["发货数据集"]


@pytest.mark.parametrize("needle", ["ds_unknown", "", "   "])
def test_unrelated_alias_has_no_owner(needle: str):
    """与组件无关的标识不得被误判，避免把「真写错了」也说成权限问题。"""
    assert _owners(needle) == []


def test_missing_select_columns_is_tolerated():
    """数据集没有 select_columns 键时不报错。"""
    assert QueryManager._component_owner_datasets([{"dataset_alias": "ds_x"}], "ds_team") == []


def test_owner_falls_back_to_alias_when_no_chinese_name():
    """没有中文名时退回英文名/alias，保证提示里始终有可辨识的来源。"""
    datasets = [{
        "dataset_alias": "ds_x",
        "select_columns": [{"component_dataset_alias": "ds_team"}],
    }]
    assert QueryManager._component_owner_datasets(datasets, "ds_team") == ["ds_x"]
