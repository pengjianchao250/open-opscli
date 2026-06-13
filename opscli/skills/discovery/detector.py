"""Skill 发现与检测模块。

负责扫描多个候选目录，发现已安装的 Skill 并生成 SkillRecord。
同时提供安装目标目录的检测逻辑，决定新 Skill 应安装到哪里。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

from opscli.skills.domain.models import SkillRecord

_logger = logging.getLogger("opscli.skills.detector")


class SkillDetector:
    """Skill 探测器，扫描磁盘目录发现已安装的 Skill。"""

    def candidate_dirs(self, skills_dir: str | None = None, cwd: Path | None = None) -> list[Path]:
        """收集所有候选扫描目录，按优先级排列并去重。

        优先级从高到低：
        1. 调用方显式指定的 skills_dir 参数
        2. 环境变量 OPSCLI_SKILLS_DIR
        3. 当前工作目录下的 .claude/skills
        4. 用户主目录下的 .claude/skills
        5. 用户主目录下的 .openclaw/skills
        """
        current = cwd or Path.cwd()
        candidates: list[Path] = []

        # 显式指定的目录优先级最高
        if skills_dir:
            candidates.append(Path(skills_dir).expanduser())

        # 环境变量指定的目录次之
        env_dir = os.getenv("OPSCLI_SKILLS_DIR")
        if env_dir:
            candidates.append(Path(env_dir).expanduser())

        # 默认候选目录（按工具优先级排列）
        home = Path.home()
        candidates.extend(
            [
                current / ".claude" / "skills",
                home / ".claude" / "skills",
                home / ".openclaw" / "skills",
                home / ".codex" / "skills",
                self._opencode_skills_dir(),
                home / ".workbuddy" / "skills",
                home / ".trae-cn" / "skills",
                home / ".agents" / "skills",
            ]
        )

        # AuWork（Windows 专属）：追加 ~/.auwork 下所有纯数字用户目录的 skills/，
        # 使 list/status/upgrade/unlink 能发现已安装到 AuWork 的 Skill
        candidates.extend(path for _, path in self._auwork_targets())

        # 按路径去重，避免同一目录被重复扫描
        seen: set[str] = set()
        result: list[Path] = []
        for item in candidates:
            key = str(item.resolve()) if item.exists() else str(item.expanduser())
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def discover(self, skills_dir: str | None = None, cwd: Path | None = None) -> list[SkillRecord]:
        """扫描所有候选目录，发现已安装的 Skill。

        判定条件：目录下必须存在 data/VERSION.json 文件。
        解析失败（JSON 格式错误等）的目录会被静默跳过。
        """
        records: list[SkillRecord] = []
        for base_dir in self.candidate_dirs(skills_dir=skills_dir, cwd=cwd):
            if not base_dir.exists():
                continue
            # 遍历子目录，按名称排序保证输出稳定
            for skill_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
                version_file = skill_dir / "data" / "VERSION.json"
                data_dir = skill_dir / "data"
                if version_file.exists():
                    # 正常情况：data/VERSION.json 存在，读取版本号
                    try:
                        payload = json.loads(version_file.read_text(encoding="utf-8"))
                    except Exception as _det_exc:
                        _logger.debug("跳过损坏的 VERSION.json: %s [%s]", version_file, _det_exc)
                        continue
                    version = str(payload.get("version", "unknown"))
                elif data_dir.exists():
                    # 兜底情况：data/ 目录存在但缺少 VERSION.json（安装后从未升级过），
                    # 视为未初始化安装，版本设为 v0.0.0，升级时会自动补全所有数据文件
                    version = "v0.0.0"
                else:
                    # data/ 目录不存在，不是合法的 Skill 目录
                    continue
                # 根据路径推断运行时类型
                runtime = self._infer_runtime(skill_dir)
                records.append(
                    SkillRecord(
                        name=skill_dir.name,
                        version=version,
                        runtime=runtime,
                        root=skill_dir,
                        version_file=version_file,
                    )
                )
        return records

    def detect_install_target(self, cwd: Path | None = None, preferred_runtime: str | None = None) -> tuple[str, Path]:
        """检测新 Skill 应该安装到哪个目录。

        优先使用 preferred_runtime 参数，否则根据当前目录下是否存在对应运行时目录推断。
        默认回退到 claude 运行时。

        Returns:
            (runtime, target_path) 二元组
        """
        current = cwd or Path.cwd()
        # 显式指定运行时
        runtime_dirs = {
            "claude":     current / ".claude" / "skills",
            "openclaw":   current / ".openclaw" / "skills",
            "codex":      current / ".codex" / "skills",
            "opencode":   current / ".opencode" / "skills",
            "workbuddy":  current / ".workbuddy" / "skills",
            "trae-cn":    current / ".trae-cn" / "skills",
            "agents":     current / ".agents" / "skills",
        }
        if preferred_runtime and preferred_runtime in runtime_dirs:
            return preferred_runtime, runtime_dirs[preferred_runtime]

        # 自动检测：根据当前目录下已有的运行时目录推断
        for runtime, path in runtime_dirs.items():
            if path.parent.exists():
                return runtime, path
        # 默认使用 claude 运行时
        return "claude", current / ".claude" / "skills"

    def detect_install_targets(self, cwd: Path | None = None, preferred_runtimes: list[str] | None = None) -> list[tuple[str, Path]]:
        """检测多个安装目标。"""
        current = cwd or Path.cwd()

        if preferred_runtimes:
            targets: list[tuple[str, Path]] = []
            for runtime in preferred_runtimes:
                normalized = runtime.strip().lower()
                if normalized == "all":
                    return self.detect_all_install_targets()
                # AuWork 是特殊运行时：一个运行时展开为 N 个目标目录，
                # 不能走单路径的 detect_install_target
                if normalized == "auwork":
                    targets.extend(self._auwork_targets())
                    continue
                _, path = self.detect_install_target(cwd=current, preferred_runtime=normalized)
                targets.append((normalized, path))
            return self._dedupe_targets(targets)

        available = self.detect_available_install_targets(cwd=current)
        if available:
            return available

        runtime, target = self.detect_install_target(cwd=current, preferred_runtime=None)
        return [(runtime, target)]

    def detect_available_install_targets(self, cwd: Path | None = None) -> list[tuple[str, Path]]:
        """根据当前目录已存在的运行时目录，返回可用目标列表（项目级/全局均适用）。

        当 cwd=Path.home() 时等价于全局检测（remote_installer 场景），
        因此必须覆盖所有支持的工具，与 detect_global_install_targets 的工具集保持一致。
        仅检测目录是否存在，不做 which 探测（which 探测由 detect_global_install_targets 负责）。
        """
        current = cwd or Path.cwd()
        targets: list[tuple[str, Path]] = []
        # Claude Code：.claude/ 目录存在
        if (current / ".claude").exists():
            targets.append(("claude", current / ".claude" / "skills"))
        # OpenClaw：.openclaw/ 目录存在
        if (current / ".openclaw").exists():
            targets.append(("openclaw", current / ".openclaw" / "skills"))
        # Codex CLI：.codex/ 目录存在
        if (current / ".codex").exists():
            targets.append(("codex", current / ".codex" / "skills"))
        # OpenCode：.config/opencode/ 目录存在（所有平台路径统一）
        if (current / ".config" / "opencode").exists():
            targets.append(("opencode", current / ".config" / "opencode" / "skills"))
        # WorkBuddy：.workbuddy/ 目录存在
        if (current / ".workbuddy").exists():
            targets.append(("workbuddy", current / ".workbuddy" / "skills"))
        # Trae Solo：.trae-cn/ 目录存在
        if (current / ".trae-cn").exists():
            targets.append(("trae-cn", current / ".trae-cn" / "skills"))
        # Agents：.agents/ 目录存在
        if (current / ".agents").exists():
            targets.append(("agents", current / ".agents" / "skills"))
        # AuWork（Windows 专属）：始终基于用户 home 探测，与 cwd 无关，
        # 自动纳入 ~/.auwork 下所有纯数字用户目录
        targets.extend(self._auwork_targets())
        return self._dedupe_targets(targets)

    def detect_global_install_targets(self) -> list[tuple[str, Path]]:
        """检测全局已安装的 AI 工具，返回对应的全局 Skills 安装目录。

        检测规则（opscli 多工具 Skills 支持路径对照表）：

        工具          macOS/Linux               Windows
        Claude Code   ~/.claude/skills/         %USERPROFILE%/.claude/skills/
        OpenClaw      ~/.openclaw/skills/        %USERPROFILE%/.openclaw/skills/
        Codex CLI     ~/.codex/skills/           %USERPROFILE%/.codex/skills/
        OpenCode      ~/.config/opencode/skills/ %USERPROFILE%/.config/opencode/skills/

        检测条件：配置目录存在 或 对应命令可用（which）。
        返回 [(runtime, skills_dir), ...] 列表，按检测顺序排列，已去重。
        """
        home = Path.home()
        targets: list[tuple[str, Path]] = []

        # Claude Code：~/.claude/ 存在 或 `which claude` 可用
        if (home / ".claude").exists() or shutil.which("claude") is not None:
            targets.append(("claude", home / ".claude" / "skills"))

        # OpenClaw：~/.openclaw/ 存在 或 `which openclaw` 可用
        if (home / ".openclaw").exists() or shutil.which("openclaw") is not None:
            targets.append(("openclaw", home / ".openclaw" / "skills"))

        # Codex CLI：~/.codex/ 存在 或 `which codex` 可用
        if (home / ".codex").exists() or shutil.which("codex") is not None:
            targets.append(("codex", home / ".codex" / "skills"))

        # OpenCode：~/.config/opencode/（所有平台统一）存在，或 `which opencode` 可用
        opencode_config = self._opencode_config_dir()
        if opencode_config.exists() or shutil.which("opencode") is not None:
            targets.append(("opencode", self._opencode_skills_dir()))

        # WorkBuddy：~/.workbuddy/ 存在 或 `which workbuddy` 可用
        if (home / ".workbuddy").exists() or shutil.which("workbuddy") is not None:
            targets.append(("workbuddy", home / ".workbuddy" / "skills"))

        # Trae Solo：~/.trae-cn/ 存在 或 `which trae` 可用（macOS/Linux/Windows 均为用户目录下 .trae-cn）
        if (home / ".trae-cn").exists() or shutil.which("trae") is not None:
            targets.append(("trae-cn", home / ".trae-cn" / "skills"))

        # Agents：~/.agents/ 存在 或 `which agents` 可用
        if (home / ".agents").exists() or shutil.which("agents") is not None:
            targets.append(("agents", home / ".agents" / "skills"))

        # AuWork（Windows 专属）：~/.auwork 下所有纯数字用户目录
        targets.extend(self._auwork_targets())

        return self._dedupe_targets(targets)

    def detect_all_install_targets(self) -> list[tuple[str, Path]]:
        """返回全部支持运行时的全局安装目录。

        `--runtime all` 的语义是强制覆盖四类 AI 工具的全局 Skills 目录，
        不依赖当前机器是否已检测到对应命令或配置目录。
        """
        home = Path.home()
        return self._dedupe_targets(
            [
                ("claude",     home / ".claude" / "skills"),
                ("openclaw",   home / ".openclaw" / "skills"),
                ("codex",      home / ".codex" / "skills"),
                ("opencode",   self._opencode_skills_dir()),
                ("workbuddy",  home / ".workbuddy" / "skills"),
                ("trae-cn",    home / ".trae-cn" / "skills"),
                ("agents",     home / ".agents" / "skills"),
            ]
            # AuWork（Windows 专属）：非 Windows 自动为空，不影响 mac/linux
            + self._auwork_targets()
        )

    def _auwork_targets(self) -> list[tuple[str, Path]]:
        """返回 AuWork 安装目标列表：~/.auwork 下所有纯数字用户目录的 skills/。

        AuWork 是 Windows 专属的特殊运行时，一个运行时展开为 N 个目标目录
        （每个登录过的 AuWork 用户对应一个纯数字命名的目录）。
        非 Windows、~/.auwork 不存在、或无任何纯数字子目录时均返回空列表
        （对应"跳过并提示"语义，由调用方决定是否提示）。
        """
        # 仅 Windows 生效：AuWork 是 Windows 客户端专属路径
        if sys.platform != "win32":
            return []
        auwork_root = Path.home() / ".auwork"
        if not auwork_root.exists():
            return []
        # 只纳入"纯数字"命名的用户目录，按名称排序保证输出稳定
        return [
            ("auwork", sub / "skills")
            for sub in sorted(p for p in auwork_root.iterdir() if p.is_dir() and p.name.isdigit())
        ]

    def _opencode_config_dir(self) -> Path:
        """返回 OpenCode 的配置根目录（所有平台统一为 ~/.config/opencode/）。"""
        return Path.home() / ".config" / "opencode"

    def _opencode_skills_dir(self) -> Path:
        """返回 OpenCode 的 Skills 安装目录（跨平台）。"""
        return self._opencode_config_dir() / "skills"

    def _dedupe_targets(self, targets: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, Path]] = []
        for runtime, path in targets:
            key = (runtime, str(path))
            if key in seen:
                continue
            seen.add(key)
            result.append((runtime, path))
        return result

    def _infer_runtime(self, skill_dir: Path) -> str:
        """根据 Skill 目录路径推断运行时类型。

        优先匹配最具体的特征路径段，无法识别时默认返回 claude。
        """
        parts = {part.lower() for part in skill_dir.parts}
        if ".openclaw" in parts:
            return "openclaw"
        if ".codex" in parts:
            return "codex"
        if "opencode" in parts:
            return "opencode"
        if ".workbuddy" in parts:
            return "workbuddy"
        if ".trae-cn" in parts:
            return "trae-cn"
        if ".agents" in parts:
            return "agents"
        if ".auwork" in parts:
            return "auwork"
        return "claude"
