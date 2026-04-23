"""skills exceptions 兼容导出。"""

from opscli.skills.domain.exceptions import SkillRemoteError, SkillsError, error_to_dict

__all__ = ["SkillsError", "SkillRemoteError", "error_to_dict"]
