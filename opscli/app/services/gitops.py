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
        env.update({"LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0"})
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
        template_repo_url: str,
        template_branch: str,
        apply_template: bool,
    ) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        self._ensure_git(root)
        git_created = not (root / ".git").exists()
        if git_created:
            self.runner.run(root, ["init"])

        previous_origin = self._set_remote(root, "origin", repo_url)
        remote_sha = self._fetch_remote_main(root)
        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"], check=False)
        if head.returncode != 0:
            self.runner.run(root, ["symbolic-ref", "HEAD", f"refs/heads/{GIT_DEFAULT_BRANCH}"])
            self.runner.run(root, ["reset", "--mixed", f"origin/{GIT_DEFAULT_BRANCH}"])
            if apply_template:
                self.runner.run(root, ["checkout", f"origin/{GIT_DEFAULT_BRANCH}", "--", "."])
            else:
                self._checkout_missing_remote_files(root)
        else:
            self.runner.run(root, ["branch", "-M", GIT_DEFAULT_BRANCH])
            ancestor = self.runner.run(
                root,
                ["merge-base", "--is-ancestor", f"origin/{GIT_DEFAULT_BRANCH}", "HEAD"],
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
                        "--no-edit",
                        f"origin/{GIT_DEFAULT_BRANCH}",
                    ],
                )

        template_applied = False
        if apply_template:
            self._set_remote(root, "template", template_repo_url)
            self.runner.run(
                root,
                [
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.askPass=",
                    "fetch",
                    "template",
                    template_branch,
                ],
            )
            self.runner.run(root, ["checkout", "FETCH_HEAD", "--", "."])
            self.runner.run(root, ["remote", "remove", "template"])
            template_applied = True

        reachable_sha = self.probe_remote_main(root, repo_url=repo_url)
        if reachable_sha != remote_sha:
            remote_sha = reachable_sha
        return {
            "git_created": git_created,
            "template_applied": template_applied,
            "template_branch": template_branch if template_applied else None,
            "previous_origin": previous_origin if previous_origin != repo_url else None,
            "remote_main_sha": remote_sha,
        }

    def push_all(self, root: Path, *, repo_url: str, message: str) -> dict:
        self._ensure_git(root)
        if not (root / ".git").exists():
            raise AppGitError(
                "GIT-NOT-INITIALIZED",
                "当前目录尚未初始化 Git。",
                fix_hint="请先执行 opscli app init。",
            )
        self._assert_origin(root, repo_url)
        self._fetch_remote_main(root)

        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"], check=False)
        if head.returncode != 0 or not _is_sha(head.stdout):
            raise AppGitError("GIT-NO-COMMIT", "当前项目没有可推送的 Git commit。")
        ancestor = self.runner.run(
            root,
            ["merge-base", "--is-ancestor", f"origin/{GIT_DEFAULT_BRANCH}", "HEAD"],
            check=False,
        )
        if ancestor.returncode != 0:
            raise AppGitError(
                "GIT-003",
                "远端 main 包含本地尚未合并的提交，已拒绝非 fast-forward 推送。",
                fix_hint="先合并 origin/main 后重试；禁止使用 force push。",
            )

        dirty = bool(self.runner.run(root, ["status", "--porcelain"]).stdout)
        committed = False
        if dirty:
            self.runner.run(root, ["add", "-A"])
            self.runner.run(root, ["commit", "-m", message])
            committed = True

        head = self.runner.run(root, ["rev-parse", "--verify", "HEAD"])
        push = self.runner.run(
            root,
            ["push", "-u", "origin", f"HEAD:{GIT_DEFAULT_BRANCH}"],
            check=False,
        )
        if push.returncode != 0:
            self._raise_git_transport_error(push, non_fast_forward=True)
        remote_sha = self.probe_remote_main(root, repo_url=repo_url)
        return {
            "commit_sha": head.stdout,
            "remote_commit_sha": remote_sha,
            "committed": committed,
            "pushed": True,
        }

    def probe_remote_main(self, root: Path, *, repo_url: str) -> str:
        result = self.runner.run(
            root,
            ["ls-remote", repo_url, f"refs/heads/{GIT_DEFAULT_BRANCH}"],
            check=False,
        )
        if result.returncode != 0:
            self._raise_git_transport_error(result)
        sha = result.stdout.split(maxsplit=1)[0] if result.stdout else ""
        if not _is_sha(sha):
            raise AppGitError(
                "GIT-REPO-NOT-READY",
                "AppHub 已登记应用，但仓库 main 暂不可访问。",
                fix_hint="稍后重新执行 app init；不要在 CLI 中自行创建仓库。",
            )
        return sha

    def _fetch_remote_main(self, root: Path) -> str:
        result = self.runner.run(
            root,
            [
                "fetch",
                "origin",
                f"{GIT_DEFAULT_BRANCH}:refs/remotes/origin/{GIT_DEFAULT_BRANCH}",
            ],
            check=False,
        )
        if result.returncode != 0:
            self._raise_git_transport_error(result)
        remote = self.runner.run(
            root,
            ["rev-parse", "--verify", f"origin/{GIT_DEFAULT_BRANCH}"],
            check=False,
        )
        if remote.returncode != 0 or not _is_sha(remote.stdout):
            raise AppGitError(
                "GIT-REPO-NOT-READY",
                "远端仓库尚未准备好 main 分支。",
                fix_hint="稍后重新执行；仓库和 main 应由 AppHub create 创建。",
            )
        return remote.stdout

    def _checkout_missing_remote_files(self, root: Path) -> None:
        tracked = self.runner.run(
            root,
            ["ls-tree", "-r", "--name-only", f"origin/{GIT_DEFAULT_BRANCH}"],
        )
        for relative_path in tracked.stdout.splitlines():
            if relative_path and not (root / relative_path).exists():
                self.runner.run(
                    root,
                    ["checkout", f"origin/{GIT_DEFAULT_BRANCH}", "--", relative_path],
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
                "Git origin 与当前站点的独立仓库不一致。",
                fix_hint="请重新执行 opscli app init。",
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
    ) -> None:
        detail = result.stderr or result.stdout or f"exit={result.returncode}"
        lowered = detail.lower()
        if non_fast_forward and any(
            marker in lowered for marker in ("non-fast-forward", "fetch first", "rejected")
        ):
            raise AppGitError(
                "GIT-003",
                "远端 main 已领先，已拒绝非 fast-forward 推送。",
                fix_hint="先合并 origin/main 后重试；禁止使用 force push。",
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
