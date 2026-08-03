"""卖家精灵接口直连配置。"""

from __future__ import annotations

import os
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from opscli.config import CONFIG_DIR


ENV_USERNAME = "OPSCLI_SELLER_SPRITE_USERNAME"
ENV_PASSWORD = "OPSCLI_SELLER_SPRITE_PASSWORD"
ENV_ACCOUNT_NAME = "OPSCLI_SELLER_SPRITE_ACCOUNT_NAME"
ENV_ACCOUNTS = "OPSCLI_SELLER_SPRITE_ACCOUNTS"
ENV_OUTPUT_DIR = "OPSCLI_SELLER_SPRITE_OUTPUT_DIR"
# 队列写端与外部 Monitor 共用该显式路径，避免依赖不同服务账号的 HOME。
ENV_QUEUE_DB_PATH = "OPSCLI_SELLER_SPRITE_QUEUE_DB_PATH"
ENV_PAGE_SIZE = "OPSCLI_SELLER_SPRITE_PAGE_SIZE"
ENV_ACCOUNT_CACHE_TTL_SECONDS = "OPSCLI_SELLER_SPRITE_ACCOUNT_CACHE_TTL_SECONDS"
ENV_TASK_TIMEOUT_SECONDS = "OPSCLI_SELLER_SPRITE_TASK_TIMEOUT_SECONDS"
ENV_TASK_LEASE_SECONDS = "OPSCLI_SELLER_SPRITE_TASK_LEASE_SECONDS"
ENV_TASK_HEARTBEAT_SECONDS = "OPSCLI_SELLER_SPRITE_TASK_HEARTBEAT_SECONDS"
ENV_SHUTDOWN_TIMEOUT_SECONDS = "OPSCLI_SELLER_SPRITE_SHUTDOWN_TIMEOUT_SECONDS"
ENV_MODE = "OPSCLI_SELLER_SPRITE_MODE"
ENV_BROWSER_PROFILE_DIR = "OPSCLI_SELLER_SPRITE_BROWSER_PROFILE_DIR"
ENV_BROWSER_HEADLESS = "OPSCLI_SELLER_SPRITE_BROWSER_HEADLESS"
ENV_BROWSER_RUNTIME = "OPSCLI_SELLER_SPRITE_BROWSER_RUNTIME"
ENV_BROWSER_CHANNEL = "OPSCLI_SELLER_SPRITE_BROWSER_CHANNEL"
ENV_BROWSER_TASK_INTERVAL_SECONDS = "OPSCLI_SELLER_SPRITE_BROWSER_TASK_INTERVAL_SECONDS"
ENV_BROWSER_COOLDOWN_SECONDS = "OPSCLI_SELLER_SPRITE_BROWSER_COOLDOWN_SECONDS"
ENV_BROWSER_IDLE_TTL_SECONDS = "OPSCLI_SELLER_SPRITE_BROWSER_IDLE_TTL_SECONDS"
ENV_BROWSER_MAX_LIFETIME_SECONDS = "OPSCLI_SELLER_SPRITE_BROWSER_MAX_LIFETIME_SECONDS"
ENV_BROWSER_PAGE_PREPARE = "OPSCLI_SELLER_SPRITE_BROWSER_PAGE_PREPARE"
ENV_BROWSER_CAPTCHA_OCR_ENABLED = "OPSCLI_SELLER_SPRITE_BROWSER_CAPTCHA_OCR_ENABLED"
ENV_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS = "OPSCLI_SELLER_SPRITE_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS"

