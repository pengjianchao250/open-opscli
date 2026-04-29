"""版本读取入口。

统一从包元数据读取版本；开发态未安装时使用受控 fallback。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "aukeys-opscli"
FALLBACK_VERSION = "0.0.23-dev"


def get_version() -> str:
    """返回当前运行版本。"""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return FALLBACK_VERSION
