"""Git 初始化、模板获取与整体源码推送。"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from opscli.app.domain.constants import GIT_DEFAULT_BRANCH, GIT_MIN_VERSION
from opscli.app.domain.exceptions import AppGitError, GitUnavailableError

_CREDENTIAL_URL_RE = re.compile(r"(https?://)([^/@\s]+)@", re.IGNORECASE)


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    def __init__(self, *, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def run(self, cwd: Path, args: list[str], *, check: bool = True) -> GitCommandResult:
        env = os.environ.copy()
        env.update({"LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0"})
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout,
                shell=False,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitUnavailableError(
                "GIT-001",
                "未找到 Git。",
                fix_hint="安装 Git 2.30+ 后重新打开终端。",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AppGitError("GIT-010", f"Git 命令执行超时：git {args[0]}") from exc

        result = GitCommandResult(
            returncode=completed.returncode,
            stdout=_redact(completed.stdout.strip()),
            stderr=_redact(completed.stderr.strip()),
        )
        if check and result.returncode != 0:
            detail = result.stderr or result.stdout or f"exit={result.returncode}"
            raise AppGitError("GIT-010", f"Git 命令失败：{detail}")
        return result


class GitService:
    def __init__(self, runner: GitRunner | None = None) -> None:
        self.runner = runner or GitRunner()

    def initialize(
        self,
        root: Path,
        *,
        repo_url: str,
        template_repo_url: str,
        template_branch: str,
        apply_template: bool,
    ) -> dict:
        self._ensure_git(root)
        git_created = not (root / ".git").exists()
        if git_created:
            self.runner.run(root, ["init"])
            self.runner.run(root, ["branch", "-M", GIT_DEFAULT_BRANCH])

        template_applied = False
        if apply_template:
            self._set_remote(root, "template", template_repo_url)
            self.runner.run(root, ["fetch", "template", template_branch])
            self.runner.run(root, ["checkout", "-B", GIT_DEFAULT_BRANCH, "FETCH_HEAD"])
            self.runner.run(root, ["remote", "remove", "template"])
            template_applied = True

        previous_origin = self._set_remote(root, "origin", repo_url)
        return {
            "git_created": git_created,
            "template_applied": template_applied,
            "template_branch": template_branch if template_applied else None,
            "previous_origin": previous_origin if previous_origin != repo_url else None,
        }

    def push_all(self, root: Path, *, repo_url: str, message: str) -> dict:
        self._ensure_git(root)
        if not (root / ".git").exists():
            raise AppGitError(
                "GIT-NOT-INITIALIZED",
                "当前目录尚未初始化 Git。",
                fix_hint="请先执行 opscli app init。",
            )
        origin = self.runner.run(root, ["remote", "get-url", "origin"], check=False)
        if origin.returncode != 0 or not _repo_urls_match(origin.stdout, repo_url):
            raise AppGitError(
                "GIT-ORIGIN-MISMATCH",
                "Git origin 与站点绑定的目标仓库不一致。",
                fix_hint="请重新执行 opscli app init。",
            )

        dirty = bool(self.runner.run(root, ["status", "--porcelain"]).stdout)
        committed = False
        if dirty:
            self.runner.run(root, ["add", "-A"])
            self.runner.run(root, ["commit", "-m", message])
            committed = True

        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"], check=False)
        if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head.stdout):
            raise AppGitError("GIT-NO-COMMIT", "当前项目没有可推送的 Git commit。")

        self.runner.run(root, ["push", "-u", "origin", f"HEAD:{GIT_DEFAULT_BRANCH}"])
        return {"commit_sha": head.stdout, "committed": committed, "pushed": True}

    def _ensure_git(self, root: Path) -> None:
        version_result = self.runner.run(root, ["--version"])
        version = _parse_git_version(version_result.stdout)
        if version < GIT_MIN_VERSION:
            raise GitUnavailableError(
                "GIT-001",
                f"Git 版本过低：{'.'.join(map(str, version))}，最低要求 2.30。",
            )

    def _set_remote(self, root: Path, name: str, url: str) -> str | None:
        current = self.runner.run(root, ["remote", "get-url", name], check=False)
        if current.returncode == 0:
            if _repo_urls_match(current.stdout, url):
                return current.stdout
            self.runner.run(root, ["remote", "set-url", name, url])
            return current.stdout
        self.runner.run(root, ["remote", "add", name, url])
        return None


def _parse_git_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        raise GitUnavailableError("GIT-001", f"无法解析 Git 版本：{text}")
    return tuple(int(part or 0) for part in match.groups())


def _redact(text: str) -> str:
    return _CREDENTIAL_URL_RE.sub(r"\1***@", text)


def _normalize_repo_url(url: str) -> str:
    value = url.strip().rstrip("/")
    if value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.removesuffix(".git").rstrip("/")
        return urlunsplit((parsed.scheme.lower(), f"{host.lower()}{port}", path, "", ""))
    return value.removesuffix(".git")


def _repo_urls_match(left: str, right: str) -> bool:
    return _normalize_repo_url(left) == _normalize_repo_url(right)
