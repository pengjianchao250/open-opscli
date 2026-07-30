"""同一值同属多个字段授权枚举时不得静默绑定的回归测试。

碰撞扫描在本账号真实枚举里找到 10 个同值跨字段的情形：
  产品型号 ∩ SPU      8 个（bkc-102/bkc-107/cot-102/cot-114/cot-165/mks-111/tv-101/tv-140）
  渠道SKU  ∩ 公司SKU  2 个（usan1088833、usan1077714）

原先裸值按 _ENUM_COMPONENT_SPECS 顺序静默绑到靠前的字段（实测
「查BKC-107的近7天销量」绑到 model）。危险点在于：值在错字段里同样是合法枚举值，
完整等值校验不会报错，因此没有任何 fail-closed 兜底——用户拿到的是另一个字段口径
的数据且无从察觉。

修复语义：只对裸值判歧义（标签形态已由字段名确定，「产品型号是BKC-107」与
「SPU是BKC-107」实测各自正确），检测到多字段命中即转澄清并列出候选字段。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_plan  # noqa: E402

# 伪造的组件枚举：值 → 字段归属，覆盖两组真实碰撞对
FAKE_ENUMS = {
    "model": ["BKC-107", "BSB-156-RU-155"],
    "spu": ["BKC-107", "BSB-217"],
    "sell_sku": ["USAN1088833", "ON-OB-JL-007-68157"],
    "ed_sku": ["USAN1088833", "QD1085997"],
    "pmc_code": ["12.3456"],
}


@pytest.fixture
def stubbed(monkeypatch):
    """把组件查找与枚举替换成本地桩，避免测试依赖真实网络（铁律8）。"""

    def fake_lookup(_execution, field_name, _data_dir):
        return {"component_table_id": f"t_{field_name}"} if field_name in FAKE_ENUMS else None

    def fake_enum(_cache, table_id, field_name, errors=None):
        return list(FAKE_ENUMS.get(field_name) or [])

    monkeypatch.setattr(query_plan, "_lookup_component", fake_lookup)
    monkeypatch.setattr(query_plan, "_cached_enum_values", fake_enum)


def _spec(field_name: str) -> dict:
    return next(
        item for item in query_plan._ENUM_COMPONENT_SPECS if item["field_name"] == field_name
    )


@pytest.mark.parametrize(
    "owner, value, expected",
    [
        ("model", "BKC-107", {"产品型号", "SPU"}),
        ("spu", "BKC-107", {"产品型号", "SPU"}),
        ("sell_sku", "USAN1088833", {"渠道SKU", "公司SKU"}),
        ("ed_sku", "USAN1088833", {"渠道SKU", "公司SKU"}),
    ],
)
def test_shared_value_lists_all_candidate_fields(stubbed, owner, value, expected):
    """同值必须列出全部候选字段，且与从哪个字段进来无关。"""
    labels = query_plan._cross_field_candidates(_spec(owner), value, {}, None, {})

    assert set(labels) == expected
    assert labels[0] == _spec(owner)["label_zh"], "首个候选应是当前字段，用于给出示例话术"


@pytest.mark.parametrize(
    "owner, value",
    [
        ("model", "BSB-156-RU-155"),      # 只属产品型号
        ("spu", "BSB-217"),               # 只属 SPU
        ("sell_sku", "ON-OB-JL-007-68157"),  # 只属渠道SKU
        ("ed_sku", "QD1085997"),          # 只属公司SKU
    ],
)
def test_unique_value_is_not_flagged(stubbed, owner, value):
    """只属单一字段的值不得被误判为歧义。"""
    labels = query_plan._cross_field_candidates(_spec(owner), value, {}, None, {})

    assert labels == [_spec(owner)["label_zh"]]


def test_check_scope_is_not_narrowed_by_pattern(stubbed):
    """检查范围不能按"形态是否命中该值"缩小。

    渠道SKU 的形态要求三段连字符，匹配不上 USAN1088833；若按形态缩范围，
    这一对碰撞会漏检（第一版实现就漏了，实测才发现）。
    """
    assert not any(
        __import__("re").search(_spec("sell_sku")["value_pattern"], "USAN1088833")
        for _ in [0]
    ), "前提变了：渠道SKU 形态已能命中该值"

    labels = query_plan._cross_field_candidates(_spec("ed_sku"), "USAN1088833", {}, None, {})
    assert "渠道SKU" in labels


def test_fields_without_pattern_are_skipped(stubbed):
    """无编码形态的字段（渠道/部门等）不参与该检查，避免为每个裸值扫全部组件。"""
    labels = query_plan._cross_field_candidates(_spec("model"), "BKC-107", {}, None, {})

    assert "渠道" not in labels
    assert "部门" not in labels
