'''克隆统一应用模板并立即移除模板仓库 Git 元数据。'''

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence


DEFAULT_TEMPLATE_REPO = 'http://10.1.13.143:3000/aukeys-admin/template'
DEFAULT_TEMPLATE_BRANCH = 'master'


class TemplateCloneError(RuntimeError):
    '''表示模板准备流程无法安全完成。'''


def _resolved_target(value: str | Path) -> Path:
    target = Path(value).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve(strict=False)
    if target.parent == target:
        raise TemplateCloneError('项目目录不能是文件系统根目录。')
    return target


def _validate_empty_target(target: Path) -> None:
    if target.exists():
        if target.is_symlink():
            raise TemplateCloneError(f'项目目录不能是符号链接：{target}')
        if not target.is_dir():
            raise TemplateCloneError(f'项目路径不是目录：{target}')
        if any(target.iterdir()):
            raise TemplateCloneError(f'项目目录必须为空：{target}')
        return
    if not target.parent.is_dir():
        raise TemplateCloneError(f'项目目录的父目录不存在：{target.parent}')


def _remove_readonly(
    operation: Callable[[str], object],
    path: str,
    _error_info: object,
) -> None:
    os.chmod(path, stat.S_IWRITE)
    operation(path)


def detach_git_metadata(project_dir: str | Path) -> Path:
    '''只删除项目根目录的 .git，并保留模板源码与 .gitignore。'''
    root = _resolved_target(project_dir)
    if not root.is_dir():
        raise TemplateCloneError(f'模板项目目录不存在：{root}')

    git_metadata = root / '.git'
    try:
        if git_metadata.is_symlink() or git_metadata.is_file():
            git_metadata.unlink()
        elif git_metadata.is_dir():
            shutil.rmtree(git_metadata, onerror=_remove_readonly)
        else:
            raise TemplateCloneError(f'模板 clone 完成后未找到 Git 元数据：{git_metadata}')
    except OSError as exc:
        raise TemplateCloneError(f'删除模板 Git 元数据失败：{git_metadata}: {exc}') from exc

    if git_metadata.exists() or git_metadata.is_symlink():
        raise TemplateCloneError(f'模板 Git 元数据删除后仍然存在：{git_metadata}')
    return root


def clone_template(
    project_dir: str | Path,
    *,
    repo_url: str = DEFAULT_TEMPLATE_REPO,
    branch: str = DEFAULT_TEMPLATE_BRANCH,
) -> Path:
    '''直接 clone 模板到目标目录，成功后立即移除根目录 .git。'''
    target = _resolved_target(project_dir)
    _validate_empty_target(target)

    result = subprocess.run(
        [
            'git',
            'clone',
            '--branch',
            branch,
            '--single-branch',
            repo_url,
            str(target),
        ],
        check=False,
        text=True,
        encoding='utf-8',
        errors='replace',
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f'exit={result.returncode}'
        raise TemplateCloneError(f'模板克隆失败：{detail}')

    return detach_git_metadata(target)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='克隆统一 AppHub 模板并立即移除模板仓库的 .git。'
    )
    parser.add_argument('project_directory', help='不存在或为空的目标项目目录')
    parser.add_argument('--repo-url', default=DEFAULT_TEMPLATE_REPO, help='模板仓库地址')
    parser.add_argument('--branch', default=DEFAULT_TEMPLATE_BRANCH, help='模板分支')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        target = clone_template(
            args.project_directory,
            repo_url=args.repo_url,
            branch=args.branch,
        )
    except (TemplateCloneError, OSError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1

    print(f'模板已准备完成：{target}')
    print('模板 Git 元数据已删除，可以继续执行 opscli app create/init。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
