"""Google Trends 配置。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR


ENV_OUTPUT_DIR = "OPSCLI_GOOGLE_TRENDS_OUTPUT_DIR"
ENV_HL = "OPSCLI_GOOGLE_TRENDS_HL"
ENV_TZ = "OPSCLI_GOOGLE_TRENDS_TZ"
ENV_TIMEOUT_SECONDS = "OPSCLI_GOOGLE_TRENDS_TIMEOUT_SECONDS"
ENV_RETRIES = "OPSCLI_GOOGLE_TRENDS_RETRIES"
ENV_BACKOFF_FACTOR = "OPSCLI_GOOGLE_TRENDS_BACKOFF_FACTOR"
ENV_PROXIES = "OPSCLI_GOOGLE_TRENDS_PROXIES"
ENV_REQUESTS_VERIFY = "OPSCLI_GOOGLE_TRENDS_REQUESTS_VERIFY"

DEFAULT_OUTPUT_DIR = CONFIG_DIR / "google_trends" / "api_runs"
DEFAULT_HL = "en-US"
DEFAULT_TZ = 360
DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_FACTOR = 0.1
DEFAULT_REQUESTS_VERIFY = True


@dataclass(frozen=True)
class GoogleTrendsSettings:
    """Google Trends 运行配置。"""

    output_dir: Path = DEFAULT_OUTPUT_DIR
    hl: str = DEFAULT_HL
    tz: int = DEFAULT_TZ
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retries: int = DEFAULT_RETRIES
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    proxies: list[str] | None = None
    requests_verify: bool = DEFAULT_REQUESTS_VERIFY

    def to_public_dict(self) -> dict[str, Any]:
        """返回配置摘要。"""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        return payload


def load_settings() -> GoogleTrendsSettings:
    """从 `.env` 和环境变量读取 Google Trends 配置。"""
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    return GoogleTrendsSettings(
        output_dir=output_dir,
        hl=values.get(ENV_HL) or DEFAULT_HL,
        tz=_parse_int(values.get(ENV_TZ), DEFAULT_TZ),
        timeout_seconds=_parse_float(values.get(ENV_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS),
        retries=_parse_int(values.get(ENV_RETRIES), DEFAULT_RETRIES),
        backoff_factor=_parse_float(values.get(ENV_BACKOFF_FACTOR), DEFAULT_BACKOFF_FACTOR),
        proxies=_parse_proxies(values.get(ENV_PROXIES)),
        requests_verify=_parse_bool(values.get(ENV_REQUESTS_VERIFY), DEFAULT_REQUESTS_VERIFY),
    )


def _load_env_values() -> dict[str, str]:
    values = _read_dotenv()
    for key in [
        ENV_OUTPUT_DIR,
        ENV_HL,
        ENV_TZ,
        ENV_TIMEOUT_SECONDS,
        ENV_RETRIES,
        ENV_BACKOFF_FACTOR,
        ENV_PROXIES,
        ENV_REQUESTS_VERIFY,
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


def _parse_float(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _parse_bool(value: str | None, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_proxies(value: str | None) -> list[str] | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    proxies = [item.strip() for item in text.split(",") if item.strip()]
    return proxies or None
