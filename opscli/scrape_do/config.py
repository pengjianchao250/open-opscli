"""Scrape.do API 配置。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR

SCRAPE_DO_BASE_URL = "https://api.scrape.do"
ENV_OUTPUT_DIR = "OPSCLI_SCRAPEDO_OUTPUT_DIR"
ENV_TIMEOUT_SECONDS = "OPSCLI_SCRAPEDO_TIMEOUT_SECONDS"

DEFAULT_OUTPUT_DIR = CONFIG_DIR / "scrape_do" / "api_runs"
DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ScrapeDoSettings:
    """Scrape.do API 运行配置。"""

    output_dir: Path = DEFAULT_OUTPUT_DIR
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        return payload


def load_settings() -> ScrapeDoSettings:
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    return ScrapeDoSettings(
        output_dir=output_dir,
        timeout_seconds=_parse_int(values.get(ENV_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS),
    )


def _load_env_values() -> dict[str, str]:
    values = _read_dotenv()
    for key in [ENV_OUTPUT_DIR, ENV_TIMEOUT_SECONDS]:
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
    return parsed if parsed > 0 else default
