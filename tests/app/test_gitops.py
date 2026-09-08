"""独立仓库 Git 初始化与普通推送测试。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppGitError
from opscli.app.services.gitops import GitCommandResult, GitService, _parse_git_version


def test_git_runner_disables_windows_credential_manager_prompt(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    from opscli.app.services.gitops import GitRunner

    GitRunner().run(tmp_path, ["credential", "fill"], check=False)

    assert captured["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["GCM_INTERACTIVE"] == "Never"


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


def test_empty_project_bases_master_on_origin_without_template(tmp_path: Path) -> None:
    remote_sha = "a" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(2, "", "missing"),
            ("rev-parse", "--verify", "origin/master"): GitCommandResult(0, remote_sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(1, "", "missing"),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, f"{remote_sha}	refs/heads/master", ""),
        }
    )

    result = GitService(runner=runner).initialize(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
    )

    assert result["git_created"] is True
    assert result["remote_branch"] == "master"
    assert result["remote_branch_sha"] == remote_sha
    assert result["remote_branch_exists"] is True
    assert ["fetch", "origin", "master:refs/remotes/origin/master"] in runner.calls
    assert ["reset", "--mixed", "origin/master"] in runner.calls
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
            ("rev-parse", "--verify", "origin/master"): GitCommandResult(0, remote_sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, local_sha, ""),
            ("merge-base", "--is-ancestor", "origin/master", "HEAD"): GitCommandResult(1, "", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, f"{remote_sha}	refs/heads/master", ""),
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
        "origin/master",
    ] in runner.calls
    assert not any(call and call[0] == "commit" for call in runner.calls)


def test_init_replaces_template_origin_without_reading_stale_template_master(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    local_sha = "b" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("symbolic-ref", "--quiet", "--short", "HEAD"): GitCommandResult(
                0, "master", ""
            ),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, "", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/aukeys-admin/template.git", ""
            ),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, local_sha, ""),
        }
    )

    result = GitService(runner=runner).initialize(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
    )

    assert result["previous_origin"] == "https://gitea.example/aukeys-admin/template.git"
    assert result["remote_branch_exists"] is False
    assert [
        "remote",
        "set-url",
        "origin",
        "https://gitea.example/apps/demo.git",
    ] in runner.calls
    assert ["update-ref", "-d", "refs/remotes/origin/master"] in runner.calls
    assert not any(call and call[0] in {"fetch", "reset", "merge"} for call in runner.calls)


def test_init_does_not_replace_origin_when_target_preflight_fails(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("symbolic-ref", "--quiet", "--short", "HEAD"): GitCommandResult(
                0, "master", ""
            ),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(1, "", "fatal: 403 Forbidden"),
        }
    )

    with pytest.raises(AppGitError) as caught:
        GitService(runner=runner).initialize(
            tmp_path,
            repo_url="https://gitea.example/apps/demo.git",
        )

    assert caught.value.code == "GIT-002"
    assert not any(call[0] == "remote" and call[1] in {"add", "set-url"} for call in runner.calls)


def test_init_rejects_detached_head_before_replacing_origin(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("symbolic-ref", "--quiet", "--short", "HEAD"): GitCommandResult(
                1, "", "detached"
            ),
        }
    )

    with pytest.raises(AppGitError) as caught:
        GitService(runner=runner).initialize(
            tmp_path,
            repo_url="https://gitea.example/apps/demo.git",
        )

    assert caught.value.code == "GIT-DETACHED-HEAD"
    assert not any(call[0] == "remote" for call in runner.calls)

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
            ("rev-parse", "--verify", "origin/master"): GitCommandResult(0, remote_before, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, sha, ""),
            ("merge-base", "--is-ancestor", "origin/master", "HEAD"): GitCommandResult(0, "", ""),
            ("status", "--porcelain"): GitCommandResult(0, " M index.html", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, f"{sha}	refs/heads/master", ""),
        }
    )

    result = GitService(runner=runner).push_all(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
        message="优化首页",
    )

    assert ["add", "-A"] in runner.calls
    assert ["commit", "-m", "优化首页"] in runner.calls
    assert ["push", "-u", "origin", "HEAD:master"] in runner.calls
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
            ("rev-parse", "--verify", "origin/master"): GitCommandResult(0, sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, sha, ""),
            ("merge-base", "--is-ancestor", "origin/master", "HEAD"): GitCommandResult(0, "", ""),
            ("status", "--porcelain"): GitCommandResult(0, "", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, f"{sha}	refs/heads/master", ""),
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


def test_push_rejects_repository_without_head_or_source(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/apps/demo.git", ""
            ),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(1, "", "missing"),
            ("rev-parse", "--verify", "MERGE_HEAD"): GitCommandResult(1, "", "missing"),
            ("status", "--porcelain"): GitCommandResult(0, "", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, "", ""),
        }
    )

    with pytest.raises(AppGitError) as caught:
        GitService(runner=runner).push_all(
            tmp_path,
            repo_url="https://gitea.example/apps/demo.git",
            message="提交源码",
        )

    assert caught.value.code == "GIT-NO-COMMIT"
    assert ["add", "-A"] not in runner.calls
    assert not any(call and call[0] in {"commit", "push"} for call in runner.calls)


def test_push_rejects_non_fast_forward(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(
                0, "https://gitea.example/apps/demo.git", ""
            ),
            ("rev-parse", "--verify", "origin/master"): GitCommandResult(0, "a" * 40, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, "b" * 40, ""),
            ("merge-base", "--is-ancestor", "origin/master", "HEAD"): GitCommandResult(1, "", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/master",
            ): GitCommandResult(0, f"{'a' * 40}	refs/heads/master", ""),
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


def test_push_rejects_binding_file_that_is_not_ignored(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    binding = tmp_path / ".opscli" / "app.json"
    binding.parent.mkdir()
    binding.write_text("{}", encoding="utf-8")
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            (
                "ls-files",
                "--error-unmatch",
                "--",
                ".opscli/app.json",
            ): GitCommandResult(1, "", "not tracked"),
            (
                "check-ignore",
                "-q",
                "--",
                ".opscli/app.json",
            ): GitCommandResult(1, "", "not ignored"),
        }
    )

    with pytest.raises(AppGitError) as caught:
        GitService(runner=runner).push_all(
            tmp_path,
            repo_url="https://gitea.example/apps/demo.git",
            message="提交源码",
        )

    assert caught.value.code == "APP-BINDING-TRACKED"
    assert ["add", "-A"] not in runner.calls


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_real_git_push_creates_initial_commit_for_empty_remote(tmp_path: Path) -> None:
    target_bare = tmp_path / "target.git"
    target_bare.mkdir()
    _git(target_bare, "init", "--bare", "--initial-branch=master")

    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "index.html").write_text("local index", encoding="utf-8")
    service = GitService()

    initialized = service.initialize(app_root, repo_url=str(target_bare))

    assert initialized["git_created"] is True
    assert initialized["remote_branch_exists"] is False

    _configure_author(app_root)
    pushed = service.push_all(app_root, repo_url=str(target_bare), message="初始化源码")

    assert pushed["committed"] is True
    assert pushed["pushed"] is True
    assert _git(target_bare, "rev-parse", "refs/heads/master") == pushed["commit_sha"]
    assert _git(target_bare, "show", f"{pushed['commit_sha']}:index.html") == "local index"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_real_git_init_preserves_existing_source_and_pushes(tmp_path: Path) -> None:
    target_work = tmp_path / "target-work"
    target_work.mkdir()
    _git(target_work, "init")
    _configure_author(target_work)
    (target_work / "README.md").write_text("remote readme", encoding="utf-8")
    _git(target_work, "add", "-A")
    _git(target_work, "commit", "-m", "initialize master")
    _git(target_work, "branch", "-M", "master")
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
    assert _git(target_bare, "rev-parse", "refs/heads/master") == pushed["commit_sha"]


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
