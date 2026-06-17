"""卖家精灵异步任务状态文件管理。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_FILENAME = "status.json"


def now_iso() -> str:
    """返回带时区的当前时间字符串，用于任务状态追踪。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def status_path(root_dir: Path) -> Path:
    """返回任务目录下的状态文件路径。"""
    return root_dir / STATUS_FILENAME


def write_status(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """写入任务状态并返回写入内容。"""
    root_dir.mkdir(parents=True, exist_ok=True)
    path = status_path(root_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_status(root_dir: Path) -> dict[str, Any] | None:
    """读取任务状态文件；不存在时返回 None。"""
    path = status_path(root_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def base_status(
    *,
    job_id: str,
    scenario: str,
    site: str,
    period: str,
    state: str,
    stage: str,
    root_dir: Path,
) -> dict[str, Any]:
    """构造任务状态的基础结构。"""
    created_at = now_iso()
    return {
        "job_id": job_id,
        "scenario": scenario,
        "site": site,
        "period": period,
        "state": state,
        "stage": stage,
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
        "root_dir": str(root_dir),
        "error": None,
        "export": None,
    }


def error_to_dict(exc: Exception) -> dict[str, Any]:
    """将异常转换为可落盘的错误摘要。"""
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {"code": type(exc).__name__, "message": str(exc)}
