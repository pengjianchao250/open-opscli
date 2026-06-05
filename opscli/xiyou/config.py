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

DEFAULT_PROVIDER = "xiyou"
DEFAULT_PAGE_SIZE = 50
DEFAULT_SITE = "US"
DEFAULT_PERIOD = "week"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "xiyou" / "api_runs"


@dataclass(frozen=True)
class XiyouSettings:
    """西柚洞察接口直连运行配置。"""

    provider: str = DEFAULT_PROVIDER
    authorization: str | None = None
    cookie: str | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    page_size: int = DEFAULT_PAGE_SIZE
    default_site: str = DEFAULT_SITE
    default_period: str = DEFAULT_PERIOD
    krs_ver: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的配置摘要。"""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["has_authorization"] = bool(self.authorization)
        payload["has_cookie"] = bool(self.cookie)
        payload.pop("authorization", None)
        payload.pop("cookie", None)
        return payload


def load_settings() -> XiyouSettings:
    """从 `.env` 和环境变量读取西柚洞察配置。"""
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    page_size = _parse_int(values.get(ENV_PAGE_SIZE), DEFAULT_PAGE_SIZE)
    return XiyouSettings(
        provider=values.get(ENV_PROVIDER) or DEFAULT_PROVIDER,
        authorization=values.get(ENV_AUTHORIZATION) or None,
        cookie=values.get(ENV_COOKIE) or None,
        output_dir=output_dir,
        page_size=page_size,
        krs_ver=values.get(ENV_KRS_VER) or None,
    )


def _load_env_values() -> dict[str, str]:
    """读取 `.env` 后叠加真实环境变量，真实环境变量优先。"""
    values = _read_dotenv()
    for key in [ENV_AUTHORIZATION, ENV_COOKIE, ENV_OUTPUT_DIR, ENV_PAGE_SIZE, ENV_PROVIDER, ENV_KRS_VER]:
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

