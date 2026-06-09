"""通用工单数据模型。"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass
class TaskResult:
    """工单创建结果。"""

    success: bool
    task_id: str | None = None
    message: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class TaskStatus:
    """工单状态/详情。"""

    task_id: str
    status: str = "unknown"
    message: str | None = None
    detail: dict | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
