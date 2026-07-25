"""用户级元数据缓存单测。"""
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opscli.query.services.metadata_cache import MetadataCache


def _payload():
    return {"datasets": [{"dataset_alias": "ds_a"}], "fields": [], "select_columns": []}


# ----- Task 2：信封与新鲜度判定 -----

def test_envelope_and_fresh(tmp_path: Path):
    """新建信封应被判定为新鲜，且 email 一致。"""
    cache = MetadataCache(base_dir=tmp_path, ttl_seconds=3600)
    env = cache._envelope("u@x.com", _payload())
    assert env["user_email"] == "u@x.com"
    assert env["cache_version"] == 1
    assert env["ttl_seconds"] == 3600
    assert cache._is_fresh(env, "u@x.com") is True


def test_stale_when_email_mismatch(tmp_path: Path):
    """信封 email 与当前用户不符时视为不新鲜（换账号失效）。"""
    cache = MetadataCache(base_dir=tmp_path)
    env = cache._envelope("old@x.com", _payload())
    assert cache._is_fresh(env, "new@x.com") is False


def test_stale_when_expired(tmp_path: Path):
    """超过 TTL 视为不新鲜。"""
    cache = MetadataCache(base_dir=tmp_path, ttl_seconds=60)
    env = cache._envelope("u@x.com", _payload())
    env["fetched_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    assert cache._is_fresh(env, "u@x.com") is False


# ----- Task 3：磁盘层 -----

def test_disk_round_trip(tmp_path: Path):
    """写入后能读回相同信封。"""
    cache = MetadataCache(base_dir=tmp_path)
    env = cache._envelope("u@x.com", _payload())
    h = cache._email_hash("u@x.com")
    cache._write_disk(h, env)
    assert cache._cache_file(h).exists()
    loaded = cache._read_disk(h)
    assert loaded["user_email"] == "u@x.com"
    assert loaded["payload"]["datasets"][0]["dataset_alias"] == "ds_a"


def test_disk_missing_returns_none(tmp_path: Path):
    """无缓存文件时返回 None。"""
    cache = MetadataCache(base_dir=tmp_path)
    assert cache._read_disk(cache._email_hash("nobody@x.com")) is None


def test_disk_corrupt_returns_none(tmp_path: Path):
    """损坏 JSON 返回 None 而非抛错。"""
    cache = MetadataCache(base_dir=tmp_path)
    h = cache._email_hash("u@x.com")
    cache._dir.mkdir(parents=True, exist_ok=True)
    cache._cache_file(h).write_text("{not json", encoding="utf-8")
    assert cache._read_disk(h) is None


# ----- Task 4：get 主流程 -----

def test_get_miss_then_hit(tmp_path: Path):
    """首次 miss 触发一次 fetch_fn 并落盘；二次命中不再 fetch。"""
    cache = MetadataCache(base_dir=tmp_path)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return _payload()

    r1 = cache.get("u@x.com", fetch)
    assert r1.from_cache is False and r1.stale is False
    assert calls["n"] == 1

    r2 = cache.get("u@x.com", fetch)
    assert r2.from_cache is True
    assert calls["n"] == 1


def test_get_l2_hit_new_instance(tmp_path: Path):
    """新进程（新实例、空 L1）能命中已落盘的 L2 缓存。"""
    MetadataCache(base_dir=tmp_path).get("u@x.com", _payload)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return _payload()

    r = MetadataCache(base_dir=tmp_path).get("u@x.com", fetch)
    assert r.from_cache is True
    assert calls["n"] == 0


# ----- Task 5：并发防惊群 -----

def test_get_concurrent_single_fetch(tmp_path: Path):
    """10 个线程并发首取，只应触发一次 fetch_fn。"""
    cache = MetadataCache(base_dir=tmp_path)
    calls = {"n": 0}
    lock = threading.Lock()

    def fetch():
        with lock:
            calls["n"] += 1
        time.sleep(0.05)
        return _payload()

    results = []

    def worker():
        results.append(cache.get("u@x.com", fetch))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert calls["n"] == 1


# ----- Task 6：stale 兜底 / 失效 / 模块级池 -----

def test_get_stale_on_fetch_error(tmp_path: Path):
    """已有过期缓存时，后端拉取失败返回过期数据并标 stale。"""
    cache = MetadataCache(base_dir=tmp_path, ttl_seconds=60)
    cache.get("u@x.com", _payload)
    h = cache._email_hash("u@x.com")
    env = cache._read_disk(h)
    env["fetched_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    cache._write_disk(h, env)
    cache._mem.clear()

    def boom():
        raise RuntimeError("backend down")

    r = cache.get("u@x.com", boom)
    assert r.stale is True
    assert r.payload["datasets"][0]["dataset_alias"] == "ds_a"


def test_get_raises_when_no_cache_and_fetch_fails(tmp_path: Path):
    """无任何缓存且拉取失败时原样抛错。"""
    cache = MetadataCache(base_dir=tmp_path)

    def boom():
        raise RuntimeError("backend down")

    with pytest.raises(RuntimeError):
        cache.get("fresh@x.com", boom)


def test_invalidate_specific(tmp_path: Path):
    """失效后下次强制重新拉取。"""
    cache = MetadataCache(base_dir=tmp_path)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return _payload()

    cache.get("u@x.com", fetch)
    cache.invalidate("u@x.com")
    cache.get("u@x.com", fetch)
    assert calls["n"] == 2


def test_module_pool_same_instance(tmp_path: Path):
    """同 base_dir 返回同一实例（池化）。"""
    from opscli.query.services.metadata_cache import get_metadata_cache

    a = get_metadata_cache(base_dir=tmp_path)
    b = get_metadata_cache(base_dir=tmp_path)
    assert a is b
