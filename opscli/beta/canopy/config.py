"""beta Canopy API 配置。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CANOPY_BASE_URL = "https://rest.canopyapi.co"
CANOPY_API_KEY_PLACEHOLDER = "<YOUR_CANOPY_API_KEY>"
ENV_OUTPUT_DIR = "OPSCLI_BETA_CANOPY_OUTPUT_DIR"
PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "api_runs"
DEFAULT_API_KEY_PATH = PACKAGE_DIR / "api_key"


@dataclass(frozen=True)
class CanopySettings:
    """Canopy beta 运行配置。"""

    output_dir: Path = DEFAULT_OUTPUT_DIR

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的配置摘要。"""
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        return payload


def load_settings() -> CanopySettings:
    """读取 beta Canopy 配置。"""
    output_dir = Path(os.environ.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    return CanopySettings(output_dir=output_dir)


def load_local_api_key() -> str | None:
    """读取本地保存的 Canopy API key。"""
    path = DEFAULT_API_KEY_PATH.expanduser()
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None
