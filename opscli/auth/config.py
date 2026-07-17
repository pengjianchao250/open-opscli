"""
auth 模块配置加载器。

优先级（从高到低）：
  1. 项目根目录 .env 文件（开发/测试环境覆盖，不提交 git）
  2. ~/.config/opscli/config.ini（用户本地覆盖）
  3. DEFAULTS（生产默认值，硬编码在代码中）
"""

import configparser
from pathlib import Path

from opscli.config import CONFIG_DIR

# 生产环境默认值
DEFAULTS = {
    "ops_url": "https://ops.api.xenkee.com/api",
    "ops_system_url": "https://ops.api.xenkee.com",
    "ops_token_endpoint": "/api/v1/auth/cli-token",
    "polaris_system_url": "https://bi.api.xenkee.com",
    "polaris_token_endpoint": "/api/auth/cli-token",
    "amazon_submit_endpoint": "",
    # 控制 polaris 系统是否参与授权请求和 Token 刷新
    # 默认 false（正式发版中 polaris 暂时不参与）
    # 需要启用时在 .env 写 OPSCLI_POLARIS_ENABLED=true
    # 或在 ~/.config/opscli/config.ini [systems] 写入 polaris_enabled = true
    "polaris_enabled": "true",
}

# .env 环境变量名 → config 内部 key 的映射
_ENV_VAR_MAP: dict[str, str] = {
    "OPSCLI_OPS_URL": "ops_url",
    "OPSCLI_OPS_SYSTEM_URL": "ops_system_url",
    "OPSCLI_OPS_TOKEN_ENDPOINT": "ops_token_endpoint",
    "OPSCLI_POLARIS_SYSTEM_URL": "polaris_system_url",
    "OPSCLI_POLARIS_TOKEN_ENDPOINT": "polaris_token_endpoint",
    "OPSCLI_AMAZON_SUBMIT_ENDPOINT": "amazon_submit_endpoint",
    "OPSCLI_POLARIS_ENABLED": "polaris_enabled",
}

CONFIG_PATH = CONFIG_DIR / "config.ini"


def _find_dotenv() -> Path | None:
    """从当前工作目录向上查找 .env 文件，找到即返回路径，未找到返回 None。"""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        # 遇到 git 根目录或文件系统根目录就停止向上查找
        if (directory / ".git").exists() or directory == directory.parent:
            break
    return None


def _parse_dotenv(dotenv_path: Path) -> dict[str, str]:
    """
    简单解析 .env 文件，返回 {ENV_VAR_NAME: value} 字典。

    支持：
      - KEY=VALUE（值不含引号）
      - KEY="VALUE"（双引号，自动去除）
      - KEY='VALUE'（单引号，自动去除）
      - # 开头的注释行
      - 空行忽略
    不支持多行值和变量引用（够用即可）。
    """
    env_vars: dict[str, str] = {}
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        # 跳过空行和注释行
        if not line or line.startswith("#"):
            continue
        # 必须包含 = 才是有效的键值对
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 去除首尾引号（成对才去除）
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env_vars[key] = value
    return env_vars


def load_config() -> dict:
    """
    按优先级合并配置并返回。

    优先级（从高到低）：
      1. 项目根目录 .env（OPSCLI_* 前缀变量）
      2. ~/.config/opscli/config.ini [systems] 节
      3. DEFAULTS 默认值
    """
    # --- 第三层：默认值 ---
    result = dict(DEFAULTS)

    # --- 第二层：config.ini 用户本地覆盖 ---
    ini = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        ini.read(CONFIG_PATH, encoding="utf-8")
    section = "systems"
    for key in DEFAULTS:
        if ini.has_option(section, key):
            result[key] = ini.get(section, key)

    # --- 第一层：.env 文件（最高优先级）---
    dotenv_path = _find_dotenv()
    if dotenv_path is not None:
        env_vars = _parse_dotenv(dotenv_path)
        for env_name, config_key in _ENV_VAR_MAP.items():
            if env_name in env_vars and env_vars[env_name]:
                result[config_key] = env_vars[env_name]

    return result


def get_ops_url() -> str:
    return load_config()["ops_url"]


def get_ops_system_url() -> str:
    """获取 ops 系统基础 URL（不含 /api 前缀）。

    用于拼接 MCP API Key 校验地址等非 /api 路径的端点。
    """
    return load_config()["ops_system_url"]


def get_builtin_systems() -> list[dict]:
    cfg = load_config()
    systems = [
        {
            "alias": "ops",
            "system_key": "ops",
            "url": cfg["ops_system_url"],
            "token_endpoint": cfg["ops_token_endpoint"],
            "source": "builtin",
        },
    ]
    # polaris_enabled=false 时跳过，不参与授权请求和 Token 刷新
    if cfg.get("polaris_enabled", "true").lower() == "true":
        systems.append({
            "alias": "polaris",
            "system_key": "polaris",
            "url": cfg["polaris_system_url"],
            "token_endpoint": cfg["polaris_token_endpoint"],
            "source": "builtin",
        })
    return systems


def get_amazon_submit_endpoint() -> str:
    return load_config()["amazon_submit_endpoint"]
