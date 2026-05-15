"""Skill 链接管理器。

负责在各 AI 工具的 skills 目录下创建指向中央存储的链接，
实现"中央存储一份，多工具共享引用"的架构。

链接策略：
  macOS / Linux : os.symlink（符号链接）
  Windows       : os.symlink(target_is_directory=True)（Directory Junction，无需管理员权限）
  降级兜底       : shutil.copytree（极少数受限环境无法创建 Junction 时）
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LinkResult:
    """单次链接操作的结果。"""

    skill_name: str     # Skill 名称
    link_path: Path     # 工具 skills 目录下的链接路径
    target_path: Path   # 链接指向的中央存储路径
    method: str         # 实际使用的方式：symlink / junction / copy_fallback
    replaced: bool      # 是否替换了已有内容（旧链接、旧副本等）


class SkillsLinker:
    """Skill 链接器，在 AI 工具的 skills 目录下创建指向中央存储的链接。"""

    def link(
        self,
        skill_name: str,
        central_skill_dir: Path,
        tool_skills_dir: Path,
        *,
        force: bool = False,
    ) -> LinkResult:
        """在 tool_skills_dir 下创建指向 central_skill_dir 的链接。

        Args:
            skill_name: Skill 名称（如 "ops-dataset-query"）
            central_skill_dir: 中央存储中该 Skill 的目录
            tool_skills_dir: AI 工具的 skills 目录（如 ~/.claude/skills）
            force: 是否覆盖已有内容

        Returns:
            LinkResult，记录链接路径、目标、方式和是否替换
        """
        link_path = tool_skills_dir / skill_name
        replaced = False

        if link_path.exists() or link_path.is_symlink():
            if not force:
                raise ValueError(f"目标已存在（使用 --force 覆盖）: {link_path}")
            # 安全删除已有内容（区分 Junction / symlink / 普通目录）
            self._safe_remove(link_path)
            replaced = True

        tool_skills_dir.mkdir(parents=True, exist_ok=True)
        method = self._create_link(central_skill_dir, link_path)

        return LinkResult(
            skill_name=skill_name,
            link_path=link_path,
            target_path=central_skill_dir,
            method=method,
            replaced=replaced,
        )

    def unlink(self, link_path: Path) -> bool:
        """移除链接（不影响中央存储内容）。

        Args:
            link_path: 工具 skills 目录下的链接路径

        Returns:
            True 表示成功移除，False 表示路径本不存在
        """
        if not link_path.exists() and not link_path.is_symlink():
            return False
        self._safe_remove(link_path)
        return True

    def is_link_valid(self, link_path: Path, expected_target: Path) -> bool:
        """检查链接是否存在且指向预期的中央目录。

        Args:
            link_path: 工具 skills 目录下的链接路径
            expected_target: 预期的中央存储路径

        Returns:
            True 表示链接健康，False 表示缺失或指向错误
        """
        if not link_path.exists() and not link_path.is_symlink():
            return False
        # symlink：直接比较 resolve 结果
        if link_path.is_symlink():
            try:
                return link_path.resolve() == expected_target.resolve()
            except OSError:
                return False
        # Junction（Windows Python <3.12 的 is_symlink() 对 Junction 返回 False）
        # 通过检查 VERSION.json 是否仍可访问来判断健康状态
        return (link_path / "data" / "VERSION.json").exists()

    # ------------------------------------------------------------------ 内部方法

    def _create_link(self, target: Path, link: Path) -> str:
        """创建链接并返回实际使用的方式。"""
        if sys.platform == "win32":
            return self._create_windows_link(target, link)
        # macOS / Linux：标准符号链接
        os.symlink(target, link)
        return "symlink"

    def _create_windows_link(self, target: Path, link: Path) -> str:
        """Windows 下优先创建 Directory Junction，失败时降级复制。

        os.symlink(target_is_directory=True) 在普通用户权限下创建的是
        Directory Junction（等价于 mklink /J），无需管理员或开发者模式。
        """
        try:
            os.symlink(target, link, target_is_directory=True)
            return "junction"
        except OSError:
            # 极少数受限环境无法创建 Junction，降级为完整复制
            shutil.copytree(
                target,
                link,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            return "copy_fallback"

    def _safe_remove(self, path: Path) -> None:
        """安全删除链接或目录，避免误删 Junction 指向的中央存储内容。

        策略：
          - Unix symlink  : path.unlink()（仅删链接本身）
          - Windows Junction / 空目录 : os.rmdir()（仅删链接本身，不递归目标）
          - 普通目录       : shutil.rmtree()（os.rmdir 抛错时降级）
        """
        if sys.platform != "win32" and path.is_symlink():
            path.unlink()
            return

        if sys.platform == "win32":
            # Windows：先尝试 rmdir（成功则为 Junction 或空目录，不会删目标内容）
            try:
                os.rmdir(str(path))
                return
            except OSError:
                pass
            # rmdir 失败说明是有内容的普通目录，用 rmtree 清理
            shutil.rmtree(path)
        else:
            # Unix 非 symlink（普通目录）
            shutil.rmtree(path)
