"""预取计划后台运行使用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PrefetchRunClaim:
    """一条已经由当前宿主取得租约的预取运行。"""

    run_id: int
    schedule_id: int
    source_system: str
    scenario: str
    request: dict[str, Any]
    trigger_type: str
    scheduled_for: datetime

    @property
    def job_id(self) -> str:
        """返回可跨重试复用的确定性来源任务 ID。"""
        source = self.source_system.replace("_", "-")
        return f"Prefetch-{source}-{self.run_id}"
