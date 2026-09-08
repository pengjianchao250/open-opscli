"""独立站点仓库的 Git 初始化、校验与普通推送。"""

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
_SECRET_LINE_RE = re.compile(
    r"(?im)^(password|token|authorization)\s*[=:]\s*.+$"
)


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    def __init__(self, *, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def run(
        self,
        cwd: Path,
        args: list[str],
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> GitCommandResult:
        env = os.environ.copy()
        env.update(
            {
                "LC_ALL": "C",
                "LANG": "C",
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
            }
        )
        try:
            completed = subprocess.run(
                ["git", *args],
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
        branch: str = GIT_DEFAULT_BRANCH,
    ) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        self._ensure_git(root)
        git_created = not (root / ".git").exists()
        if git_created:
            self.runner.run(root, ["init"])
        else:
            self._assert_on_branch(root)
        remote_sha = self.probe_remote_branch(root, repo_url=repo_url, branch=branch)
        previous_origin = self._get_remote(root, "origin")
        self._set_remote(root, "origin", repo_url)
        if remote_sha is None:
            self._clear_remote_tracking(root, branch=branch)
        else:
            remote_sha = self._fetch_remote_branch(root, branch=branch)
        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"], check=False)
        if head.returncode != 0:
            self.runner.run(root, ["symbolic-ref", "HEAD", f"refs/heads/{branch}"])
            if remote_sha is not None:
                self.runner.run(root, ["reset", "--mixed", f"origin/{branch}"])
                self._checkout_missing_remote_files(root, branch=branch)
        else:
            self.runner.run(root, ["branch", "-M", branch])
            if remote_sha is not None:
                ancestor = self.runner.run(
                    root,
                    ["merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
                    check=False,
                )
                if ancestor.returncode != 0:
                    self.runner.run(
                        root,
                        [
                            "merge",
                            "--allow-unrelated-histories",
                            "-s",
                            "ours",
                            "--no-commit",
                            f"origin/{branch}",
                        ],
                    )

        if remote_sha is not None:
            self.runner.run(
                root,
                ["branch", f"--set-upstream-to=origin/{branch}", branch],
            )

        reachable_sha = self.probe_remote_branch(root, repo_url=repo_url, branch=branch)
        if reachable_sha != remote_sha:
            remote_sha = reachable_sha
        return {
            "git_created": git_created,
            "previous_origin": previous_origin if previous_origin != repo_url else None,
            "remote_branch": branch,
            "remote_branch_sha": remote_sha,
            "remote_branch_exists": remote_sha is not None,
        }

    def push_all(
        self,
        root: Path,
        *,
        repo_url: str,
        message: str,
        branch: str = GIT_DEFAULT_BRANCH,
    ) -> dict:
        self._ensure_git(root)
        if not (root / ".git").exists():
            raise AppGitError(
                "GIT-NOT-INITIALIZED",
                "当前目录尚未初始化 Git。",
                fix_hint="请先执行 opscli app init。",
            )
        self._assert_binding_ignored(root)
        self._assert_origin(root, repo_url)
        remote_sha = self.probe_remote_branch(root, repo_url=repo_url, branch=branch)
        if remote_sha is None:
            self._clear_remote_tracking(root, branch=branch)
        else:
            remote_sha = self._fetch_remote_branch(root, branch=branch)

        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"], check=False)
        has_head = head.returncode == 0 and _is_sha(head.stdout)
        dirty = bool(self.runner.run(root, ["status", "--porcelain"]).stdout)
        merge_head = self.runner.run(
            root,
            ["rev-parse", "--verify", "MERGE_HEAD"],
            check=False,
        )
        merge_pending = _is_sha(merge_head.stdout)
        committed = False
        if dirty:
            self.runner.run(root, ["add", "-A"])
            self._assert_binding_ignored(root)
        # 首次推送可能尚无 HEAD；有源码时先创建初始提交，避免把正常新项目误判为无提交。
        if dirty or merge_pending:
            self.runner.run(root, ["commit", "-m", message])
            committed = True
        elif not has_head:
            raise AppGitError("GIT-NO-COMMIT", "当前项目没有可推送的 Git commit。")

        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"])
        if remote_sha is not None:
            ancestor = self.runner.run(
                root,
                ["merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
                check=False,
            )
            if ancestor.returncode != 0:
                raise AppGitError(
                    "GIT-003",
                    f"远端 {branch} 包含本地尚未合并的提交，已拒绝非 fast-forward 推送。",
                    fix_hint=f"先合并 origin/{branch} 后重试；禁止使用 force push。",
                )
        if remote_sha is not None and head.stdout == remote_sha:
            return {
                "commit_sha": head.stdout,
                "remote_commit_sha": remote_sha,
                "committed": committed,
                "pushed": False,
            }
        push = self.runner.run(
            root,
            ["push", "-u", "origin", f"HEAD:{branch}"],
            check=False,
        )
        if push.returncode != 0:
            self._raise_git_transport_error(
                push,
                non_fast_forward=True,
                branch=branch,
            )
        remote_sha = self.probe_remote_branch(root, repo_url=repo_url, branch=branch)
        if remote_sha is None:
            raise AppGitError(
                "GIT-REPO-NOT-READY",
                f"Git push 成功后仍无法读取远端 {branch}。",
                fix_hint="检查目标仓库的默认分支和 Git 服务状态。",
            )
        return {
            "commit_sha": head.stdout,
            "remote_commit_sha": remote_sha,
            "committed": committed,
            "pushed": True,
        }

    def probe_remote_branch(
        self,
        root: Path,
        *,
        repo_url: str,
        branch: str = GIT_DEFAULT_BRANCH,
    ) -> str | None:
        result = self.runner.run(
            root,
            ["ls-remote", repo_url, f"refs/heads/{branch}"],
            check=False,
        )
        if result.returncode != 0:
            self._raise_git_transport_error(result)
        if not result.stdout:
            return None
        sha = result.stdout.split(maxsplit=1)[0]
        if not _is_sha(sha):
            raise AppGitError(
                "GIT-REPO-NOT-READY",
                f"AppHub 已登记应用，但仓库 {branch} 暂不可访问。",
                fix_hint=f"稍后重新执行 opscli app init；仓库和 {branch} 由 AppHub 创建。",
            )
        return sha

    def _get_remote(self, root: Path, name: str) -> str | None:
        result = self.runner.run(root, ["remote", "get-url", name], check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _clear_remote_tracking(self, root: Path, *, branch: str) -> None:
        self.runner.run(
            root,
            ["update-ref", "-d", f"refs/remotes/origin/{branch}"],
        )
        self.runner.run(root, ["branch", "--unset-upstream"], check=False)

    def _assert_on_branch(self, root: Path) -> None:
        result = self.runner.run(
            root,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            raise AppGitError(
                "GIT-DETACHED-HEAD",
                "当前项目处于 detached HEAD，无法绑定应用仓库。",
                fix_hint="请先切换到本地分支后重新执行 opscli app init。",
            )

    def _fetch_remote_branch(self, root: Path, *, branch: str) -> str:
        result = self.runner.run(
            root,
            [
                "fetch",
                "origin",
                f"{branch}:refs/remotes/origin/{branch}",
            ],
            check=False,
        )
        if result.returncode != 0:
            self._raise_git_transport_error(result)
        remote = self.runner.run(
            root,
            ["rev-parse", "--verify", f"origin/{branch}"],
            check=False,
        )
        if remote.returncode != 0 or not _is_sha(remote.stdout):
            raise AppGitError(
                "GIT-REPO-NOT-READY",
                f"远端仓库尚未准备好 {branch} 分支。",
                fix_hint=f"稍后重新执行；仓库和 {branch} 应由 AppHub create 创建。",
            )
        return remote.stdout

    def _checkout_missing_remote_files(self, root: Path, *, branch: str) -> None:
        tracked = self.runner.run(
            root,
            ["ls-tree", "-r", "--name-only", f"origin/{branch}"],
        )
        for relative_path in tracked.stdout.splitlines():
            if relative_path and not (root / relative_path).exists():
                self.runner.run(
                    root,
                    ["checkout", f"origin/{branch}", "--", relative_path],
                )

    def _ensure_git(self, root: Path) -> None:
        version_result = self.runner.run(root, ["--version"])
        version = _parse_git_version(version_result.stdout)
        if version < GIT_MIN_VERSION:
            raise GitUnavailableError(
                "GIT-001",
                f"Git 版本过低：{'.'.join(map(str, version))}，最低要求 2.30。",
            )

    def _assert_origin(self, root: Path, repo_url: str) -> None:
        origin = self.runner.run(root, ["remote", "get-url", "origin"], check=False)
        if origin.returncode != 0 or not _repo_urls_match(origin.stdout, repo_url):
            raise AppGitError(
                "GIT-ORIGIN-MISMATCH",
                "Git origin 与当前应用的独立仓库不一致。",
                fix_hint="请重新执行 opscli app init。",
            )

    def _assert_binding_ignored(self, root: Path) -> None:
        binding_path = root / ".opscli" / "app.json"
        if not binding_path.exists():
            return
        tracked = self.runner.run(
            root,
            ["ls-files", "--error-unmatch", "--", ".opscli/app.json"],
            check=False,
        )
        ignored = self.runner.run(
            root,
            ["check-ignore", "-q", "--", ".opscli/app.json"],
            check=False,
        )
        if tracked.returncode == 0 or ignored.returncode != 0:
            raise AppGitError(
                "APP-BINDING-TRACKED",
                ".opscli/app.json 是本地绑定文件，禁止进入 Git 提交。",
                fix_hint="在项目 .gitignore 中加入 .opscli/；如已跟踪，请先从 Git 索引移除。",
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

    def _raise_git_transport_error(
        self,
        result: GitCommandResult,
        *,
        non_fast_forward: bool = False,
        branch: str = GIT_DEFAULT_BRANCH,
    ) -> None:
        detail = result.stderr or result.stdout or f"exit={result.returncode}"
        lowered = detail.lower()
        if non_fast_forward and any(
            marker in lowered for marker in ("non-fast-forward", "fetch first", "rejected")
        ):
            raise AppGitError(
                "GIT-003",
                f"远端 {branch} 已领先，已拒绝非 fast-forward 推送。",
                fix_hint=f"先合并 origin/{branch} 后重试；禁止使用 force push。",
            )
        if any(
            marker in lowered
            for marker in ("authentication", "credential", "unauthorized", "403", "401")
        ):
            raise AppGitError(
                "GIT-002",
                "Git 凭据缺失、失效或无仓库写权限。",
                fix_hint="重新执行 opscli app init 以刷新凭据。",
            )
        raise AppGitError("GIT-010", f"Git 远端操作失败：{detail}")


def _parse_git_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        raise GitUnavailableError("GIT-001", f"无法解析 Git 版本：{text}")
    return tuple(int(part or 0) for part in match.groups())


def _is_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value))


def _redact(text: str) -> str:
    redacted = _CREDENTIAL_URL_RE.sub(r"\1***@", text)
    return _SECRET_LINE_RE.sub(lambda match: f"{match.group(1)}=***", redacted)


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
