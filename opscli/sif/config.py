"""Sif 平台运行配置。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR


ENV_COOKIE = "OPSCLI_SIF_COOKIE"
ENV_TOKEN = "OPSCLI_SIF_TOKEN"
ENV_USERNAME = "OPSCLI_SIF_USERNAME"
ENV_PASSWORD = "OPSCLI_SIF_PASSWORD"
ENV_OUTPUT_DIR = "OPSCLI_SIF_OUTPUT_DIR"

BASE_URL = "https://www.sif.com"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "sif" / "sales" / "runs"
DEFAULT_FEATURE_OUTPUT_DIRS = {
    "sales": CONFIG_DIR / "sif" / "sales" / "runs",
    "traffic": CONFIG_DIR / "sif" / "traffic" / "runs",
    "compare": CONFIG_DIR / "sif" / "compare" / "runs",
    "ranking": CONFIG_DIR / "sif" / "ranking" / "runs",
    "operation_time_machine": CONFIG_DIR / "sif" / "operation_time_machine" / "runs",
    "product_time_machine": CONFIG_DIR / "sif" / "product_time_machine" / "runs",
}


@dataclass(frozen=True)
class SifSettings:
    """Sif 运行配置，敏感信息不进入公开输出。"""

    base_url: str = BASE_URL
    cookie: str | None = None
    token: str | None = None
    username: str | None = None
    password: str | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["has_cookie"] = bool(self.cookie)
        payload["has_token"] = bool(self.token)
        payload["has_username"] = bool(self.username)
        payload["has_password"] = bool(self.password)
        payload.pop("cookie", None)
        payload.pop("token", None)
        payload.pop("username", None)
        payload.pop("password", None)
        return payload


def load_settings() -> SifSettings:
    """从环境变量读取 Sif 配置。"""
    output_dir = Path(os.environ.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    return SifSettings(
        cookie=os.environ.get(ENV_COOKIE) or None,
        token=os.environ.get(ENV_TOKEN) or None,
        username=os.environ.get(ENV_USERNAME) or None,
        password=os.environ.get(ENV_PASSWORD) or None,
        output_dir=output_dir,
    )


def default_output_dir_for_feature(feature_key: str) -> Path:
    configured = os.environ.get(ENV_OUTPUT_DIR)
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_FEATURE_OUTPUT_DIRS.get(feature_key, DEFAULT_OUTPUT_DIR)
