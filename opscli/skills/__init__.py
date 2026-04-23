"""opscli skills 模块。

提供 Claude Code / OpenClaw 的 Skill 生命周期管理能力，包括：
- 发现：扫描本地已安装的 Skill
- 安装：从内置模板安装到指定目录
- 状态：查询本地和远端版本对比
- 升级：从运营系统后端拉取最新数据

典型工作流程：
1. 用户执行 `opscli skills install ops-dataset-query` 安装 Skill
2. Skill 被部署到 .claude/skills 或 .openclaw/skills
3. 用户执行 `opscli skills upgrade` 拉取远端最新数据

CLI 入口通过 cli.py 注册到 opscli 顶级命令：
- opscli skills list     # 列出已安装的 Skill
- opscli skills install # 安装 Skill
- opscli skills status # 查看安装状态
- opscli skills upgrade # 升级到远端最新版本
"""

from opscli.skills.domain.models import (
    SkillBatchInstallResult,
    SkillBatchUpgradeResult,
    SkillInstallResult,
    SkillRecord,
    SkillUpgradeResult,
)
from opscli.skills.services.manager import SkillsManager

__all__ = [
    "SkillRecord",
    "SkillInstallResult",
    "SkillBatchInstallResult",
    "SkillUpgradeResult",
    "SkillBatchUpgradeResult",
    "SkillsManager",
]
