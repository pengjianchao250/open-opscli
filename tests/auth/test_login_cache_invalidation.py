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
