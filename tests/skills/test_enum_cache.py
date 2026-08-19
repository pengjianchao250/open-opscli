"""组件枚举值本地磁盘缓存的回归测试（TTL 24h + 超时/失败降级兜底）。

守住的核心行为：规划器的权限枚举依赖一次同步网络调用，网络抖动或服务端短暂
不可用时若无兜底会直接 fail-closed 阻断所有依赖枚举的查询。本文件覆盖：
1. enum_cache 模块自身（Skill 版 + 内核版）：put→get 命中、过期不命中、
   损坏文件安全返回 None、文件名安全化。
2. Skill 侧三处枚举调用（_auto_enum_platform_values /
   _auto_enum_component_values / _auto_enum_component_field_group）：
   实时枚举超时/失败后正确降级读缓存，并把缓存年龄透出供披露文案使用；
   缓存也未命中时维持现行失败路径（行为不回归）。
3. 内核侧 entry.py 的 enum_fn：同样的降级语义，通过 run_plan 校验最终会把
   "来自缓存"披露写进 model_view。

Skill 版与内核版同源，逐条对齐；两版实现细节不同（Skill 版不能 import opscli
包，用 monkeypatch 隔离缓存目录；内核版原生支持 base_dir 参数隔离），
测试分别使用各自的隔离方式，但断言的行为完全一致。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

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

import enum_cache as skill_enum_cache  # noqa: E402
import query_plan as skill_query_plan  # noqa: E402

from opscli.query.services.planner import enum_cache as kernel_enum_cache  # noqa: E402
from opscli.query.services.planner import entry  # noqa: E402


# ── 1. enum_cache 模块自身：Skill 版 + 内核版 ──────────────────────────────


@pytest.fixture
def skill_cache(tmp_path, monkeypatch):
    """把 Skill 版 enum_cache 的缓存目录隔离到 tmp_path，避免读写真实主目录。"""
    monkeypatch.setattr(skill_enum_cache, "_cache_dir", lambda: str(tmp_path))
    return skill_enum_cache


class _KernelCacheAdapter:
    """内核版 enum_cache 原生支持 base_dir 隔离，包一层与 Skill 版测试同接口。"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def get(self, table_id, field_name):
        return kernel_enum_cache.get(table_id, field_name, base_dir=self._base_dir)

    def get_age_hours(self, table_id, field_name):
        return kernel_enum_cache.get_age_hours(table_id, field_name, base_dir=self._base_dir)

    def put(self, table_id, field_name, values):
        kernel_enum_cache.put(table_id, field_name, values, base_dir=self._base_dir)

    def _cache_path(self, table_id, field_name):
        return kernel_enum_cache._cache_path(table_id, field_name, self._base_dir)


@pytest.fixture
def kernel_cache(tmp_path):
    return _KernelCacheAdapter(tmp_path)


BOTH_CACHES = pytest.mark.parametrize("cache_fixture", ["skill_cache", "kernel_cache"])


@BOTH_CACHES
def test_put_then_get_hit(cache_fixture, request):
    cache = request.getfixturevalue(cache_fixture)
    cache.put(7, "channel_name", ["傲彼瑞-美国", "傲彼瑞-加拿大"])
    assert cache.get(7, "channel_name") == ["傲彼瑞-美国", "傲彼瑞-加拿大"]


@BOTH_CACHES
def test_get_miss_when_never_written(cache_fixture, request):
    cache = request.getfixturevalue(cache_fixture)
    assert cache.get(999, "no_such_field") is None


@BOTH_CACHES
def test_expired_entry_is_miss(cache_fixture, request):
    """写入后手动改写 fetched_at 到 25 小时前（TTL 24h），过期即不命中。"""
    cache = request.getfixturevalue(cache_fixture)
    cache.put(7, "channel_name", ["傲彼瑞-美国"])
    path = cache._cache_path(7, "channel_name")
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["fetched_at"] = time.time() - 25 * 3600
    Path(path).write_text(json.dumps(payload), encoding="utf-8")
    assert cache.get(7, "channel_name") is None


