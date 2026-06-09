"""Shared Sif run helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def build_job_id(prefix: str, key: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"{prefix}-{key}-{timestamp}-{suffix}"


def timestamp_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def resolve_root_dir(output_dir: str | None, default_output_dir: Path, job_id: str) -> Path:
    base_dir = Path(output_dir).expanduser() if output_dir else default_output_dir
    if not base_dir.is_absolute():
        base_dir = Path.cwd() / base_dir
    return base_dir.resolve() / job_id


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_sections(value: list[str], defaults: list[str], aliases: dict[str, str] | None = None) -> list[str]:
    if not value:
        return defaults
    aliases = aliases or {}
    sections: list[str] = []
    for item in value:
        for part in str(item).split(","):
            key = part.strip()
            if not key or key.lower() == "all":
                return defaults
            normalized = aliases.get(key) or aliases.get(key.lower()) or key
            if normalized not in sections:
                sections.append(normalized)
    return sections or defaults


def parse_asins(value: str | None) -> list[str]:
    return [item.strip().upper() for item in (value or "").split(",") if item.strip()]
