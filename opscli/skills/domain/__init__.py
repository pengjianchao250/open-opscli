"""skills 领域模型与异常。"""

from opscli.skills.domain.exceptions import SkillRemoteError, SkillsError, error_to_dict
from opscli.skills.domain.models import (
    SkillBatchInstallResult,
    SkillBatchUpgradeResult,
    SkillInstallResult,
    SkillRecord,
    SkillUpgradeResult,
    runtime_to_tool_name,
)

__all__ = [
    "SkillsError",
    "SkillRemoteError",
    "error_to_dict",
    "runtime_to_tool_name",
    "SkillRecord",
    "SkillInstallResult",
    "SkillBatchInstallResult",
    "SkillUpgradeResult",
    "SkillBatchUpgradeResult",
]
