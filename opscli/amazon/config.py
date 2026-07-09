"""amazon 模块抓取配置加载器。

职责：从 ~/.config/opscli/config.ini 的 [amazon] 段与环境变量读取
抓取相关配置，核心是**代理**与**反检测**参数。

为什么需要代理：Amazon 的 Bot 检测最主要依据是来源 IP 的信誉。
阿里云等数据中心 IP 段被 Amazon 标记为高风险，会直接触发验证码 /
首页重定向。无论浏览器指纹伪装做得多好，机房 IP 一旦被封都无法绕过。
唯一可靠的做法是把出口切换到住宅 / 移动代理（residential / mobile proxy），
或改用 Amazon 官方 Product Advertising API（最合规、无封禁风险）。

优先级（从高到低）：环境变量 OPSCLI_AMAZON_* > config.ini [amazon] > 内置默认。

config.ini 示例：

    [amazon]
    proxy_server = http://gate.your-proxy.com:8000
    proxy_username = your_user
    proxy_password = your_pass
    max_retries = 3
    headless = true
"""

from __future__ import annotations

import configparser
import os

from opscli.config import CONFIG_DIR

# 配置文件路径（复用全局 CONFIG_DIR，遵循铁律3 禁止硬编码）
CONFIG_PATH = CONFIG_DIR / "config.ini"

# config.ini 中本模块使用的 section 名
_SECTION = "amazon"

# 反检测用的真实桌面 Chrome User-Agent 池。
# 覆盖多平台 / 多版本，抓取时随机选取一个，降低单一指纹被识别的概率。
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# 反检测用的常见桌面视口尺寸池，随机选取避免固定 viewport 指纹。
VIEWPORTS: list[dict[str, int]] = [
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
]


def _read_ini() -> configparser.ConfigParser:
    """读取 config.ini，文件不存在时返回空的解析器。"""
    ini = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        ini.read(CONFIG_PATH, encoding="utf-8")
    return ini


def _get(env_name: str, ini_key: str, default: str = "") -> str:
    """按优先级读取字符串配置：环境变量 > config.ini [amazon] > 默认值。"""
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value.strip()
    ini = _read_ini()
    if ini.has_option(_SECTION, ini_key):
        return ini.get(_SECTION, ini_key).strip()
    return default


def get_proxy() -> dict | None:
    """读取代理配置，返回可直接传给 Playwright launch 的 proxy dict。

    proxy_server 为空时返回 None（表示不使用代理，走本机出口 IP）。
    username / password 可选，用于需要鉴权的商业住宅代理。

    Returns:
        {"server": ..., "username": ..., "password": ...} 或 None
    """
    server = _get("OPSCLI_AMAZON_PROXY_SERVER", "proxy_server")
    if not server:
        return None
    proxy: dict[str, str] = {"server": server}
    username = _get("OPSCLI_AMAZON_PROXY_USERNAME", "proxy_username")
    password = _get("OPSCLI_AMAZON_PROXY_PASSWORD", "proxy_password")
    # 仅在配置了用户名时附加鉴权字段，避免向代理传空凭证
    if username:
        proxy["username"] = username
        proxy["password"] = password
    return proxy


def get_max_retries() -> int:
    """读取命中 Bot 检测时的最大重试次数，默认 3（含首次共尝试 3 次）。"""
    raw = _get("OPSCLI_AMAZON_MAX_RETRIES", "max_retries", "3")
    try:
        # 约束在 1~6 之间，防止配置异常导致过度重试拖慢流程
        return max(1, min(6, int(raw)))
    except ValueError:
        return 3


def get_headless() -> bool:
    """读取是否无头模式，默认 True（服务器部署场景通常无显示器）。"""
    raw = _get("OPSCLI_AMAZON_HEADLESS", "headless", "true").lower()
    return raw not in ("false", "0", "no", "off")
