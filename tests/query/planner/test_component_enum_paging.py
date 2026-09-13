"""组件权限枚举分页的回归测试。

事故形态：品类有 1799 个授权值，枚举默认先取 500 行。首页里混有空值和
「 转接头」这类去空白后重复的值，去重后只剩 499 个，旧逻辑按去重后的条数
判断"未取满"，于是只核对了前 499 个品类，「家居」被判查无此值。
取满必须按服务端原始返回行数判断；判断放在能看到原始行的 enum_fn 里，
规划器内层不再二次扩页（原先点名高基数值时会连发 500、5000、5000 三次）。
"""

from __future__ import annotations

from pathlib import Path

from opscli.query.services.planner import entry, query_plan


class _FakeManager:
    """按请求 limit 返回行的假 QueryManager，只实现 enum_fn 用到的方法。"""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.limits: list[int] = []

    def build_simple_and_run(self, *, table_id, dimensions, limit):  # noqa: ARG002
        self.limits.append(limit)
        return {"result": {"success": True, "data": self.rows[:limit]}}


def _category_rows() -> list[dict]:
    # 首页 500 行里含一个空值和一个去空白后与已有值重复的值
    rows = [{"category": ""}, {"category": " 转接头"}, {"category": "转接头"}]
    rows += [{"category": f"品类{index:04d}"} for index in range(1796)]
    rows.append({"category": "家居"})
    return rows


def test_full_raw_page_expands_even_when_distinct_values_fall_short(tmp_path: Path):
    """原始行数取满即放大上限重取，不受去空去重后条数的影响。"""
    manager = _FakeManager(_category_rows())
    _refresh_fn, enum_fn, _stale = entry._make_callbacks(manager, "user@example.com", tmp_path)

    values = enum_fn(9, "category", limit=500)

    assert manager.limits == [500, entry._ENUM_EXPANDED_LIMIT]
    assert "家居" in values
    assert values.count("转接头") == 1
    assert "" not in values


def test_small_component_uses_single_call(tmp_path: Path):
    """取不满首页的小基数字段只调用一次。"""
    manager = _FakeManager([{"platform_name": f"平台{index}"} for index in range(27)])
    _refresh_fn, enum_fn, _stale = entry._make_callbacks(manager, "user@example.com", tmp_path)

    values = enum_fn(7, "platform_name", limit=500)

    assert manager.limits == [500]
    assert len(values) == 27


def test_planner_does_not_expand_again_after_enum_fn():
    """规划器内层拿到的是完整取值，不再按条数二次扩页。"""
    limits: list[int] = []

    def enum_fn(_table_id, _field_name, *, limit):
        limits.append(limit)
        return [f"值{index}" for index in range(1799)]

    values = query_plan._auto_enum_component_values(enum_fn, 9, "category")

    assert limits == [500]
    assert len(values) == 1799


def test_planner_retries_once_on_enum_error():
    """枚举偶发异常时内部重试一次，第二次成功即返回。"""
    attempts: list[int] = []

    def enum_fn(_table_id, _field_name, *, limit):  # noqa: ARG001
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("代理抖动")
        return ["家居"]

    errors: list[str] = []
    values = query_plan._auto_enum_component_values(enum_fn, 9, "category", errors)

    assert values == ["家居"]
    assert len(attempts) == 2
    assert errors == []
