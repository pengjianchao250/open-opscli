import configparser
from opscli.config import CONFIG_DIR

# 默认配置（生产环境）
DEFAULTS = {
    "ops_url": "https://ops.api.qa.aukeyit.com/api",
    "ops_system_url": "https://ops.api.qa.aukeyit.com",
    "ops_token_endpoint": "/api/v1/auth/cli-token",
    "polaris_system_url": "https://bi.api.xenkee.com",
    "polaris_token_endpoint": "/api/auth/cli-token",
    "amazon_submit_endpoint": "",
}

CONFIG_PATH = CONFIG_DIR / "config.ini"


def load_config() -> dict:
    """读取配置文件，不存在则返回默认值"""
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH, encoding="utf-8")

    section = "systems"
    result = {}
    for key, default in DEFAULTS.items():
        result[key] = config.get(section, key, fallback=default)
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
    return [
        {
            "alias": "ops",
            "system_key": "ops",
            "url": cfg["ops_system_url"],
            "token_endpoint": cfg["ops_token_endpoint"],
            "source": "builtin",
        },
        {
            "alias": "polaris",
            "system_key": "polaris",
            "url": cfg["polaris_system_url"],
            "token_endpoint": cfg["polaris_token_endpoint"],
            "source": "builtin",
        },
    ]


def get_amazon_submit_endpoint() -> str:
    return load_config()["amazon_submit_endpoint"]
