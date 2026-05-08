"""Skills 模块的数据模型定义。

包含 Skill 生命周期中各阶段的数据结构：发现记录、安装结果、升级结果。
所有 dataclass 均提供 to_dict() 方法用于 JSON 序列化输出。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


def runtime_to_tool_name(runtime: str) -> str:
    """将内部 runtime 标识转换为对外稳定的工具名。"""
    mapping = {
        "claude": "claude-code",
        "openclaw": "openclaw",
    }
    return mapping.get(runtime, runtime)


@dataclass
class SkillRecord:
    """已发现的 Skill 记录。

    由 SkillDetector 扫描磁盘目录后生成，描述一个已安装 Skill 的基本信息。
    """

    name: str           # Skill 名称，对应目录名
    version: str        # 当前版本号，读取自 data/VERSION.json
    runtime: str        # 运行时类型：claude 或 openclaw
    root: Path          # Skill 根目录绝对路径
    version_file: Path  # VERSION.json 文件绝对路径

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典，Path 字段转为字符串。"""
        data = asdict(self)
        data["runtime"] = runtime_to_tool_name(self.runtime)
        data["root"] = str(self.root)
        data["version_file"] = str(self.version_file)
        return data


@dataclass
class SkillInstallResult:
    """Skill 安装操作的结果。

    由 SkillsManager.install() 返回，记录安装目标路径及是否覆盖了已有安装。
    """

    name: str           # Skill 名称
    runtime: str        # 目标运行时类型
    target_dir: Path    # 安装目标目录
    version: str        # 安装后的版本号
    replaced: bool      # 是否覆盖了已有安装

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典，Path 字段转为字符串。"""
        data = asdict(self)
        data["runtime"] = runtime_to_tool_name(self.runtime)
        data["target_dir"] = str(self.target_dir)
        return data


@dataclass
class SkillBatchInstallResult:
    """批量安装结果。"""

    name: str
    installs: list[SkillInstallResult]
    injected_configs: list[Path] = None  # 已注入铁律的配置文件路径列表

    def __post_init__(self):
        if self.injected_configs is None:
            self.injected_configs = []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.installs[0].version if self.installs else "unknown",
            "installed_paths": [
                {
                    "tool": runtime_to_tool_name(item.runtime),
                    "path": str(item.target_dir),
                    "replaced": item.replaced,
                }
                for item in self.installs
            ],
            "injected_configs": [str(p) for p in self.injected_configs],
        }


@dataclass
class SkillUpgradeResult:
    """Skill 升级操作的结果。

    由 SkillsUpdater.upgrade_dataset_fields() 返回，记录版本变化和是否实际更新。
    """

    name: str               # Skill 名称
    from_version: str       # 升级前版本号
    to_version: str         # 升级后版本号（未更新时与 from_version 相同）
    runtime: str            # 所属运行时
    target_dir: Path        # Skill 根目录
    updated: bool           # 是否实际执行了更新
    field_count: int = 0    # 当前用户可见字段数

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典，Path 字段转为字符串。"""
        data = asdict(self)
        data["runtime"] = runtime_to_tool_name(self.runtime)
        data["target_dir"] = str(self.target_dir)
        return data


@dataclass
class SkillBatchUpgradeResult:
    """批量升级结果。"""

    name: str
    results: list[SkillUpgradeResult]

    def to_dict(self) -> dict:
        updated = self._group_results(updated=True)
        already_latest = self._group_results(updated=False)
        return {
            "updated": updated,
            "already_latest": already_latest,
            "failed": [],
        }

    def _group_results(self, *, updated: bool) -> list[dict]:
        grouped: dict[tuple[str, str, str, int], dict] = {}
        for item in self.results:
            if item.updated is not updated:
                continue
            key = (item.name, item.from_version, item.to_version, item.field_count)
            group = grouped.setdefault(
                key,
                {
                    "name": item.name,
                    "from_version": item.from_version,
                    "to_version": item.to_version,
                    "field_count": item.field_count,
                    "tools": [],
                },
            )
            group["tools"].append(runtime_to_tool_name(item.runtime))

        return list(grouped.values())
