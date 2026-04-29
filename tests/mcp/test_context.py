"""MCP context.py 兼容性测试。

context.py 已变为空操作 + 弃用警告模式，验证三个函数的行为。
"""
import asyncio
import warnings

import pytest

from opscli.mcp.context import configure_multi_user, get_credential_dir, is_multi_user_enabled


def test_configure_multi_user_is_noop_and_deprecated(tmp_path):
    """configure_multi_user 在无状态下为空操作，触发 DeprecationWarning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        configure_multi_user(enabled=False, base_dir=tmp_path)
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "废弃" in str(w[0].message)


def test_is_multi_user_enabled_returns_false_and_deprecated():
    """is_multi_user_enabled 在无状态下返回 False，触发 DeprecationWarning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = is_multi_user_enabled()
        assert result is False
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)


def test_get_credential_dir_returns_none_and_deprecated():
    """get_credential_dir 在无状态下返回 None，触发 DeprecationWarning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = asyncio.run(get_credential_dir())
        assert result is None
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)