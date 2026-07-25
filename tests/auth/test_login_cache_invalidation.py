"""登录/登出失效元数据缓存挂钩单测。"""
from pathlib import Path

from opscli.query.services.metadata_cache import (
    get_metadata_cache,
    invalidate_metadata_cache,
)


def _payload():
    return {"datasets": [], "fields": [], "select_columns": []}


def test_invalidate_metadata_cache_clears_disk(tmp_path: Path):
    """invalidate_metadata_cache 应清空指定 base_dir 的缓存（登录/登出挂钩依赖此行为）。"""
    cache = get_metadata_cache(base_dir=tmp_path)
    cache.get("u@x.com", _payload)
    assert cache._read_disk(cache._email_hash("u@x.com")) is not None

    invalidate_metadata_cache(base_dir=tmp_path)
    assert cache._read_disk(cache._email_hash("u@x.com")) is None


def test_invalidate_specific_user_only(tmp_path: Path):
    """按 email 失效只清该用户，不影响其他用户缓存。"""
    cache = get_metadata_cache(base_dir=tmp_path)
    cache.get("a@x.com", _payload)
    cache.get("b@x.com", _payload)

    invalidate_metadata_cache(base_dir=tmp_path, user_email="a@x.com")
    assert cache._read_disk(cache._email_hash("a@x.com")) is None
    assert cache._read_disk(cache._email_hash("b@x.com")) is not None


def test_invalidate_clears_disk_when_pool_cold(tmp_path: Path):
    """模拟短生命进程：本进程未实例化过缓存池，invalidate 仍须清磁盘。

    复现 CLI auth login/logout 场景——磁盘缓存由别的进程写入，
    登出进程的池是冷的；旧实现会 no-op，修复后必须清除磁盘。
    """
    from opscli.query.services import metadata_cache as mc
    from opscli.query.services.metadata_cache import MetadataCache

    # 由“另一个进程”写入磁盘缓存（独立实例，不进模块池）
    MetadataCache(base_dir=tmp_path).get("u@x.com", _payload)
    h = MetadataCache._email_hash("u@x.com")
    assert (tmp_path / "metadata" / f"{h}.json").exists()

    # 模拟全新进程：清空模块级池，使 _caches 中无对应条目
    with mc._pool_lock:
        mc._caches.clear()

    invalidate_metadata_cache(base_dir=tmp_path)
    assert not (tmp_path / "metadata" / f"{h}.json").exists()
