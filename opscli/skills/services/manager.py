"""Skill 生命周期管理器。

提供 Skill 的安装、列表查询、状态检查、升级等核心业务逻辑。
是 CLI 层（cli.py）和底层组件（detector/updater）之间的中间协调层。
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from opscli.config import CONFIG_DIR
from opscli.skills.discovery.detector import SkillDetector
from opscli.skills.domain.exceptions import error_to_dict
from opscli.skills.domain.models import (
    SkillBatchInstallResult,
    SkillBatchUpgradeResult,
    SkillInstallResult,
    SkillRecord,
    SkillUpgradeResult,
    runtime_to_tool_name,
)
from opscli.skills.packaging import get_builtin_templates_dir
from opscli.skills.sync.updater import SkillsUpdater

_logger = logging.getLogger("opscli.skills")


class SkillsManager:
    """Skill 管理器，协调检测器和更新器完成 Skill 生命周期管理。"""

    def __init__(self, *, registry_path: Path | None = None) -> None:
        self.detector = SkillDetector()             # 负责 Skill 发现
        self.updater = SkillsUpdater()              # 负责远端数据拉取和升级
        self.templates_dir = get_builtin_templates_dir()  # 内置 Skill 模板目录
        # 注册表路径：默认使用全局 CONFIG_DIR，测试时可注入临时路径实现隔离
        self._custom_registry_path = registry_path

    def list_templates(self) -> list[dict]:
        """扫描内置模板目录，返回可安装的 Skill 列表。

        每项包含 name、version、description（从 SKILL.md 首段提取）。
        """
        templates: list[dict] = []
        if not self.templates_dir.exists():
            return templates
        for skill_dir in sorted(p for p in self.templates_dir.iterdir() if p.is_dir()):
            version_file = skill_dir / "data" / "VERSION.json"
            if not version_file.exists():
                continue
            try:
                payload = json.loads(version_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            version = str(payload.get("version", "unknown"))
            description = self._extract_skill_description(skill_dir)
            templates.append({"name": skill_dir.name, "version": version, "description": description})
        return templates

    def _extract_skill_description(self, skill_dir: Path) -> str:
        """从 SKILL.md 提取 Skill 简介（标题后第一个非空行）。

        自动跳过 YAML frontmatter（--- 包裹区域）。
        """
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return ""
        try:
            lines = skill_md.read_text(encoding="utf-8").splitlines()
        except Exception:
            return ""

        # 跳过 YAML frontmatter（以 --- 开头和结尾的区域）
        in_frontmatter = False
        content_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped == "---" and not content_lines:
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            content_lines.append(line)

        # 从正文内容中提取：跳过标题行（# 开头），取第一个非空的普通文本行
        skip_title = True
        for line in content_lines:
            stripped = line.strip()
            if skip_title and stripped.startswith("#"):
                skip_title = False
                continue
            if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
                return stripped[:30] + ("…" if len(stripped) > 30 else "")
        return ""

    def list_skills(self, skills_dir: str | None = None, cwd: Path | None = None) -> list[SkillRecord]:
        """列出所有已安装的 Skill，委托给 SkillDetector.discover()。"""
        return self.detector.discover(skills_dir=skills_dir, cwd=cwd)

    def install(
        self,
        skill_name: str,
        *,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        runtime: str | list[str] | None = None,
        force: bool = False,
    ) -> SkillBatchInstallResult:
        """从内置模板安装 Skill 到目标目录。

        流程：
        1. 检查模板是否存在（只支持内置 Skill）
        2. 确定安装目标路径（显式指定 或 自动检测）
        3. 若目标已存在且未指定 force，则报错
        4. 将模板目录整体复制到目标位置

        Args:
            skill_name: 要安装的 Skill 名称（如 "ops-dataset-query"）
            skills_dir: 显式指定安装根目录
            cwd: 当前工作目录，用于自动检测安装目标
            runtime: 运行时类型（claude/openclaw）
            force: 是否覆盖已存在的安装
        """
        template_dir = self.templates_dir / skill_name
        if not template_dir.exists():
            raise ValueError(f"当前发行包未包含内置 Skill: {skill_name}")

        current = cwd or Path.cwd()
        if skills_dir:
            targets = [(str(runtime or "custom"), Path(skills_dir).expanduser())]
        else:
            runtime_list = self._normalize_runtime_arg(runtime)
            targets = self.detector.detect_install_targets(
                cwd=current,
                preferred_runtimes=runtime_list,
            )

        installs: list[SkillInstallResult] = []
        for target_runtime, target_root in targets:
            target_root.mkdir(parents=True, exist_ok=True)
            target_dir = target_root / skill_name

            replaced = False
            if target_dir.exists():
                if not force:
                    raise ValueError(f"Skill 已存在: {target_dir}")
                shutil.rmtree(target_dir)
                replaced = True

            # 安装 Skill 时跳过 Python 运行缓存，避免把本地验证产物复制给 Agent。
            shutil.copytree(
                template_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            # 记录本次安装到注册表，供 upgrade 无 --skills-dir 时自动定位
            self._record_install(skill_name, target_dir, target_runtime)
            installs.append(
                SkillInstallResult(
                    name=skill_name,
                    runtime=target_runtime,
                    target_dir=target_dir,
                    version=self._read_version(target_dir),
                    replaced=replaced,
                )
            )

        return SkillBatchInstallResult(name=skill_name, installs=installs)

    def status(self, skills_dir: str | None = None, cwd: Path | None = None) -> dict:
        """查询 Skill 安装状态，包含本地信息和远端版本对比。

        返回结构：
        - installed: 本地已安装 Skill 列表（附带远端版本和是否有更新）
        - remote_manifest: 远端 manifest 数据（可能为 None）
        - remote_error: 远端请求失败时的错误信息
        """
        records = self.list_skills(skills_dir=skills_dir, cwd=cwd)

        # 获取远端 manifest（仅支持 ops-dataset-query）
        remote_manifest = None
        remote_summary = None
        remote_error = None
        try:
            remote_summary = self.updater.build_remote_summary("ops-dataset-query")
            remote_manifest = remote_summary.get("manifest")
        except Exception as exc:
            remote_error = error_to_dict(exc)

        remote_version = None
        if remote_manifest:
            remote_version = str(remote_manifest.get("version", "v0.0.0"))

        # 为每个已安装 Skill 附带远端版本信息
        enriched: list[dict] = []
        for item in records:
            row = item.to_dict()
            if item.name == "ops-dataset-query" and remote_version:
                row["remote_version"] = remote_version
                row["has_update"] = self.updater.compare_versions(item.version, remote_version) < 0
            else:
                row["remote_version"] = None
                row["has_update"] = False
            enriched.append(row)

        return {
            "skills": self._summarize_installed_skills(enriched),
            "installed": enriched,
            "remote_manifest": remote_manifest,
            "remote_summary": remote_summary,
            "remote_error": remote_error,
        }

    def upgrade(
        self,
        *,
        name: str = "ops-dataset-query",
        skills_dir: str | None = None,
        cwd: Path | None = None,
        force: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> SkillBatchUpgradeResult:
        """升级指定 Skill 到最新版本。

        当前支持 ops-dataset-query 与 ops-amazon-rufus。会先查找本地已安装的记录，
        再委托给 SkillsUpdater 执行实际的远端数据拉取和文件替换。

        Args:
            name: 要升级的 Skill 名称
            skills_dir: 指定扫描目录
            cwd: 当前工作目录
            force: 是否强制升级（即使版本号相同也重新拉取）
            on_step: 可选进度回调，每个阶段开始时调用，参数为描述字符串
        """
        records = self.list_skills(skills_dir=skills_dir, cwd=cwd)
        targets = [item for item in records if item.name == name]

        # 若未指定 skills_dir，从注册表补充可能安装到自定义目录的记录
        if not skills_dir:
            targets = self._merge_registry_targets(name, targets)

        if not targets:
            raise ValueError(f"未找到已安装 Skill: {name}")
        if name not in {"ops-dataset-query", "ops-amazon-rufus"}:
            raise ValueError(f"暂不支持升级 Skill: {name}")

        # 远端数据对所有本地安装实例完全相同，只拉取一次，再分发写入各目录
        upgrade_data = self.updater.fetch_upgrade_data(name, on_step=on_step)

        if on_step:
            dir_count = len(targets)
            on_step(f"写入本地文件到 {dir_count} 个目录..." if dir_count > 1 else "写入本地文件...")

        results = []
        for target in targets:
            results.append(self.updater.apply_upgrade_data(target, upgrade_data, force=force, on_step=None))

        return SkillBatchUpgradeResult(name=name, results=results)

    def _normalize_runtime_arg(self, runtime: str | list[str] | None) -> list[str] | None:
        """统一解析 runtime 参数。"""
        if runtime is None:
            return None
        if isinstance(runtime, list):
            return runtime
        parts = [item.strip() for item in runtime.split(",") if item.strip()]
        return parts or None

    def _read_version(self, target_dir: Path) -> str:
        """从安装目录的 data/VERSION.json 中读取版本号。"""
        version_file = target_dir / "data" / "VERSION.json"
        payload = json.loads(version_file.read_text(encoding="utf-8"))
        return str(payload.get("version", "unknown"))

    @property
    def _registry_path(self) -> Path:
        """安装注册表文件路径，默认为 ~/.config/opscli/installed_skills.json。

        构造时传入 registry_path 可覆盖，用于测试隔离。
        """
        return self._custom_registry_path if self._custom_registry_path is not None else CONFIG_DIR / "installed_skills.json"

    def _read_registry(self) -> dict:
        """读取安装注册表，文件不存在或解析失败时返回空字典。"""
        if not self._registry_path.exists():
            return {}
        try:
            return json.loads(self._registry_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_registry(self, data: dict) -> None:
        """将注册表数据写入文件，确保父目录存在。"""
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._registry_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _record_install(self, skill_name: str, target_dir: Path, runtime: str) -> None:
        """在注册表中写入一条安装记录。

        同一 skill 可安装到多个目录，每个目录保留独立记录。
        若同路径已有记录则更新 installed_at，避免重复追加。
        写入失败时静默忽略，不影响 install 主流程。
        """
        try:
            registry = self._read_registry()
            entries: list[dict] = registry.setdefault(skill_name, [])
            target_str = str(target_dir)
            now = datetime.now(timezone.utc).isoformat()

            # 查找同路径的已有记录并更新，否则追加新条目
            for entry in entries:
                if entry.get("target_dir") == target_str:
                    entry["installed_at"] = now
                    entry["runtime"] = runtime
                    break
            else:
                entries.append({"target_dir": target_str, "runtime": runtime, "installed_at": now})

            self._write_registry(registry)
        except Exception as _reg_exc:
            # 注册表写入失败不应阻断安装流程，但记录警告
            _logger.warning("注册表写入失败（不影响安装）: %s", _reg_exc)

    def _merge_registry_targets(self, skill_name: str, existing: list[SkillRecord]) -> list[SkillRecord]:
        """将注册表中的安装路径合并到已发现记录列表（去重）。

        用于 upgrade 时补充通过 --skills-dir 安装到自定义目录的 Skill，
        这些目录不在 SkillDetector 的扫描范围内。
        同时自动清理注册表中目录已不存在的过期条目。

        Args:
            skill_name: Skill 名称
            existing: 文件系统扫描已发现的记录列表
        Returns:
            合并后的记录列表，新增条目附加在末尾
        """
        registry = self._read_registry()
        entries = registry.get(skill_name, [])
        if not entries:
            return existing

        # 已发现的路径集合，用于去重
        existing_paths = {str(r.root) for r in existing}
        merged = list(existing)
        stale_indices: list[int] = []

        for i, entry in enumerate(entries):
            target_dir_str = entry.get("target_dir", "")
            if not target_dir_str or target_dir_str in existing_paths:
                continue
            target_dir = Path(target_dir_str)
            version_file = target_dir / "data" / "VERSION.json"
            # 验证目录和 VERSION.json 仍然存在（防止目录被手动删除）
            if not target_dir.exists() or not version_file.exists():
                stale_indices.append(i)
                continue
            try:
                payload = json.loads(version_file.read_text(encoding="utf-8"))
                version = str(payload.get("version", "v0.0.0"))
            except Exception:
                continue
            merged.append(
                SkillRecord(
                    name=skill_name,
                    version=version,
                    runtime=entry.get("runtime", "claude"),
                    root=target_dir,
                    version_file=version_file,
                )
            )
            existing_paths.add(target_dir_str)

        # 自动清理注册表中目录已不存在的过期条目，避免反复累积
        if stale_indices:
            registry[skill_name] = [e for j, e in enumerate(entries) if j not in stale_indices]
            try:
                self._write_registry(registry)
            except Exception as _reg_exc:
                _logger.warning("注册表清理写入失败: %s", _reg_exc)

        return merged

    def _summarize_installed_skills(self, records: list[dict]) -> list[dict]:
        """按 skill 名称聚合安装记录，生成稳定的对外 JSON 结构。"""
        grouped: dict[str, dict] = {}
        for item in records:
            group = grouped.setdefault(
                item["name"],
                {
                    "name": item["name"],
                    "local_version": item["version"],
                    "remote_version": item["remote_version"],
                    "has_update": item["has_update"],
                    "installed_paths": [],
                },
            )

            if item["version"] != group["local_version"]:
                group["local_version"] = max(str(group["local_version"]), str(item["version"]))
            if item["remote_version"] and not group["remote_version"]:
                group["remote_version"] = item["remote_version"]
            group["has_update"] = group["has_update"] or item["has_update"]
            group["installed_paths"].append(
                {
                    "tool": runtime_to_tool_name(item["runtime"]),
                    "path": item["root"],
                }
            )

        return list(grouped.values())
