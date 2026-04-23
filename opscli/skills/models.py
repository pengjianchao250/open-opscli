"""skills models 兼容导出。"""

from opscli.skills.domain.models import (
    SkillBatchInstallResult,
    SkillBatchUpgradeResult,
    SkillInstallResult,
    SkillRecord,
    SkillUpgradeResult,
    runtime_to_tool_name,
)

__all__ = [
    "runtime_to_tool_name",
    "SkillRecord",
    "SkillInstallResult",
    "SkillBatchInstallResult",
    "SkillUpgradeResult",
    "SkillBatchUpgradeResult",
]
