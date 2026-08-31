"""Collector Monitor 环境配置。"""

from __future__ import annotations

import ipaddress
import math
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from opscli.config import CONFIG_DIR
from opscli.mcp.quota import ENV_SQLITE_PATH
from opscli.seller_sprite.services.account_bindings import DEFAULT_BINDING_DB_PATH
from opscli.seller_sprite.config import ENV_QUEUE_DB_PATH, resolve_queue_db_path

_ENV_PREFIX = "OPSCLI_COLLECTOR_MONITOR_"
# 项目内默认机器人文件随包分发；显式环境配置仍具有最高优先级。
_BUNDLED_WEBHOOK_FILE = Path(__file__).with_name("wecom-webhook")


@dataclass(frozen=True)
class MonitorSettings:
    """监控服务的不可变运行配置。"""

    queue_db_path: Path
    state_db_path: Path
    monitor_url: str
    collector_mcp_url: str | None
    collector_mcp_api_key_file: Path | None
    poll_interval: float
    stalled_threshold: float
    queue_threshold: float
    runtime_stale_threshold: float
    orphan_required_scans: int
    alert_cooldown: float
    webhook_file: Path | None
    host: str
    port: int
    collector_probe_timeout: float
    scenario_test_enabled: bool
    account_binding_db_path: Path | None = None
    quota_db_path: Path | None = None


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
) -> MonitorSettings:
    """从统一前缀环境变量加载并校验监控配置。"""
    env = os.environ if environ is None else environ
    base_dir = Path(CONFIG_DIR if config_dir is None else config_dir)
    queue_db_path = _queue_db_path(env, base_dir)
    host = _text(env, "HOST", "127.0.0.1")
    port = _integer(env, "PORT", 8767, minimum=1, maximum=65535)
    default_url = f"http://{host}:{port}"
    webhook_file = (
        _optional_path(env, "WEBHOOK_FILE")
        if _env_name("WEBHOOK_FILE") in env
        else _BUNDLED_WEBHOOK_FILE if _BUNDLED_WEBHOOK_FILE.is_file() else None
    )
    settings = MonitorSettings(
        queue_db_path=queue_db_path,
        state_db_path=_path(
            env,
            "STATE_DB_PATH",
            base_dir / "collector_monitor" / "state.sqlite3",
        ),
        monitor_url=_url(env, "URL", default_url),
        collector_mcp_url=_optional_url(env, "COLLECTOR_MCP_URL"),
        collector_mcp_api_key_file=_optional_path(env, "COLLECTOR_MCP_API_KEY_FILE"),
        poll_interval=_number(env, "POLL_INTERVAL", 10.0, minimum=0.01),
        stalled_threshold=_number(env, "STALLED_THRESHOLD", 300.0, minimum=0.0),
        queue_threshold=_number(env, "QUEUE_THRESHOLD", 300.0, minimum=0.0),
        runtime_stale_threshold=_number(
            env,
            "RUNTIME_STALE_THRESHOLD",
            300.0,
            minimum=0.0,
        ),
        orphan_required_scans=_integer(
            env,
            "ORPHAN_REQUIRED_SCANS",
            2,
            minimum=1,
        ),
        alert_cooldown=_number(env, "ALERT_COOLDOWN", 1800.0, minimum=0.0),
        webhook_file=webhook_file,
        host=host,
        port=port,
        collector_probe_timeout=_number(
            env,
            "COLLECTOR_PROBE_TIMEOUT",
            5.0,
            minimum=0.01,
        ),
        scenario_test_enabled=_boolean(env, "SCENARIO_TEST_ENABLED", False),
        account_binding_db_path=base_dir / "seller_sprite" / DEFAULT_BINDING_DB_PATH.name,
        quota_db_path=Path(
            str(env.get(ENV_SQLITE_PATH) or base_dir / "mcp_quota" / "quota.sqlite3")
        ).expanduser(),
    )
    return validate_settings(settings)


def validate_settings(settings: MonitorSettings) -> MonitorSettings:
    """校验环境加载或手工构造的完整监控配置。"""
    validate_database_paths(settings.queue_db_path, settings.state_db_path)
    if settings.account_binding_db_path is not None:
        validate_database_paths(settings.account_binding_db_path, settings.state_db_path)
    if settings.quota_db_path is not None:
        validate_database_paths(settings.quota_db_path, settings.state_db_path)
    _validate_url(settings.monitor_url, "URL")
    if not _url_protects_secret(settings.monitor_url):
        raise ValueError(
            "monitor url must use HTTPS or loopback because the UI accepts API keys"
        )
    if settings.collector_mcp_url is not None:
        _validate_url(settings.collector_mcp_url, "COLLECTOR_MCP_URL")
    if settings.scenario_test_enabled and settings.collector_mcp_url is None:
        raise ValueError("scenario test requires collector mcp url")
    transports_api_key = (
        settings.collector_mcp_api_key_file is not None
        or settings.scenario_test_enabled
    )
    if (
        transports_api_key
        and settings.collector_mcp_url is not None
        and not _url_protects_secret(settings.collector_mcp_url)
    ):
        raise ValueError(
            "collector mcp url must use HTTPS or loopback when an API key may be sent"
        )
    for name, value, minimum in (
        ("POLL_INTERVAL", settings.poll_interval, 0.01),
        ("STALLED_THRESHOLD", settings.stalled_threshold, 0.0),
        ("QUEUE_THRESHOLD", settings.queue_threshold, 0.0),
        ("RUNTIME_STALE_THRESHOLD", settings.runtime_stale_threshold, 0.0),
        ("ALERT_COOLDOWN", settings.alert_cooldown, 0.0),
        ("COLLECTOR_PROBE_TIMEOUT", settings.collector_probe_timeout, 0.01),
    ):
        _validate_finite_setting(name, value, minimum=minimum)
    _validate_integer_setting(
        "ORPHAN_REQUIRED_SCANS",
        settings.orphan_required_scans,
        minimum=1,
    )
    _validate_integer_setting("PORT", settings.port, minimum=1, maximum=65535)
    if not str(settings.host).strip():
        raise ValueError("host must not be empty")
    return settings