@BOTH_CACHES
def test_corrupt_file_returns_none(cache_fixture, request):
    """缓存文件损坏（非 JSON）时安全返回 None，不抛异常。"""
    cache = request.getfixturevalue(cache_fixture)
    path = Path(cache._cache_path(7, "channel_name"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a json {{{", encoding="utf-8")
    assert cache.get(7, "channel_name") is None


@BOTH_CACHES
def test_empty_values_are_not_written(cache_fixture, request):
    """空列表不落盘，避免把"暂无授权值"误当成可复用的缓存。"""
    cache = request.getfixturevalue(cache_fixture)
    cache.put(7, "channel_name", [])
    assert cache.get(7, "channel_name") is None


@BOTH_CACHES
def test_get_age_hours_reports_recent_write_as_near_zero(cache_fixture, request):
    cache = request.getfixturevalue(cache_fixture)
    cache.put(7, "channel_name", ["傲彼瑞-美国"])
    age = cache.get_age_hours(7, "channel_name")
    assert age is not None
    assert 0 <= age < 0.01


@BOTH_CACHES
def test_field_name_with_path_separators_is_sanitized(cache_fixture, request, tmp_path):
    """field_name 含路径分隔符时不得逃逸出缓存目录（安全化处理）。"""
    cache = request.getfixturevalue(cache_fixture)
    cache.put(7, "../../etc/passwd", ["evil"])
    path = Path(cache._cache_path(7, "../../etc/passwd")).resolve()
    cache_root = Path(str(tmp_path)).resolve()
    assert cache_root in path.parents
    # 安全化后仍可正常按同一 field_name 读回
    assert cache.get(7, "../../etc/passwd") == ["evil"]


# ── 2. Skill 侧三处枚举调用：超时/失败降级读缓存 ───────────────────────────


def test_platform_enum_falls_back_to_cache_on_timeout(skill_cache, monkeypatch):
    """平台枚举超时后命中本地缓存：返回缓存值并把年龄写入 cache_meta。"""
    skill_cache.put(7, "platform_name", ["Amazon", "Walmart"])

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opscli", timeout=7.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_meta: dict = {}
    values = skill_query_plan._auto_enum_platform_values(7, cache_meta=cache_meta)
    assert values == ["Amazon", "Walmart"]
    assert cache_meta.get("stale_hours") is not None


def test_platform_enum_returns_empty_when_no_cache(skill_cache, monkeypatch):
    """超时且无缓存兜底：维持现行失败路径，返回空列表（行为不回归）。"""

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opscli", timeout=7.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_meta: dict = {}
    values = skill_query_plan._auto_enum_platform_values(7, cache_meta=cache_meta)
    assert values == []
    assert "stale_hours" not in cache_meta


def test_platform_enum_success_writes_cache(skill_cache, monkeypatch):
    """实时枚举成功时写入本地缓存，供下次超时/失败降级复用。"""
    import json as _json

    class _FakeResult:
        returncode = 0
        stdout = _json.dumps(
            {"success": True, "data": {"data": [{"platform_name": "Amazon"}]}}
        )
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    values = skill_query_plan._auto_enum_platform_values(7)
    assert values == ["Amazon"]
    assert skill_cache.get(7, "platform_name") == ["Amazon"]


def test_component_values_enum_falls_back_to_cache_on_timeout(skill_cache, monkeypatch):
    """普通筛选组件字段枚举超时后命中缓存：返回缓存值，不写入 errors（视为已恢复）。"""
    skill_cache.put(7, "channel_name", ["傲彼瑞-美国", "傲彼瑞-加拿大"])

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opscli", timeout=7.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    errors: list = []
    cache_meta: dict = {}
    values = skill_query_plan._auto_enum_component_values(
        7, "channel_name", errors=errors, cache_meta=cache_meta
    )
    assert values == ["傲彼瑞-美国", "傲彼瑞-加拿大"]
    assert errors == []
    assert cache_meta.get("stale_hours") is not None


def test_component_values_enum_reports_error_when_no_cache(skill_cache, monkeypatch):
    """无缓存兜底时维持现行失败路径：errors 非空，返回空列表。"""

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opscli", timeout=7.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    errors: list = []
    values = skill_query_plan._auto_enum_component_values(7, "channel_name", errors=errors)
    assert values == []
    assert errors  # 无缓存兜底，必须如实报错供上层阻断


def test_component_field_group_partial_cache_degrade(skill_cache, monkeypatch):
    """批量枚举失败后逐字段读缓存：只预热了部分字段时允许部分降级。"""
    skill_cache.put(7, "channel_name", ["傲彼瑞-美国"])
    # country_name 未预热，降级结果里不应出现

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opscli", timeout=7.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_meta: dict = {}
    grouped = skill_query_plan._auto_enum_component_field_group(
        7, ["channel_name", "country_name"], cache_meta=cache_meta
    )
    assert grouped == {"channel_name": ["傲彼瑞-美国"]}
    assert "channel_name" in cache_meta
    assert "country_name" not in cache_meta


def test_component_field_group_success_writes_cache_per_field(skill_cache, monkeypatch):
    import json as _json

    class _FakeResult:
        returncode = 0
        stdout = _json.dumps(
            {
                "success": True,
                "data": {
                    "data": [
                        {"channel_name": "傲彼瑞-美国", "country_name": "美国"},
                    ]
                },
            }
        )
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    grouped = skill_query_plan._auto_enum_component_field_group(
        7, ["channel_name", "country_name"]
    )
    assert grouped == {"channel_name": ["傲彼瑞-美国"], "country_name": ["美国"]}
    assert skill_cache.get(7, "channel_name") == ["傲彼瑞-美国"]
    assert skill_cache.get(7, "country_name") == ["美国"]


def test_component_filter_resolution_discloses_stale_cache(skill_cache, monkeypatch):
    """端到端：渠道筛选走缓存降级解析成功后，component_filter_disclosures_zh 里
    必须出现"来自约 N 小时前缓存"字样，不能让 Agent 把降级值当实时数据。
    """
    skill_cache.put(7, "channel_name", ["傲彼瑞-美国", "傲创-美国"])

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opscli", timeout=7.0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    contract = {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": "channel_name",
                    "label_zh": "渠道",
                    "component_dataset_alias": "ds_channel",
                    "component_table_id": 7,
                }
            ],
            "query_template": {
                "tableId": 1,
                "dimensions": [],
                "metrics": [],
                "filters": [],
            },
        },
    }
    out = skill_query_plan._resolve_component_filters(
        contract, "查渠道是傲彼瑞-美国的所有ASIN", auto_enum=True, data_dir=None
    )
    assert out["status"] == "planned"
    disclosures = " ".join(out["model_view"].get("component_filter_disclosures_zh") or [])
    assert "小时前缓存" in disclosures


# ── 3. 内核侧 entry.py 的 enum_fn：同样的降级语义 ─────────────────────────


def test_kernel_enum_fn_falls_back_to_cache_on_exception(tmp_path):
    """entry._make_callbacks 的 enum_fn：实时枚举异常时命中本地缓存则降级返回。"""
    kernel_enum_cache.put(7, "platform_name", ["Amazon"], base_dir=tmp_path)

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
    assert kernel_enum_cache.get(7, "platform_name", base_dir=tmp_path) == ["Amazon"]


def test_run_plan_attaches_stale_cache_disclosure(tmp_path, monkeypatch):
    """run_plan：本次调用中 enum_fn 命中缓存降级时，在 model_view 追加中文披露。"""
    kernel_enum_cache.put(7, "platform_name", ["Amazon"], base_dir=tmp_path)

    def fake_build_model_query_plan(
        adapter, request, *, requested_fields, refresh_fn, enum_fn, **kwargs
    ):
        # 模拟规划器内部真实发生的一次枚举调用：实时失败触发缓存降级
        enum_fn(7, "platform_name", limit=100)
        return {"contract": "query_plan_model_contract_v2", "model_view": {}}

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
