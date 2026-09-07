"""组件枚举值本地磁盘缓存的回归测试（TTL 24h + 超时/失败降级兜底）。

守住的核心行为：规划器的权限枚举依赖一次同步网络调用，网络抖动或服务端短暂
不可用时若无兜底会直接 fail-closed 阻断所有依赖枚举的查询。本文件覆盖：
1. enum_cache 模块自身：put→get 命中、过期不命中、损坏文件安全返回 None、
   文件名安全化。
2. entry.py 的 enum_fn：实时枚举异常时降级读缓存，并把缓存年龄透出，
   最终由 run_plan 把"来自缓存"披露写进 model_view。

历史说明：本文件原先同时对拍 Skill 版与内核版；Skill 本地规划器移除后，
Skill 侧三处枚举调用（走 subprocess 调 opscli）的用例一并删除，只保留内核半边。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from opscli.query.services.planner import enum_cache, plan_integrity, entry


# ── 1. enum_cache 模块自身 ────────────────────────────────────────────────


def test_put_then_get_hit(tmp_path):
    enum_cache.put(7, "channel_name", ["傲彼瑞-美国", "傲彼瑞-加拿大"], base_dir=tmp_path)
    assert enum_cache.get(7, "channel_name", base_dir=tmp_path) == [
        "傲彼瑞-美国",
        "傲彼瑞-加拿大",
    ]


def test_get_miss_when_never_written(tmp_path):
    assert enum_cache.get(999, "no_such_field", base_dir=tmp_path) is None


def test_expired_entry_is_miss(tmp_path):
    """写入后手动改写 fetched_at 到 25 小时前（TTL 24h），过期即不命中。"""
    enum_cache.put(7, "channel_name", ["傲彼瑞-美国"], base_dir=tmp_path)
    path = Path(enum_cache._cache_path(7, "channel_name", tmp_path))

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] = time.time() - 25 * 3600
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert enum_cache.get(7, "channel_name", base_dir=tmp_path) is None


def test_corrupt_file_returns_none(tmp_path):
    """缓存文件损坏（非 JSON）时安全返回 None，不抛异常。"""
    path = Path(enum_cache._cache_path(7, "channel_name", tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a json {{{", encoding="utf-8")
    assert enum_cache.get(7, "channel_name", base_dir=tmp_path) is None


def test_empty_values_are_not_written(tmp_path):
    """空列表不落盘，避免把"暂无授权值"误当成可复用的缓存。"""
    enum_cache.put(7, "channel_name", [], base_dir=tmp_path)
    assert enum_cache.get(7, "channel_name", base_dir=tmp_path) is None


def test_get_age_hours_reports_recent_write_as_near_zero(tmp_path):
    enum_cache.put(7, "channel_name", ["傲彼瑞-美国"], base_dir=tmp_path)
    age = enum_cache.get_age_hours(7, "channel_name", base_dir=tmp_path)
    assert age is not None
    assert 0 <= age < 0.01


def test_field_name_with_path_separators_is_sanitized(tmp_path):
    """field_name 含路径分隔符时不得逃逸出缓存目录（安全化处理）。"""
    enum_cache.put(7, "../../etc/passwd", ["evil"], base_dir=tmp_path)
    path = Path(enum_cache._cache_path(7, "../../etc/passwd", tmp_path)).resolve()
    cache_root = Path(str(tmp_path)).resolve()
    assert cache_root in path.parents
    # 安全化后仍可正常按同一 field_name 读回
    assert enum_cache.get(7, "../../etc/passwd", base_dir=tmp_path) == ["evil"]


# ── 2. entry.py 的 enum_fn：超时/失败降级读缓存 ────────────────────────────


def test_kernel_enum_fn_falls_back_to_cache_on_exception(tmp_path):
    """entry._make_callbacks 的 enum_fn：实时枚举异常时命中本地缓存则降级返回。"""
    enum_cache.put(7, "platform_name", ["Amazon"], base_dir=tmp_path)

    class _FakeQM:
        def build_simple_and_run(self, **kwargs):
            raise RuntimeError("网络异常")

    refresh_fn, enum_fn, stale_hits = entry._make_callbacks(_FakeQM(), "u@x.com", tmp_path)
    values = enum_fn(7, "platform_name", limit=100)
    assert values == ["Amazon"]
    assert stale_hits and stale_hits[0] >= 0


def test_kernel_enum_fn_reraises_when_no_cache(tmp_path):
    """无缓存兜底时 enum_fn 原样把异常抛给上层，维持现行 fail-closed 行为。"""

    class _FakeQM:
        def build_simple_and_run(self, **kwargs):
            raise RuntimeError("网络异常")

    refresh_fn, enum_fn, stale_hits = entry._make_callbacks(_FakeQM(), "u@x.com", tmp_path)
    with pytest.raises(RuntimeError):
        enum_fn(7, "platform_name", limit=100)
    assert stale_hits == []


def test_kernel_enum_fn_success_writes_cache(tmp_path):
    """实时枚举成功时写入本地缓存（内核版），供下次异常时降级复用。"""

    class _FakeQM:
        def build_simple_and_run(self, **kwargs):
            return {"result": {"success": True, "data": [{"platform_name": "Amazon"}]}}

    refresh_fn, enum_fn, stale_hits = entry._make_callbacks(_FakeQM(), "u@x.com", tmp_path)
    values = enum_fn(7, "platform_name", limit=100)
    assert values == ["Amazon"]
    assert enum_cache.get(7, "platform_name", base_dir=tmp_path) == ["Amazon"]


def test_run_plan_attaches_stale_cache_disclosure(tmp_path, monkeypatch):
    """run_plan：本次调用中 enum_fn 命中缓存降级时，在 model_view 追加中文披露。"""
    enum_cache.put(7, "platform_name", ["Amazon"], base_dir=tmp_path)

    def fake_build_model_query_plan(
        adapter, request, *, requested_fields, refresh_fn, enum_fn, **kwargs
    ):
        # 模拟规划器内部真实发生的一次枚举调用：实时失败触发缓存降级
        enum_fn(7, "platform_name", limit=100)
        # 模拟 planned 合同：规划器在返回前已挂好完整性摘要
        return plan_integrity.attach(
            {
                "contract": "query_plan_model_contract_v2",
                "status": "planned",
                "model_view": {},
                "execution_ref": {"query_template": {"tableId": 7}},
            }
        )

    monkeypatch.setattr(entry.query_plan, "build_model_query_plan", fake_build_model_query_plan)

    class _QM:
        def metadata_all(self, *, user_email, base_dir):
            class _Result:
                payload = {"datasets": [], "fields": []}

            return _Result()

        def build_simple_and_run(self, **kwargs):
            raise RuntimeError("网络异常")

    contract = entry.run_plan(
        "查询", user_email="u@x.com", base_dir=tmp_path, query_manager=_QM()
    )
    disclosures = contract["model_view"]["component_filter_disclosures_zh"]
    assert any("小时前本地缓存" in item for item in disclosures)
    # 追加披露改写了 model_view，摘要必须随之重挂，否则多币种 run_flow 的完整性校验
    # 会把这份合同判为"被篡改"而拒绝执行（实测：Privoxy 抖动触发缓存降级后必现）
    assert plan_integrity.verify(contract)
