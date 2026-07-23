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

import dataclasses

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
from opscli.skills.link.linker import SkillsLinker
from opscli.skills.packaging import get_builtin_templates_dir, get_central_skills_dir
from opscli.skills.sync.updater import SkillsUpdater

_logger = logging.getLogger("opscli.skills")


class SkillsManager:
    """Skill 管理器，协调检测器和更新器完成 Skill 生命周期管理。"""

    def __init__(
        self,
        *,
        registry_path: Path | None = None,
        central_skills_dir: Path | None = None,
        detector: SkillDetector | None = None,
    ) -> None:
        # 允许外部注入 detector，方便测试时隔离真实全局目录扫描
        self.detector = detector if detector is not None else SkillDetector()
        self.updater = SkillsUpdater()              # 负责远端数据拉取和升级
        self.linker = SkillsLinker()                # 负责创建/删除工具链接
        self.templates_dir = get_builtin_templates_dir()  # 内置 Skill 模板目录
        # 注册表路径：默认使用全局 CONFIG_DIR，测试时可注入临时路径实现隔离
        self._custom_registry_path = registry_path
        # 中央存储根目录：测试时可注入临时路径
        self._custom_central_skills_dir = central_skills_dir

    @property
    def _central_skills_dir(self) -> Path:
        """中央 Skills 存储根目录（~/.opscli/skills 或测试注入路径）。"""
        return self._custom_central_skills_dir if self._custom_central_skills_dir is not None else get_central_skills_dir()

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
        link_targets: list[tuple[str, Path]] | None = None,
        cwd: Path | None = None,
        runtime: str | list[str] | None = None,
        force: bool = False,
    ) -> SkillBatchInstallResult:
        """从内置模板安装 Skill。

        模式 A（旧，向后兼容）：显式传入 skills_dir
            → 将模板整体复制到 skills_dir/<skill_name>，不使用中央存储。

        模式 B（新，默认）：不传 skills_dir
            → Step 1: 模板复制到中央存储 (~/.opscli/skills/<skill_name>)
            → Step 2: 在每个检测到的 AI 工具 skills 目录下创建指向中央存储的链接
            升级时只需更新中央存储，所有工具链接自动同步。

        Args:
            skill_name: 要安装的 Skill 名称（如 "ops-dataset-query"）
            skills_dir: 显式指定安装根目录（触发旧复制模式）
            link_targets: 显式指定链接目标列表 [(runtime, skills_dir), ...]
            cwd: 当前工作目录，用于自动检测安装目标
            runtime: 运行时类型（claude/openclaw/all 或逗号分隔）
            force: 是否覆盖已存在的安装/链接
        """
        template_dir = self.templates_dir / skill_name
        if not template_dir.exists():
            raise ValueError(f"当前发行包未包含内置 Skill: {skill_name}")

        # 执行安装（模式 A 或模式 B）
        if skills_dir:
            result = self._install_copy(
                skill_name,
                template_dir=template_dir,
                target_root=Path(skills_dir).expanduser(),
                runtime=str(runtime or "custom"),
                force=force,
            )
        else:
            result = self._install_central(
                skill_name,
                template_dir=template_dir,
                link_targets=link_targets,
                cwd=cwd,
                runtime=runtime,
                force=force,
            )

        # 安装成功后，自动注入 PostToolUse Hook 到 ~/.claude/settings.json
        # 确保用户在任意目录下触发 Skill 时都能自动上报使用次数
        try:
            from opscli.skills.hooks.settings_injector import ensure_skill_usage_hook
            ensure_skill_usage_hook()
        except Exception as _hook_exc:
            _logger.debug("Hook 注入失败（不影响安装）: %s", _hook_exc)

        return result

    def _install_copy(
        self,
        skill_name: str,
        *,
        template_dir: Path,
        target_root: Path,
        runtime: str,
        force: bool,
    ) -> SkillBatchInstallResult:
        """旧复制模式：将模板直接复制到指定目录（兼容 --skills-dir 用法）。"""
        target_root.mkdir(parents=True, exist_ok=True)
        target_dir = target_root / skill_name

        replaced = False
        if target_dir.exists():
            if not force:
                raise ValueError(f"Skill 已存在: {target_dir}")
            shutil.rmtree(target_dir)
            replaced = True

        shutil.copytree(
            template_dir,
            target_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        self._record_install(skill_name, target_dir, runtime)
        return SkillBatchInstallResult(
            name=skill_name,
            installs=[
                SkillInstallResult(
                    name=skill_name,
                    runtime=runtime,
                    target_dir=target_dir,
                    version=self._read_version(target_dir),
                    replaced=replaced,
                    central_dir=None,
                    link_method=None,
                )
            ],
        )

    def _install_central(
        self,
        skill_name: str,
        *,
        template_dir: Path,
        link_targets: list[tuple[str, Path]] | None,
        cwd: Path | None,
        runtime: str | list[str] | None,
        force: bool,
    ) -> SkillBatchInstallResult:
        """中央存储模式：复制到 ~/.opscli/skills，再在各工具目录建链接。"""
        central_skill_dir = self._central_skills_dir / skill_name

        # Step 1：将模板写入中央存储
        # force 时无条件覆盖；否则比较内置模板与已有中央副本的版本，
        # 只要版本号不一致就以模板为准覆盖（允许降级），保证 install 始终与当前发行包模板对齐；
        # 版本号完全相同时复用旧副本，避免多余的删除重拷。
        if central_skill_dir.exists():
            if force or self._template_version_differs(template_dir, central_skill_dir):
                shutil.rmtree(central_skill_dir)
        if not central_skill_dir.exists():
            self._central_skills_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                template_dir,
                central_skill_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )

        version = self._read_version(central_skill_dir)

        # Step 2：确定链接目标列表
        if link_targets is not None:
            targets = link_targets
        else:
            current = cwd or Path.cwd()
            runtime_list = self._normalize_runtime_arg(runtime)
            targets = self._detect_link_targets(current, runtime_list)

        # Step 3：在各工具目录下创建链接
        installs: list[SkillInstallResult] = []
        for target_runtime, tool_skills_dir in targets:
            # 链接已存在且正确指向中央副本时：中央内容刚按版本刷新过，
            # 符号链接会自动反映新版本。此处用 force 重建（仅删链接、不动中央内容），
            # 幂等刷新，避免普通 install 因"目标已存在"报错；
            # 若链接缺失或指向异常，则保持原有 force 语义（非 force 时报错以防误删未知内容）。
            link_path = tool_skills_dir / skill_name
            link_force = force or self.linker.is_link_valid(link_path, central_skill_dir)
            link_result = self.linker.link(
                skill_name,
                central_skill_dir,
                tool_skills_dir,
                force=link_force,
            )
            self._record_install(
                skill_name,
                link_result.link_path,
                target_runtime,
                central_dir=central_skill_dir,
                link_method=link_result.method,
            )
            installs.append(
                SkillInstallResult(
                    name=skill_name,
                    runtime=target_runtime,
                    target_dir=link_result.link_path,
                    version=version,
                    replaced=link_result.replaced,
                    central_dir=central_skill_dir,
                    link_method=link_result.method,
                )
            )

        # 无 AI 工具可链接时：用一条 "central" 记录表示中央存储安装结果
        if not installs:
            installs.append(
                SkillInstallResult(
                    name=skill_name,
                    runtime="central",
                    target_dir=central_skill_dir,
                    version=version,
                    replaced=False,
                    central_dir=central_skill_dir,
                    link_method=None,
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

        # 无 AI 工具时，检查中央存储是否有该 Skill（直接对中央目录执行升级）
        if not targets and not skills_dir:
            central_skill_dir = self._central_skills_dir / name
            version_file = central_skill_dir / "data" / "VERSION.json"
            if central_skill_dir.exists() and version_file.exists():
                try:
                    payload = json.loads(version_file.read_text(encoding="utf-8"))
                    version = str(payload.get("version", "v0.0.0"))
                except Exception:
                    version = "v0.0.0"
                targets = [
                    SkillRecord(
                        name=name,
                        version=version,
                        runtime="central",
                        root=central_skill_dir,
                        version_file=version_file,
                    )
                ]

        if not targets:
            raise ValueError(f"未找到已安装 Skill: {name}（未检测到 AI 工具，且中央存储中也不存在该 Skill）")
        if name not in {"ops-dataset-query", "ops-amazon-rufus"}:
            raise ValueError(f"暂不支持升级 Skill: {name}")

        # ops-amazon-rufus 使用独立升级接口（本地题库，不依赖 ops-dataset-query 的 manifest 体系）
        if name == "ops-amazon-rufus":
            results: list[SkillUpgradeResult] = []
            for t in targets:
                results.append(self.updater.upgrade_ops_amazon_rufus(t, force=force))
            return SkillBatchUpgradeResult(name=name, results=results)

        # ops-dataset-query：远端数据对所有本地安装实例完全相同，只拉取一次
        upgrade_data = self.updater.fetch_upgrade_data(name, on_step=on_step)

        # 中央存储模式下，多个工具的链接指向同一目录，按 resolve() 去重避免重复写入
        real_path_to_result: dict[str, SkillUpgradeResult] = {}
        deduped: list[SkillRecord] = []
        for t in targets:
            real = str(t.root.resolve())
            if real not in real_path_to_result:
                deduped.append(t)

        if on_step:
            dir_count = len(deduped)
            on_step(f"写入本地文件到 {dir_count} 个目录..." if dir_count > 1 else "写入本地文件...")

        # 只对去重后的目录执行实际写入
        for t in deduped:
            real = str(t.root.resolve())
            real_path_to_result[real] = self.updater.apply_upgrade_data(t, upgrade_data, force=force, on_step=None)

        # 为所有 targets（含重复链接）生成结果，保持输出结构完整
        results: list[SkillUpgradeResult] = []
        for t in targets:
            real = str(t.root.resolve())
            base = real_path_to_result[real]
            results.append(dataclasses.replace(base, runtime=t.runtime, target_dir=t.root))

        return SkillBatchUpgradeResult(name=name, results=results)

    def _detect_link_targets(
        self,
        cwd: Path,
        runtime_list: list[str] | None,
    ) -> list[tuple[str, Path]]:
        """检测链接目标，不产生虚假回退目标。

        优先级：
          1. 显式指定 runtime → 按 runtime 解析路径（用户明确知道目标）
          2. 当前目录下已有 AI 工具配置目录（项目级安装）
          3. 全局已安装的 AI 工具（检测 ~/.claude/、which claude 等）
          4. 以上均无 → 返回空列表（仅使用中央存储，不强制创建链接）

        与 detect_install_targets() 的区别：后者在无工具时会回退到
        (cwd/.claude/skills) 虚假目标，导致创建空目录，本方法避免此问题。
        """
        if runtime_list:
            # 用户显式指定了 runtime，尊重用户意图
            return self.detector.detect_install_targets(
                cwd=cwd, preferred_runtimes=runtime_list
            )

        # 优先检测当前项目目录下的 AI 工具配置
        project_targets = self.detector.detect_available_install_targets(cwd=cwd)
        if project_targets:
            return project_targets

        # 再检测全局安装的 AI 工具
        return self.detector.detect_global_install_targets()

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

    def _template_version_differs(self, template_dir: Path, central_skill_dir: Path) -> bool:
        """比较内置模板与中央副本的版本，版本号不一致时返回 True。

        用于 install 非 force 场景判断是否需要用模板覆盖已有中央副本：
        只要版本号不同（模板更高或更低）就以当前发行包模板为准覆盖（允许降级）。
        任一 VERSION.json 读取失败时返回 False，保守复用旧副本，避免误覆盖。
        """
        try:
            template_version = self._read_version(template_dir)
            central_version = self._read_version(central_skill_dir)
        except Exception:
            return False
        # compare_versions 返回 0 表示两版本相等；非 0 即不一致，需要以模板覆盖
        return self.updater.compare_versions(template_version, central_version) != 0

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

    def _record_install(
        self,
        skill_name: str,
        target_dir: Path,
        runtime: str,
        *,
        central_dir: Path | None = None,
        link_method: str | None = None,
    ) -> None:
        """在注册表中写入一条安装记录。

        同一 skill 可安装到多个目录，每个目录保留独立记录。
        若同路径已有记录则更新 installed_at，避免重复追加。
        central_dir / link_method 为中央存储模式新增字段，旧模式为 None。
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
                    if central_dir is not None:
                        entry["central_dir"] = str(central_dir)
                    if link_method is not None:
                        entry["link_method"] = link_method
                    break
            else:
                new_entry: dict = {
                    "target_dir": target_str,
                    "runtime": runtime,
                    "installed_at": now,
                }
                if central_dir is not None:
                    new_entry["central_dir"] = str(central_dir)
                if link_method is not None:
                    new_entry["link_method"] = link_method
                entries.append(new_entry)

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
