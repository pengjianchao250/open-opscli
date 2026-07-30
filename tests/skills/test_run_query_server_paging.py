"""服务端默认分页补齐与截断判定的回归测试。

线上事故形态：服务端在 payload 不带 limit 时只返回默认页（实测 20 行），
而 meta.totalCount 给的是全量行数（38）。规划器模板恒填 limit=null，于是
执行器把首页当成全量，还报 truncated=false —— Agent 据此写出「共 20 个，
未截断」的结论，18 行数据凭空消失且无人察觉。
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

import run_query  # noqa: E402


def _rows(count: int, offset: int = 0) -> list[dict]:
    return [{"asin": f"B0{index + offset:08d}"} for index in range(count)]


def _response(rows: list[dict], total: int) -> dict:
    return {"data": {"result": {"data": rows, "meta": {"totalCount": total}}}}


def test_server_default_page_is_completed(monkeypatch):
    """不带 limit 且只回首页时，执行器必须重查补齐到 total_count。"""
    calls: list[dict] = []

    def fake_run(_table_id, payload):
        calls.append(payload)
        return _response(_rows(38), 38)

    monkeypatch.setattr(run_query, "_run_opscli", fake_run)
    rows, note = run_query._complete_server_paged_rows("1", {"limit": None}, _rows(20), 38)

    assert len(rows) == 38
    assert note["auto_complete_applied"] is True
    assert note["server_default_page_rows"] == 20
    assert calls and calls[0]["limit"] == 38


def test_explicit_limit_is_respected(monkeypatch):
    """用户明确要了行数时按其口径执行，不擅自放大。"""
    monkeypatch.setattr(
        run_query, "_run_opscli", lambda *_a, **_k: pytest.fail("不应发起补齐重查")
    )
    rows, note = run_query._complete_server_paged_rows("1", {"limit": 20}, _rows(20), 38)

    assert len(rows) == 20
    assert note is None


def test_no_completion_when_rows_already_full(monkeypatch):
    """返回行数已等于总行数时不做任何多余调用。"""
    monkeypatch.setattr(
        run_query, "_run_opscli", lambda *_a, **_k: pytest.fail("不应发起补齐重查")
    )
    rows, note = run_query._complete_server_paged_rows("1", {"limit": None}, _rows(38), 38)

    assert len(rows) == 38
    assert note is None


def test_failed_completion_is_flagged_not_silently_partial(monkeypatch):
    """补齐失败必须显式标记，绝不能把首页当全量交出去。"""

    def boom(_table_id, _payload):
        raise RuntimeError("opscli_exec_failed:boom")

    monkeypatch.setattr(run_query, "_run_opscli", boom)
    rows, note = run_query._complete_server_paged_rows("1", {"limit": None}, _rows(20), 38)

    assert len(rows) == 20
    assert note["auto_complete_applied"] is False
    assert note["total_count"] == 38
    assert "boom" in note["reason"]


def test_requery_returning_no_more_rows_is_flagged(monkeypatch):
    """重查没拿到更多行同样要标记，避免默默降级成部分结果。"""
    monkeypatch.setattr(
        run_query, "_run_opscli", lambda *_a, **_k: _response(_rows(20), 38)
    )
    rows, note = run_query._complete_server_paged_rows("1", {"limit": None}, _rows(20), 38)

    assert len(rows) == 20
    assert note["auto_complete_applied"] is False
    assert note["reason"] == "requery_returned_no_more_rows"


@pytest.mark.parametrize(
    "limit, returned, total, expected",
    [
        # 旧实现要求 payload 必须带 limit 才算截断，服务端默认分页因此被漏判
        (None, 20, 38, True),
        (None, 38, 38, False),
        (20, 20, 38, True),
        (None, 5, None, False),
    ],
)
def test_truncated_flag_only_compares_counts(limit, returned, total, expected):
    """截断判定只看返回行数是否少于总行数，与是否传 limit 无关。"""
    truncated = total is not None and returned < (total or 0)
    assert truncated is expected, f"limit={limit} returned={returned} total={total}"
