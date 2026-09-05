"""独立仓库 Git 初始化与普通推送测试。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppGitError
from opscli.app.services.gitops import GitCommandResult, GitService, _parse_git_version


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], GitCommandResult] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def run(self, cwd, args, *, check=True, input_text=None):
        self.calls.append(args)
        result = self.responses.get(tuple(args), GitCommandResult(0, "", ""))
        if check and result.returncode != 0:
            raise AssertionError(f"unexpected checked failure: {args}")
        return result


def test_parse_git_version() -> None:
    assert _parse_git_version("git version 2.45.2.windows.1") == (2, 45, 2)


def test_empty_project_bases_main_on_origin_without_template(tmp_path: Path) -> None:
    remote_sha = "a" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(2, "", "missing"),
            ("rev-parse", "--verify", "origin/main"): GitCommandResult(0, remote_sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(1, "", "missing"),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/main",
            ): GitCommandResult(0, f"{remote_sha}\trefs/heads/main", ""),
        }
    )

    result = GitService(runner=runner).initialize(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
    )

    assert result["git_created"] is True
    assert ["fetch", "origin", "main:refs/remotes/origin/main"] in runner.calls
    assert ["reset", "--mixed", "origin/main"] in runner.calls
    assert ["remote", "add", "origin", "https://gitea.example/apps/demo.git"] in runner.calls
    assert not any("template" in call for call in runner.calls)


def test_init_prepares_unrelated_history_without_creating_commit(tmp_path: Path) -> None:
    remote_sha = "a" * 40
    local_sha = "b" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/apps/demo.git", ""
            ),
            ("rev-parse", "--verify", "origin/main"): GitCommandResult(0, remote_sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, local_sha, ""),
            ("merge-base", "--is-ancestor", "origin/main", "HEAD"): GitCommandResult(1, "", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/main",
            ): GitCommandResult(0, f"{remote_sha}\trefs/heads/main", ""),
        }
    )

    GitService(runner=runner).initialize(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
    )

    assert [
        "merge",
        "--allow-unrelated-histories",
        "-s",
        "ours",
        "--no-commit",
        "origin/main",
    ] in runner.calls
    assert not any(call and call[0] == "commit" for call in runner.calls)


def test_push_fetches_checks_fast_forward_and_never_forces(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sha = "b" * 40
    remote_before = "a" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/apps/demo.git", ""
            ),
            ("rev-parse", "--verify", "origin/main"): GitCommandResult(0, remote_before, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, sha, ""),
            ("merge-base", "--is-ancestor", "origin/main", "HEAD"): GitCommandResult(0, "", ""),
            ("status", "--porcelain"): GitCommandResult(0, " M index.html", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/main",
            ): GitCommandResult(0, f"{sha}\trefs/heads/main", ""),
        }
    )

    result = GitService(runner=runner).push_all(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
        message="优化首页",
    )

    assert ["add", "-A"] in runner.calls
    assert ["commit", "-m", "优化首页"] in runner.calls
    assert ["push", "-u", "origin", "HEAD:main"] in runner.calls
    assert all("--force" not in call for call in runner.calls)
    assert result["remote_commit_sha"] == sha
    assert result["pushed"] is True


def test_push_is_noop_when_local_and_remote_are_equal(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sha = "a" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/apps/demo.git", ""
            ),
            ("rev-parse", "--verify", "origin/main"): GitCommandResult(0, sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, sha, ""),
            ("merge-base", "--is-ancestor", "origin/main", "HEAD"): GitCommandResult(0, "", ""),
            ("status", "--porcelain"): GitCommandResult(0, "", ""),
        }
    )

    result = GitService(runner=runner).push_all(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
        message="无变化",
    )

    assert result["pushed"] is False
    assert result["committed"] is False
    assert not any(call and call[0] == "push" for call in runner.calls)


def test_push_rejects_non_fast_forward(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/apps/demo.git", ""
            ),
            ("rev-parse", "--verify", "origin/main"): GitCommandResult(0, "a" * 40, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, "b" * 40, ""),
            ("merge-base", "--is-ancestor", "origin/main", "HEAD"): GitCommandResult(1, "", ""),
        }
    )

    with pytest.raises(AppGitError) as caught:
        GitService(runner=runner).push_all(
            tmp_path,
            repo_url="https://gitea.example/apps/demo.git",
            message="不能强推",
        )

    assert caught.value.code == "GIT-003"
    assert not any(call and call[0] == "push" for call in runner.calls)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_real_git_init_preserves_existing_source_and_pushes(tmp_path: Path) -> None:
    target_work = tmp_path / "target-work"
    target_work.mkdir()
    _git(target_work, "init")
    _configure_author(target_work)
    (target_work / "README.md").write_text("remote readme", encoding="utf-8")
    _git(target_work, "add", "-A")
    _git(target_work, "commit", "-m", "initialize main")
    _git(target_work, "branch", "-M", "main")
    target_bare = tmp_path / "target.git"
    subprocess.run(
        ["git", "clone", "--bare", str(target_work), str(target_bare)],
        check=True,
        capture_output=True,
    )

    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "index.html").write_text("local index", encoding="utf-8")
    service = GitService()

    initialized = service.initialize(app_root, repo_url=str(target_bare))

    assert initialized["git_created"] is True
    assert (app_root / "index.html").read_text(encoding="utf-8") == "local index"
    assert (app_root / "README.md").read_text(encoding="utf-8") == "remote readme"

    _configure_author(app_root)
    pushed = service.push_all(app_root, repo_url=str(target_bare), message="提交源码")

    assert pushed["committed"] is True
    assert pushed["pushed"] is True
    assert _git(target_bare, "rev-parse", "refs/heads/main") == pushed["commit_sha"]


def _configure_author(cwd: Path) -> None:
    _git(cwd, "config", "user.name", "Test User")
    _git(cwd, "config", "user.email", "test@example.com")


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return completed.stdout.strip()