DEFAULT_ACCOUNT_NAME = "default"
DEFAULT_PAGE_SIZE = 100
DEFAULT_SITE = "us"
DEFAULT_PERIOD = "30d"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "seller_sprite" / "api_runs"
# 未显式配置时沿用既有 CONFIG_DIR 布局，保持本地安装向后兼容。
DEFAULT_QUEUE_DB_PATH = CONFIG_DIR / "seller_sprite" / "task_queue.sqlite3"
DEFAULT_ACCOUNT_CACHE_TTL_SECONDS = 600
DEFAULT_TASK_TIMEOUT_SECONDS = 600
DEFAULT_TASK_LEASE_SECONDS = 60
DEFAULT_TASK_HEARTBEAT_SECONDS = 20
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 15
DEFAULT_MODE = "browser-route"
DEFAULT_BROWSER_PROFILE_DIR = CONFIG_DIR / "seller_sprite" / "browser_profiles"
DEFAULT_BROWSER_RUNTIME = "patchright"
DEFAULT_BROWSER_TASK_INTERVAL_SECONDS = 5.0
DEFAULT_BROWSER_COOLDOWN_SECONDS = 10.0
# 30 分钟可覆盖常见短间隔批量任务，同时及时释放长期无任务的浏览器资源。
DEFAULT_BROWSER_IDLE_TTL_SECONDS = 1800
# 6 小时轮换可限制单个 Chromium 上下文的长期内存增长，并避开任务执行中的强制中断。
DEFAULT_BROWSER_MAX_LIFETIME_SECONDS = 21600
DEFAULT_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class SellerSpriteSettings:
    """卖家精灵接口直连运行配置。"""

    account_name: str = DEFAULT_ACCOUNT_NAME
    username: str | None = None
    password: str | None = None
    accounts: tuple[dict[str, str], ...] = ()
    output_dir: Path = DEFAULT_OUTPUT_DIR
    queue_db_path: Path = DEFAULT_QUEUE_DB_PATH
    page_size: int = DEFAULT_PAGE_SIZE
    default_site: str = DEFAULT_SITE
    default_period: str = DEFAULT_PERIOD
    account_cache_ttl_seconds: int = DEFAULT_ACCOUNT_CACHE_TTL_SECONDS
    task_timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS
    task_lease_seconds: float = DEFAULT_TASK_LEASE_SECONDS
    task_heartbeat_seconds: float = DEFAULT_TASK_HEARTBEAT_SECONDS
    shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS
    default_mode: str = DEFAULT_MODE
    browser_profile_dir: Path = DEFAULT_BROWSER_PROFILE_DIR
    browser_headless: bool = False
    browser_runtime: str = DEFAULT_BROWSER_RUNTIME
    browser_channel: str | None = None
    browser_task_interval_seconds: float = DEFAULT_BROWSER_TASK_INTERVAL_SECONDS
    browser_cooldown_seconds: float = DEFAULT_BROWSER_COOLDOWN_SECONDS
    browser_idle_ttl_seconds: int = DEFAULT_BROWSER_IDLE_TTL_SECONDS
    browser_max_lifetime_seconds: int = DEFAULT_BROWSER_MAX_LIFETIME_SECONDS
    browser_page_prepare: bool = True
    browser_captcha_ocr_enabled: bool = True
    browser_captcha_ocr_max_attempts: int = DEFAULT_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的配置摘要。"""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["browser_profile_dir"] = str(self.browser_profile_dir)
        payload.pop("queue_db_path", None)
        payload["has_username"] = bool(self.username)
        payload["has_password"] = bool(self.password)
        payload["account_count"] = len(self.accounts) or int(bool(self.username))
        payload.pop("username", None)
        payload.pop("password", None)
        payload.pop("accounts", None)
        return payload


def load_settings() -> SellerSpriteSettings:
    """从 `.env` 和环境变量读取卖家精灵配置。"""
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    queue_db_path = resolve_queue_db_path(values)
    browser_profile_dir = Path(values.get(ENV_BROWSER_PROFILE_DIR) or DEFAULT_BROWSER_PROFILE_DIR).expanduser()
    page_size = _parse_int(values.get(ENV_PAGE_SIZE), DEFAULT_PAGE_SIZE)
    return SellerSpriteSettings(
        account_name=values.get(ENV_ACCOUNT_NAME) or DEFAULT_ACCOUNT_NAME,
        username=values.get(ENV_USERNAME) or None,
        password=values.get(ENV_PASSWORD) or None,
        accounts=_parse_accounts(values.get(ENV_ACCOUNTS)),
        output_dir=output_dir,
        queue_db_path=queue_db_path,
        page_size=page_size,
        account_cache_ttl_seconds=_parse_int(
            values.get(ENV_ACCOUNT_CACHE_TTL_SECONDS),
            DEFAULT_ACCOUNT_CACHE_TTL_SECONDS,
        ),
        task_timeout_seconds=_parse_float(
            values.get(ENV_TASK_TIMEOUT_SECONDS),
            DEFAULT_TASK_TIMEOUT_SECONDS,
        ),
        task_lease_seconds=_parse_float(
            values.get(ENV_TASK_LEASE_SECONDS),
            DEFAULT_TASK_LEASE_SECONDS,
        ),
        task_heartbeat_seconds=_parse_float(
            values.get(ENV_TASK_HEARTBEAT_SECONDS),
            DEFAULT_TASK_HEARTBEAT_SECONDS,
        ),
        shutdown_timeout_seconds=_parse_float(
            values.get(ENV_SHUTDOWN_TIMEOUT_SECONDS),
            DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
        ),
        default_mode=_normalize_mode(values.get(ENV_MODE)),
        browser_profile_dir=browser_profile_dir,
        browser_headless=_parse_bool(values.get(ENV_BROWSER_HEADLESS), _default_browser_headless()),
        browser_runtime=_normalize_browser_runtime(values.get(ENV_BROWSER_RUNTIME)),
        browser_channel=values.get(ENV_BROWSER_CHANNEL) or None,
        browser_task_interval_seconds=_parse_float(
            values.get(ENV_BROWSER_TASK_INTERVAL_SECONDS),
            DEFAULT_BROWSER_TASK_INTERVAL_SECONDS,
        ),
        browser_cooldown_seconds=_parse_float(
            values.get(ENV_BROWSER_COOLDOWN_SECONDS),
            DEFAULT_BROWSER_COOLDOWN_SECONDS,
        ),
        browser_idle_ttl_seconds=_parse_int(
            values.get(ENV_BROWSER_IDLE_TTL_SECONDS),
            DEFAULT_BROWSER_IDLE_TTL_SECONDS,
        ),
        browser_max_lifetime_seconds=_parse_int(
            values.get(ENV_BROWSER_MAX_LIFETIME_SECONDS),
            DEFAULT_BROWSER_MAX_LIFETIME_SECONDS,
        ),
        browser_page_prepare=_parse_bool(values.get(ENV_BROWSER_PAGE_PREPARE), True),
        browser_captcha_ocr_enabled=_parse_bool(values.get(ENV_BROWSER_CAPTCHA_OCR_ENABLED), True),
        browser_captcha_ocr_max_attempts=_parse_int(
            values.get(ENV_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS),
            DEFAULT_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS,
        ),
    )


def _load_env_values() -> dict[str, str]:
    """读取 `.env` 后叠加真实环境变量，真实环境变量优先。"""
    values = _read_dotenv()
    for key in [
        ENV_USERNAME,
        ENV_PASSWORD,
        ENV_ACCOUNT_NAME,
        ENV_ACCOUNTS,
        ENV_OUTPUT_DIR,
        ENV_QUEUE_DB_PATH,
        ENV_PAGE_SIZE,
        ENV_ACCOUNT_CACHE_TTL_SECONDS,
        ENV_TASK_TIMEOUT_SECONDS,
        ENV_TASK_LEASE_SECONDS,
        ENV_TASK_HEARTBEAT_SECONDS,
        ENV_SHUTDOWN_TIMEOUT_SECONDS,
        ENV_MODE,
        ENV_BROWSER_PROFILE_DIR,
        ENV_BROWSER_HEADLESS,
        ENV_BROWSER_RUNTIME,
        ENV_BROWSER_CHANNEL,
        ENV_BROWSER_TASK_INTERVAL_SECONDS,
        ENV_BROWSER_COOLDOWN_SECONDS,
        ENV_BROWSER_IDLE_TTL_SECONDS,
        ENV_BROWSER_MAX_LIFETIME_SECONDS,
        ENV_BROWSER_PAGE_PREPARE,
        ENV_BROWSER_CAPTCHA_OCR_ENABLED,
        ENV_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS,
    ]:
        value = os.environ.get(key)
        if value:
            values[key] = value
    return values


def resolve_queue_db_path(
    values: Mapping[str, str] | None = None,
    *,
    config_dir: Path | None = None,
) -> Path:
    """解析 SellerSprite 队列数据库路径，供写端与 Monitor 共用。

    Args:
        values: 可选环境变量映射；省略时读取 SellerSprite 的 `.env` 与进程环境。
        config_dir: 可选配置根目录，用于测试或调用方覆盖默认 `CONFIG_DIR`。

    Returns:
        显式配置的队列路径，或配置根目录下的兼容默认路径。
    """
    source = _load_env_values() if values is None else values
    configured = str(source.get(ENV_QUEUE_DB_PATH) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base_dir = Path(CONFIG_DIR if config_dir is None else config_dir)
    return (base_dir / "seller_sprite" / "task_queue.sqlite3").resolve()


def _read_dotenv() -> dict[str, str]:
    """从当前目录向上查找并解析 `.env`。"""
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        dotenv = directory / ".env"
        if dotenv.exists():
            return _parse_dotenv(dotenv)
    return {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    """解析简单 KEY=VALUE 格式的 `.env` 文件。"""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _parse_int(value: str | None, default: int) -> int:
    """解析正整数配置。"""
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _parse_float(value: str | None, default: float) -> float:
    """解析非负浮点配置。"""
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _parse_bool(value: str | None, default: bool) -> bool:
    """解析布尔配置。"""
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _default_browser_headless() -> bool:
    """默认使用有头浏览器；Linux 无显示环境由 browser-route 自动启动 Xvfb。"""
    return False


def _normalize_mode(value: str | None) -> str:
    """规范化执行模式。"""
    mode = (value or DEFAULT_MODE).strip().lower()
    return mode if mode in {"api-direct", "browser-route"} else DEFAULT_MODE


def _normalize_browser_runtime(value: str | None) -> str:
    """规范化 browser-route 使用的浏览器自动化运行时。"""
    runtime = (value or DEFAULT_BROWSER_RUNTIME).strip().lower()
    return runtime if runtime in {"playwright", "patchright"} else DEFAULT_BROWSER_RUNTIME


def _parse_accounts(value: str | None) -> tuple[dict[str, str], ...]:
    """解析服务端预配置账号池。"""
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()

    accounts: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        username = str(item.get("username") or "").strip()
        password = str(item.get("password") or "").strip()
        if not name or not username or not password:
            continue
        accounts.append({"name": name, "username": username, "password": password})
    return tuple(accounts)
