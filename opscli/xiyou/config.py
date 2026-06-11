"""Xiyou integration settings."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from opscli.auth.config import get_ops_system_url
from opscli.config import CONFIG_DIR


ENV_AUTHORIZATION = "OPSCLI_XIYOU_AUTHORIZATION"
ENV_COOKIE = "OPSCLI_XIYOU_COOKIE"
ENV_OUTPUT_DIR = "OPSCLI_XIYOU_OUTPUT_DIR"
ENV_PAGE_SIZE = "OPSCLI_XIYOU_PAGE_SIZE"
ENV_PROVIDER = "OPSCLI_XIYOU_PROVIDER"
ENV_KRS_VER = "OPSCLI_XIYOU_KRS_VER"
ENV_CREDENTIAL_PATH = "OPSCLI_XIYOU_CREDENTIAL_PATH"
ENV_CREDENTIAL_LATEST_URL = "OPSCLI_XIYOU_CREDENTIAL_LATEST_URL"
ENV_CREDENTIAL_API_KEY = "OPSCLI_XIYOU_CREDENTIAL_API_KEY"
ENV_CREDENTIAL_CACHE_TTL_SECONDS = "OPSCLI_XIYOU_CREDENTIAL_CACHE_TTL_SECONDS"

ENV_OPS_URL = "OPSCLI_OPS_URL"
ENV_OPS_SYSTEM_URL = "OPSCLI_OPS_SYSTEM_URL"

DEFAULT_PROVIDER = "xiyou"
DEFAULT_PAGE_SIZE = 50
DEFAULT_SITE = "US"
DEFAULT_PERIOD = "week"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "xiyou" / "api_runs"
DEFAULT_CREDENTIAL_PATH = CONFIG_DIR / "xiyou" / "credential.json"
DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class XiyouSettings:
    """Runtime settings for Xiyou integration."""

    provider: str = DEFAULT_PROVIDER
    authorization: str | None = None
    cookie: str | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    credential_path: Path = DEFAULT_CREDENTIAL_PATH
    page_size: int = DEFAULT_PAGE_SIZE
    default_site: str = DEFAULT_SITE
    default_period: str = DEFAULT_PERIOD
    krs_ver: str | None = None
    credential_latest_url: str | None = None
    credential_api_key: str | None = None
    credential_cache_ttl_seconds: int = DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS

    def to_public_dict(self) -> dict[str, Any]:
        """Return a redacted settings summary."""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["has_authorization"] = bool(self.authorization)
        payload["has_cookie"] = bool(self.cookie)
        payload["has_credential_latest_url"] = bool(self.credential_latest_url)
        payload["has_credential_api_key"] = bool(self.credential_api_key)
        payload.pop("authorization", None)
        payload.pop("cookie", None)
        payload.pop("credential_api_key", None)
        return payload


def load_settings() -> XiyouSettings:
    """Load settings from `.env` and process environment."""
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    credential_path = Path(values.get(ENV_CREDENTIAL_PATH) or DEFAULT_CREDENTIAL_PATH).expanduser()
    page_size = _parse_int(values.get(ENV_PAGE_SIZE), DEFAULT_PAGE_SIZE)
    credential_cache_ttl_seconds = _parse_int(
        values.get(ENV_CREDENTIAL_CACHE_TTL_SECONDS),
        DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS,
    )
    credential_latest_url = values.get(ENV_CREDENTIAL_LATEST_URL) or _build_default_credential_latest_url()
    return XiyouSettings(
        provider=values.get(ENV_PROVIDER) or DEFAULT_PROVIDER,
        authorization=values.get(ENV_AUTHORIZATION) or None,
        cookie=values.get(ENV_COOKIE) or None,
        output_dir=output_dir,
        credential_path=credential_path,
        page_size=page_size,
        krs_ver=values.get(ENV_KRS_VER) or None,
        credential_latest_url=credential_latest_url,
        credential_api_key=values.get(ENV_CREDENTIAL_API_KEY) or None,
        credential_cache_ttl_seconds=credential_cache_ttl_seconds,
    )


def _load_env_values() -> dict[str, str]:
    """Load `.env`, then override with real environment variables."""
    values = _read_dotenv()
    for key in [
        ENV_AUTHORIZATION,
        ENV_COOKIE,
        ENV_OUTPUT_DIR,
        ENV_PAGE_SIZE,
        ENV_PROVIDER,
        ENV_KRS_VER,
        ENV_CREDENTIAL_PATH,
        ENV_CREDENTIAL_LATEST_URL,
        ENV_CREDENTIAL_API_KEY,
        ENV_CREDENTIAL_CACHE_TTL_SECONDS,
        ENV_OPS_URL,
        ENV_OPS_SYSTEM_URL,
    ]:
        value = os.environ.get(key)
        if value:
            values[key] = value
    return values


def _read_dotenv() -> dict[str, str]:
    """Find and parse the nearest `.env` from cwd upward."""
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        dotenv = directory / ".env"
        if dotenv.exists():
            return _parse_dotenv(dotenv)
    return {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE entries from `.env`."""
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
    """Parse a positive integer with a default fallback."""
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _build_default_credential_latest_url() -> str | None:
    """Build the default Xiyou credential endpoint from the active ops env."""
    ops_system_url = _resolve_ops_system_url()
    if not ops_system_url:
        return None
    parts = urlsplit(ops_system_url)
    if not parts.scheme or not parts.netloc:
        return None
    path = parts.path.rstrip("/")
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"{path}/api/v1/mcp-accounts",
            "platform=xiyou",
            "",
        )
    )


def _resolve_ops_system_url() -> str | None:
    """Resolve the active ops base URL from env first, then shared config."""
    direct = (os.environ.get(ENV_OPS_SYSTEM_URL) or "").strip()
    if direct:
        return direct.rstrip("/")

    from_loaded_env = _read_dotenv().get(ENV_OPS_SYSTEM_URL, "").strip()
    if from_loaded_env:
        return from_loaded_env.rstrip("/")

    fallback = (get_ops_system_url() or "").strip()
    if fallback:
        return fallback.rstrip("/")
    return None