def validate_database_paths(queue_db_path: str | Path, state_db_path: str | Path) -> None:
    """拒绝相同路径、符号链接或硬链接指向同一业务数据库。"""
    queue_path = Path(queue_db_path)
    state_path = Path(state_db_path)
    if queue_path.resolve() == state_path.resolve():
        raise ValueError("queue db path and state db path must be different")
    if queue_path.exists() and state_path.exists():
        try:
            same_file = queue_path.samefile(state_path)
        except OSError as exc:
            raise ValueError("queue db and state db identity check failed") from exc
        if same_file:
            raise ValueError("queue db and state db must be different physical files")


def read_protected_text(path: str | Path) -> str:
    """读取受保护普通文件；POSIX 拒绝组和其他用户权限。"""
    target = Path(path)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("credential file must be a regular file")
    # Windows 标准库无法可靠验证 ACL，因此仅执行普通文件检查。
    if os.name != "nt" and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError("credential file permissions must not allow group or other access")
    return target.read_text(encoding="utf-8").strip()


def _env_name(name: str) -> str:
    """构造完整环境变量名。"""
    return f"{_ENV_PREFIX}{name}"


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    """读取非空文本配置。"""
    value = str(env.get(_env_name(name), default)).strip()
    if not value:
        raise ValueError(f"{name.lower().replace('_', ' ')} must not be empty")
    return value


def _optional_text(env: Mapping[str, str], name: str) -> str | None:
    """读取可选文本配置。"""
    value = str(env.get(_env_name(name), "")).strip()
    return value or None


def _url(env: Mapping[str, str], name: str, default: str) -> str:
    """读取仅含 HTTP(S) 基址的 URL。"""
    value = _text(env, name, default).rstrip("/")
    _validate_url(value, name)
    return value


def _optional_url(env: Mapping[str, str], name: str) -> str | None:
    """读取可选 HTTP(S) 探测地址。"""
    value = _optional_text(env, name)
    if value is None:
        return None
    value = value.rstrip("/")
    _validate_url(value, name)
    return value


def _validate_url(value: str, name: str) -> None:
    """拒绝凭据、查询和片段进入服务 URL 配置。"""
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name.lower().replace('_', ' ')} must be a safe HTTP URL")


def _url_protects_secret(value: str) -> bool:
    """仅允许 HTTPS 或明确回环 HTTP 承载请求密钥。"""
    parsed = urlparse(value)
    if parsed.scheme == "https":
        return True
    hostname = str(parsed.hostname or "").rstrip(".").casefold()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    """读取路径配置但不创建目录。"""
    value = _optional_text(env, name)
    return Path(value).expanduser() if value else default


def _queue_db_path(env: Mapping[str, str], base_dir: Path) -> Path:
    """统一解析业务队列路径，并拒绝 Collector 与 Monitor 配置漂移。"""
    seller_path = resolve_queue_db_path(env, config_dir=base_dir)
    monitor_value = _optional_text(env, "QUEUE_DB_PATH")
    if monitor_value is None:
        return seller_path
    monitor_path = Path(monitor_value).expanduser().resolve()
    seller_explicit = str(env.get(ENV_QUEUE_DB_PATH) or "").strip()
    if seller_explicit and monitor_path != seller_path:
        raise ValueError("queue db path conflicts with SellerSprite queue db path")
    return monitor_path


def _optional_path(env: Mapping[str, str], name: str) -> Path | None:
    """读取可选路径配置但不访问文件系统。"""
    value = _optional_text(env, name)
    return Path(value).expanduser() if value else None


def _validate_finite_setting(name: str, value: object, *, minimum: float) -> None:
    """拒绝手工配置中的非数值、NaN、Infinity 和越界值。"""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name.lower().replace('_', ' ')} must be a number") from exc
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(
            f"{name.lower().replace('_', ' ')} must be finite and >= {minimum}"
        )


def _validate_integer_setting(
    name: str,
    value: object,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    """拒绝手工配置中的布尔值、浮点数和越界整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name.lower().replace('_', ' ')} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(
            f"{name.lower().replace('_', ' ')} must be >= {minimum}{suffix}"
        )


def _number(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
) -> float:
    """读取有下界的浮点配置。"""
    raw = str(env.get(_env_name(name), default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name.lower().replace('_', ' ')} must be a number") from exc
    _validate_finite_setting(name, value, minimum=minimum)
    return value


def _integer(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    """读取有边界的整数配置。"""
    raw = str(env.get(_env_name(name), default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name.lower().replace('_', ' ')} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(
            f"{name.lower().replace('_', ' ')} must be >= {minimum}{suffix}"
        )
    return value


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    """读取显式布尔配置，避免拼写错误静默启用高风险功能。"""
    raw = str(env.get(_env_name(name), str(default))).strip().casefold()
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ValueError(f"{name.lower().replace('_', ' ')} must be a boolean")
