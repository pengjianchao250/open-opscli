"""西柚洞察接口直连配置。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR


ENV_AUTHORIZATION = "OPSCLI_XIYOU_AUTHORIZATION"
ENV_COOKIE = "OPSCLI_XIYOU_COOKIE"
ENV_OUTPUT_DIR = "OPSCLI_XIYOU_OUTPUT_DIR"
ENV_PAGE_SIZE = "OPSCLI_XIYOU_PAGE_SIZE"
ENV_PROVIDER = "OPSCLI_XIYOU_PROVIDER"
ENV_KRS_VER = "OPSCLI_XIYOU_KRS_VER"
ENV_CREDENTIAL_PATH = "OPSCLI_XIYOU_CREDENTIAL_PATH"
ENV_NOTIFY_PATH = "OPSCLI_XIYOU_NOTIFY_PATH"
ENV_CREDENTIAL_LATEST_URL = "OPSCLI_XIYOU_CREDENTIAL_LATEST_URL"
ENV_CREDENTIAL_API_KEY = "OPSCLI_XIYOU_CREDENTIAL_API_KEY"
ENV_CREDENTIAL_CACHE_TTL_SECONDS = "OPSCLI_XIYOU_CREDENTIAL_CACHE_TTL_SECONDS"

DEFAULT_PROVIDER = "xiyou"
DEFAULT_PAGE_SIZE = 50
DEFAULT_SITE = "US"
DEFAULT_PERIOD = "week"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "xiyou" / "api_runs"
DEFAULT_CREDENTIAL_PATH = CONFIG_DIR / "xiyou" / "credential.json"
DEFAULT_NOTIFY_PATH = CONFIG_DIR / "xiyou" / "notify.yaml"
DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class XiyouSettings:
    """西柚洞察接口直连运行配置。"""

    provider: str = DEFAULT_PROVIDER
    authorization: str | None = None
    cookie: str | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    credential_path: Path = DEFAULT_CREDENTIAL_PATH
    notify_path: Path = DEFAULT_NOTIFY_PATH
    page_size: int = DEFAULT_PAGE_SIZE
    default_site: str = DEFAULT_SITE
    default_period: str = DEFAULT_PERIOD
    krs_ver: str | None = None
    credential_latest_url: str | None = None
    credential_api_key: str | None = None
    credential_cache_ttl_seconds: int = DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的配置摘要。"""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["notify_path"] = str(self.notify_path)
        payload["has_authorization"] = bool(self.authorization)
        payload["has_cookie"] = bool(self.cookie)
        payload["has_credential_latest_url"] = bool(self.credential_latest_url)
        payload["has_credential_api_key"] = bool(self.credential_api_key)
        payload.pop("authorization", None)
        payload.pop("cookie", None)
        payload.pop("credential_api_key", None)
        return payload


def load_settings() -> XiyouSettings:
    """从 `.env` 和环境变量读取西柚洞察配置。"""
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    credential_path = Path(values.get(ENV_CREDENTIAL_PATH) or DEFAULT_CREDENTIAL_PATH).expanduser()
    notify_path = Path(values.get(ENV_NOTIFY_PATH) or DEFAULT_NOTIFY_PATH).expanduser()
    page_size = _parse_int(values.get(ENV_PAGE_SIZE), DEFAULT_PAGE_SIZE)
    credential_cache_ttl_seconds = _parse_int(
        values.get(ENV_CREDENTIAL_CACHE_TTL_SECONDS),
        DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS,
    )
    return XiyouSettings(
        provider=values.get(ENV_PROVIDER) or DEFAULT_PROVIDER,
        authorization=values.get(ENV_AUTHORIZATION) or None,
        cookie=values.get(ENV_COOKIE) or None,
        output_dir=output_dir,
        credential_path=credential_path,
        notify_path=notify_path,
        page_size=page_size,
        krs_ver=values.get(ENV_KRS_VER) or None,
        credential_latest_url=values.get(ENV_CREDENTIAL_LATEST_URL) or None,
        credential_api_key=values.get(ENV_CREDENTIAL_API_KEY) or None,
        credential_cache_ttl_seconds=credential_cache_ttl_seconds,
    )


def _load_env_values() -> dict[str, str]:
    """读取 `.env` 后叠加真实环境变量，真实环境变量优先。"""
    values = _read_dotenv()
    for key in [
        ENV_AUTHORIZATION,
        ENV_COOKIE,
        ENV_OUTPUT_DIR,
        ENV_PAGE_SIZE,
        ENV_PROVIDER,
        ENV_KRS_VER,
        ENV_CREDENTIAL_PATH,
        ENV_NOTIFY_PATH,
        ENV_CREDENTIAL_LATEST_URL,
        ENV_CREDENTIAL_API_KEY,
        ENV_CREDENTIAL_CACHE_TTL_SECONDS,
    ]:
        value = os.environ.get(key)
        if value:
            values[key] = value
    return values


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
