"""统一 AppHub 模板的安全克隆服务。"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.git_environment import GitEnvironmentService

DEFAULT_TEMPLATE_REPO = "http://10.1.13.143:3000/aukeys-admin/template"
DEFAULT_TEMPLATE_BRANCH = "master"


class TemplateService:
    """使用 opscli 运行时检测到的 Git 克隆并脱离统一模板。"""

    def clone(
        self,
        project_dir: str | Path,
        *,
        repo_url: str = DEFAULT_TEMPLATE_REPO,
        branch: str = DEFAULT_TEMPLATE_BRANCH,
    ) -> dict:
        """克隆模板到空目录，并删除模板根目录的 Git 元数据。"""
        target = self._resolve_target(project_dir)
        existed_before = target.exists()
        self._validate_empty_target(target)

        git_environment = GitEnvironmentService().ensure(install=True)
        if not git_environment.get("ready"):
            raise AppProjectError(
                "APP-TEMPLATE-GIT",
                f"Git 环境未就绪 [{git_environment.get('status')}]：{git_environment.get('message')}",
                fix_hint="先执行 opscli app ensure-git --check --json，按返回状态准备 Git。",
                detail={"git_environment": git_environment},
            )

        git_path = str(git_environment["git_path"])
        command = [
            git_path,
            "clone",
            "--branch",
            branch,
            "--single-branch",
            repo_url,
            str(target),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
            )
        except OSError as exc:
            self._cleanup_failed_target(target, existed_before)
            raise AppProjectError(
                "APP-TEMPLATE-CLONE",
                f"模板克隆命令无法启动：{exc}",
                detail={"command": command, "git_path": git_path},
            ) from exc

        if result.returncode != 0:
            self._cleanup_failed_target(target, existed_before)
            detail = result.stderr.strip() or result.stdout.strip() or f"exit={result.returncode}"
            raise AppProjectError(
                "APP-TEMPLATE-CLONE",
                f"模板克隆失败：{detail}",
                fix_hint="确认模板仓库地址、分支和网络访问权限后重试。",
                detail={
                    "command": command,
                    "return_code": result.returncode,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                },
            )

        try:
            self._detach_git_metadata(target)
        except AppProjectError:
            self._cleanup_failed_target(target, existed_before)
            raise
        return {
            "path": str(target),
            "repo_url": repo_url,
            "branch": branch,
            "git_path": git_path,
            "message": "模板已准备完成，模板 Git 元数据已删除。",
        }

    def _resolve_target(self, value: str | Path) -> Path:
        target = Path(value).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target
        target = target.resolve(strict=False)
        if target.parent == target:
            raise AppProjectError("APP-TEMPLATE-TARGET", "项目目录不能是文件系统根目录。")
        return target

    def _validate_empty_target(self, target: Path) -> None:
        if target.exists():
            if target.is_symlink():
                raise AppProjectError("APP-TEMPLATE-TARGET", f"项目目录不能是符号链接：{target}")
            if not target.is_dir():
                raise AppProjectError("APP-TEMPLATE-TARGET", f"项目路径不是目录：{target}")
            if any(target.iterdir()):
                raise AppProjectError("APP-TEMPLATE-TARGET", f"项目目录必须为空：{target}")
            return
        if not target.parent.is_dir():
            raise AppProjectError("APP-TEMPLATE-TARGET", f"项目目录的父目录不存在：{target.parent}")

    def _cleanup_failed_target(self, target: Path, existed_before: bool) -> None:
        if not target.exists():
            return
        try:
            if existed_before:
                for child in target.iterdir():
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                    else:
                        shutil.rmtree(child, onerror=self._remove_readonly)
            else:
                shutil.rmtree(target, onerror=self._remove_readonly)
        except OSError:
            pass

    def _detach_git_metadata(self, target: Path) -> None:
        git_metadata = target / ".git"
        try:
            if git_metadata.is_symlink() or git_metadata.is_file():
                git_metadata.unlink()
            elif git_metadata.is_dir():
                shutil.rmtree(git_metadata, onerror=self._remove_readonly)
            else:
                raise AppProjectError("APP-TEMPLATE-GIT", f"模板 clone 完成后未找到 Git 元数据：{git_metadata}")
        except OSError as exc:
            raise AppProjectError("APP-TEMPLATE-GIT", f"删除模板 Git 元数据失败：{git_metadata}: {exc}") from exc
        if git_metadata.exists() or git_metadata.is_symlink():
            raise AppProjectError("APP-TEMPLATE-GIT", f"模板 Git 元数据删除后仍然存在：{git_metadata}")

    @staticmethod
    def _remove_readonly(operation: Callable[[str], object], path: str, _error_info: object) -> None:
        os.chmod(path, stat.S_IWRITE)
        operation(path)
