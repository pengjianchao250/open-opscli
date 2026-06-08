"""全局配置模块。

仅包含配置路径和版本号，禁止导入任何 opscli 子模块（铁律2）。
"""
from __future__ import annotations

from importlib.metadata import version as _get_version, PackageNotFoundError
from pathlib import Path

# 从 pyproject.toml 动态读取版本号，供请求头 X-Opscli-Version 使用
# 优先从已安装的包元数据读取，fallback 从 pyproject.toml 解析（开发模式）
try:
    __version__ = _get_version("aukeys-opscli")
except PackageNotFoundError:
    # 开发模式下 pip install -e . 未注册元数据，从 pyproject.toml 解析
    import tomllib
    _project_root = Path(__file__).resolve().parent.parent
    with open(_project_root / "pyproject.toml", "rb") as _f:
        __version__ = tomllib.loads(_f.read())["project"]["version"]

CONFIG_DIR = Path.home() / ".config" / "opscli"
