"""Git 子进程封装与 D9 普通推送编排。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from opscli.app.domain.constants import GIT_DEFAULT_BRANCH, GIT_MIN_VERSION
from opscli.app.domain.exceptions import (
    AppGitError,
    GitCredentialError,
    GitNonFastForwardError,
    GitUnavailableError,
)

_CREDENTIAL_URL_RE = re.compile(r"(https?://)([^/@\s]+)@", re.IGNORECASE)


@dataclass(frozen=True)
class GitCommandResult:
    """Git 命令的脱敏结果。"""

    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    """使用参数数组执行允许的 Git 命令。"""

    def __init__(self, *, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def run(
        self,
        cwd: Path,
        args: list[str],
        *,
        credential_file: Path | None = None,
        input_text: str | None = None,
        check: bool = True,
    ) -> GitCommandResult:
        """执行 Git，凭据内容只允许通过 stdin 传入。"""
        command = ["git"]
        if credential_file is not None:
            command.extend([
                "-c",
                "credential.helper=",
                "-c",
                f"credential.helper=store --file={credential_file}",
            ])
        command.extend(args)
        env = os.environ.copy()
        env.update({"LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0"})
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                input=input_text,
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
                "未找到 Git。AppHub D9 发布要求本机安装 Git 2.30 或更高版本。",
                fix_hint="安装 Git 2.30+ 后重新打开终端。",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AppGitError("GIT-010", f"Git 命令执行超时: git {args[0]}") from exc

        result = GitCommandResult(
            returncode=completed.returncode,
            stdout=_redact(completed.stdout.strip()),
            stderr=_redact(completed.stderr.strip()),
        )
        if check and result.returncode != 0:
            detail = result.stderr or result.stdout or f"exit={result.returncode}"
            raise AppGitError("GIT-010", f"Git 命令失败: {detail}")
        return result


class GitService:
    """发布链需要的 Git 只读检查与普通 commit/push。"""

    def __init__(self, runner: GitRunner | None = None) -> None:
        self.runner = runner or GitRunner()

    def preflight(self, root: Path, slug: str, expected_repo_url: str) -> str:
        """检查版本、仓库根、main 分支和 origin，返回 origin URL。"""
        version_result = self.runner.run(root, ["--version"])
        version = _parse_git_version(version_result.stdout)
        if version < GIT_MIN_VERSION:
            raise GitUnavailableError(
                "GIT-001",
                f"Git 版本过低: {'.'.join(map(str, version))}，最低要求 2.30。",
                fix_hint="升级 Git 到 2.30 或更高版本。",
            )

        repo_root = Path(self.runner.run(root, ["rev-parse", "--show-toplevel"]).stdout).resolve()
        if repo_root != root.resolve():
            raise AppGitError(
                "GIT-001",
                f"app.yaml 必须位于 Git 仓库根目录: {repo_root}",
            )
        branch = self.runner.run(root, ["branch", "--show-current"]).stdout
        if branch != GIT_DEFAULT_BRANCH:
            raise AppGitError(
                "GIT-001",
                f"当前分支为 {branch or '(detached)'}，AppHub 只接受 main 分支。",
                fix_hint="切换到 main 分支后重试。",
            )
        origin = self.runner.run(root, ["remote", "get-url", "origin"]).stdout
        if not _repo_urls_match(origin, expected_repo_url) or not _url_matches_slug(origin, slug):
            raise AppGitError(
                "GIT-001",
                "origin 与 AppHub 为该应用分配的 apps/{slug} 仓库不一致。",
                fix_hint=f"将 origin 修正为 AppHub git-config 返回的仓库地址。",
                detail={"slug": slug},
            )
        return origin

    def initialize(
        self,
        root: Path,
        repo_url: str,
        *,
        author_name: str = "AppHub User",
        author_email: str = "apphub-user@local.invalid",
    ) -> None:
        """在新项目中初始化 main 与 origin。"""
        self.runner.run(root, ["--version"])
        if not (root / ".git").exists():
            self.runner.run(root, ["init"])
        self.runner.run(root, ["branch", "-M", GIT_DEFAULT_BRANCH])
        remote = self.runner.run(root, ["remote", "get-url", "origin"], check=False)
        if remote.returncode == 0:
            self.runner.run(root, ["remote", "set-url", "origin", repo_url])
        else:
            self.runner.run(root, ["remote", "add", "origin", repo_url])
        if self.runner.run(root, ["config", "user.name"], check=False).returncode != 0:
            self.runner.run(root, ["config", "user.name", author_name])
        if self.runner.run(root, ["config", "user.email"], check=False).returncode != 0:
            self.runner.run(root, ["config", "user.email", author_email])

    def pull(self, root: Path, credential_file: Path) -> None:
        """执行普通 pull，不做 reset/rebase/force。"""
        result = self.runner.run(
            root,
            ["pull", "--no-rebase", "origin", GIT_DEFAULT_BRANCH],
            credential_file=credential_file,
            check=False,
        )
        if result.returncode != 0:
            raise AppGitError(
                "GIT-PULL-FAILED",
                "git pull 失败或存在需要人工处理的冲突。",
                fix_hint="按 git status 提示解决冲突后重新执行 pull。",
            )

    def initial_push(self, root: Path, credential_file: Path, message: str) -> str:
        """提交模板并首次普通推送。"""
        self.fetch(root, credential_file)
        remote = self.runner.run(root, ["rev-parse", "--verify", "origin/main"], check=False)
        if remote.returncode == 0:
            reset = self.runner.run(root, ["reset", "--mixed", "origin/main"], check=False)
            if reset.returncode != 0:
                raise AppGitError("GIT-010", "无法建立本地 main 与远端初始提交的关系。")
        if not self.is_dirty(root):
            return self.revision(root, "origin/main" if remote.returncode == 0 else "HEAD")
        commit_sha = self.commit_all(root, message)
        self.push(root, credential_file)
        return commit_sha

    def probe(self, root: Path, repo_url: str, credential_file: Path) -> None:
        """用受控 credential helper 探测仓库读取权限。"""
        result = self.runner.run(
            root,
            ["ls-remote", "--exit-code", repo_url, "refs/heads/main"],
            credential_file=credential_file,
            check=False,
        )
        if result.returncode != 0:
            raise GitCredentialError(
                "GIT-002",
                "Git 凭据不存在、已失效或无权访问应用仓库。",
                fix_hint="执行 opscli app git bind 重新绑定凭据。",
            )

    def fetch(self, root: Path, credential_file: Path) -> None:
        """获取远端 main，不合并或重置本地分支。"""
        self.runner.run(
            root,
            ["fetch", "origin", GIT_DEFAULT_BRANCH],
            credential_file=credential_file,
        )

    def is_dirty(self, root: Path) -> bool:
        """判断工作区和暂存区是否存在改动。"""
        return bool(self.runner.run(root, ["status", "--porcelain"]).stdout)

    def revision(self, root: Path, ref: str) -> str:
        """解析完整 40 位 commit SHA。"""
        sha = self.runner.run(root, ["rev-parse", ref]).stdout
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise AppGitError("GIT-010", f"无法解析 {ref} 的完整 commit SHA。")
        return sha

    def is_ancestor(self, root: Path, ancestor: str, descendant: str) -> bool:
        """用稳定退出码判断祖先关系。"""
        result = self.runner.run(
            root,
            ["merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise AppGitError("GIT-010", "无法判断本地与远端分支关系。")
        return result.returncode == 0

    def commit_all(self, root: Path, message: str) -> str:
        """暂存全部改动并创建普通 commit。"""
        self.runner.run(root, ["add", "-A"])
        self.runner.run(root, ["commit", "-m", message])
        return self.revision(root, "HEAD")

    def push(self, root: Path, credential_file: Path) -> None:
        """执行非强制 main push。"""
        result = self.runner.run(
            root,
            ["push", "origin", f"HEAD:{GIT_DEFAULT_BRANCH}"],
            credential_file=credential_file,
            check=False,
        )
        if result.returncode == 0:
            return
        self.fetch(root, credential_file)
        if not self.is_ancestor(root, "origin/main", "HEAD"):
            raise GitNonFastForwardError(
                "GIT-003",
                "push 时远端 main 已更新，普通 push 被拒绝。",
                fix_hint="请执行 git pull/rebase 并解决冲突后重试。",
            )
        raise AppGitError("GIT-010", "git push 失败，请检查仓库权限和网络后重试。")

    def select_publish_sha(
        self,
        root: Path,
        credential_file: Path,
        *,
        dirty: bool,
        message: str,
    ) -> tuple[str, bool]:
        """按 D9 分支关系选择并推送待发布 SHA，返回 (sha, pushed)。"""
        local_head = self.revision(root, "HEAD")
        remote_head = self.revision(root, "origin/main")
        if dirty:
            if not self.is_ancestor(root, "origin/main", "HEAD"):
                raise GitNonFastForwardError(
                    "GIT-003",
                    "本地 main 与 origin/main 已分叉，拒绝自动 rebase/reset。",
                    fix_hint="请人工处理分支冲突后重试。",
                )
            commit_sha = self.commit_all(root, message)
            self.push(root, credential_file)
            return commit_sha, True

        if local_head == remote_head:
            return remote_head, False
        if self.is_ancestor(root, "origin/main", "HEAD"):
            self.push(root, credential_file)
            return local_head, True
        if self.is_ancestor(root, "HEAD", "origin/main"):
            return remote_head, False
        raise GitNonFastForwardError(
            "GIT-003",
            "本地 main 与 origin/main 已分叉，拒绝自动 rebase/reset。",
            fix_hint="请人工执行 git pull/rebase 并解决冲突后重试。",
        )


def _parse_git_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        raise GitUnavailableError("GIT-001", f"无法解析 Git 版本: {text}")
    return tuple(int(part or 0) for part in match.groups())


def _redact(text: str) -> str:
    return _CREDENTIAL_URL_RE.sub(r"\1***@", text)


def _normalize_repo_url(url: str) -> str:
    value = url.strip().rstrip("/")
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.removesuffix(".git").rstrip("/")
        return urlunsplit((parsed.scheme.lower(), f"{host.lower()}{port}", path, "", ""))
    return value.removesuffix(".git")


def _repo_urls_match(left: str, right: str) -> bool:
    return _normalize_repo_url(left) == _normalize_repo_url(right)


def _url_matches_slug(url: str, slug: str) -> bool:
    normalized = _normalize_repo_url(url)
    return normalized.endswith(f"/apps/{slug}")


def git_is_available() -> bool:
    """供诊断命令快速判断 Git 是否在 PATH。"""
    return shutil.which("git") is not None
