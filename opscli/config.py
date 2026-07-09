"""全局配置模块。

仅包含配置路径和版本号，禁止导入任何 opscli 子模块（铁律2）。
"""
from __future__ import annotations

from importlib.metadata import version as _get_version, PackageNotFoundError
import configparser
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
        __version__ = tomllib.load(_f)["project"]["version"]

CONFIG_DIR = Path.home() / ".config" / "opscli"

# 平台 ID 默认映射（平台别名 → 远端 platform 参数值）
PLATFORM_DEFAULTS = {
    "shopify": 2,
}

# Shopify 工单操作模板 ID 默认值（可通过 config.ini [shopify_templates] 覆盖）
SHOPIFY_TEMPLATE_DEFAULTS = {
    "price_update": 1685,
    "inventory_set": 1683,
    "set_active": 1779,
    "set_draft": 1791,
    "delete": 1783,
}


def get_platform_id(platform_name: str) -> int:
    """获取指定平台的 platform ID。

    优先从 config.ini [platforms] section 读取，
    未配置则回退到 PLATFORM_DEFAULTS 内置默认值。

    Args:
        platform_name: 平台别名（如 "shopify"）

    Returns:
        平台 ID（整数）
    """
    config = configparser.ConfigParser()
    config_path = CONFIG_DIR / "config.ini"
    if config_path.exists():
        config.read(config_path, encoding="utf-8")
    fallback = PLATFORM_DEFAULTS.get(platform_name, 1)
    return config.getint("platforms", platform_name, fallback=fallback)


def get_shopify_template_id(operation: str) -> int:
    """获取 Shopify 工单操作的模板 ID。

    优先从 config.ini [shopify_templates] section 读取，
    未配置则回退到 SHOPIFY_TEMPLATE_DEFAULTS 内置默认值。

    Args:
        operation: 操作类型（如 "price_update", "inventory_set", "set_active", "set_draft"）

    Returns:
        模板 ID（整数）
    """
    config = configparser.ConfigParser()
    config_path = CONFIG_DIR / "config.ini"
    if config_path.exists():
        config.read(config_path, encoding="utf-8")
    fallback = SHOPIFY_TEMPLATE_DEFAULTS.get(operation, 0)
    return config.getint("shopify_templates", operation, fallback=fallback)
