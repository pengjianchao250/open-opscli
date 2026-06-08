"""Keepa API 配置。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR


ENV_API_KEY = "OPSCLI_KEEPA_API_KEY"
ENV_ACCOUNT_NAME = "OPSCLI_KEEPA_ACCOUNT_NAME"
ENV_OUTPUT_DIR = "OPSCLI_KEEPA_OUTPUT_DIR"
ENV_RESERVE_TOKENS = "OPSCLI_KEEPA_RESERVE_TOKENS"
ENV_ACCOUNT_CACHE_TTL_SECONDS = "OPSCLI_KEEPA_ACCOUNT_CACHE_TTL_SECONDS"

DEFAULT_ACCOUNT_NAME = "default"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "keepa" / "api_runs"
DEFAULT_RESERVE_TOKENS = 10
DEFAULT_ACCOUNT_CACHE_TTL_SECONDS = 600


@dataclass(frozen=True)
class KeepaSettings:
    """Keepa API 运行配置。"""

    account_name: str = DEFAULT_ACCOUNT_NAME
    api_key: str | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    reserve_tokens: int = DEFAULT_RESERVE_TOKENS
    account_cache_ttl_seconds: int = DEFAULT_ACCOUNT_CACHE_TTL_SECONDS

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的配置摘要。"""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["has_api_key"] = bool(self.api_key)
        payload.pop("api_key", None)
        return payload


def load_settings() -> KeepaSettings:
    """从 `.env` 和环境变量读取 Keepa 配置。"""
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    return KeepaSettings(
        account_name=values.get(ENV_ACCOUNT_NAME) or DEFAULT_ACCOUNT_NAME,
        api_key=values.get(ENV_API_KEY) or None,
        output_dir=output_dir,
        reserve_tokens=_parse_int(values.get(ENV_RESERVE_TOKENS), DEFAULT_RESERVE_TOKENS),
        account_cache_ttl_seconds=_parse_int(
            values.get(ENV_ACCOUNT_CACHE_TTL_SECONDS),
            DEFAULT_ACCOUNT_CACHE_TTL_SECONDS,
        ),
    )


def _load_env_values() -> dict[str, str]:
    values = _read_dotenv()
    for key in [
        ENV_API_KEY,
        ENV_ACCOUNT_NAME,
        ENV_OUTPUT_DIR,
        ENV_RESERVE_TOKENS,
        ENV_ACCOUNT_CACHE_TTL_SECONDS,
    ]:
        value = os.environ.get(key)
        if value:
            values[key] = value
    return values


def _read_dotenv() -> dict[str, str]:
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        dotenv = directory / ".env"
        if dotenv.exists():
            return _parse_dotenv(dotenv)
    return {}


def _parse_dotenv(path: Path) -> dict[str, str]:
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
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default
