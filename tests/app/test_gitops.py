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


def test_empty_project_bases_main_on_origin_then_applies_template(tmp_path: Path) -> None:
    remote_sha = "a" * 40
    runner = FakeRunner(
        {
            ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
            ("remote", "get-url", "origin"): GitCommandResult(2, "", "missing"),
            (
                "rev-parse",
                "--verify",
                "origin/main",
            ): GitCommandResult(0, remote_sha, ""),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(1, "", "missing"),
            ("remote", "get-url", "template"): GitCommandResult(2, "", "missing"),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/main",
            ): GitCommandResult(0, f"{remote_sha}\trefs/heads/main", ""),
        }
    )
    service = GitService(runner=runner)

    result = service.initialize(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
        template_repo_url="https://git.example/templates/sites.git",
        template_branch="main",
        apply_template=True,
    )

    assert result["template_applied"] is True
    assert ["fetch", "origin", "main:refs/remotes/origin/main"] in runner.calls
    assert ["reset", "--mixed", "origin/main"] in runner.calls
    assert [
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=",
        "fetch",
        "template",
        "main",
    ] in runner.calls
    assert ["checkout", "FETCH_HEAD", "--", "."] in runner.calls
    assert ["remote", "remove", "template"] in runner.calls
    assert ["remote", "add", "origin", "https://gitea.example/apps/demo.git"] in runner.calls


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
            ("rev-parse", "--verify", "origin/main"): GitCommandResult(
                0, remote_before, ""
            ),
            ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, sha, ""),
            ("merge-base", "--is-ancestor", "origin/main", "HEAD"): GitCommandResult(
                0, "", ""
            ),
            ("status", "--porcelain"): GitCommandResult(0, " M index.html", ""),
            (
                "ls-remote",
                "https://gitea.example/apps/demo.git",
                "refs/heads/main",
            ): GitCommandResult(0, f"{sha}\trefs/heads/main", ""),
        }
    )
    service = GitService(runner=runner)

    result = service.push_all(
        tmp_path,
        repo_url="https://gitea.example/apps/demo.git",
        message="优化首页",
    )

    assert ["add", "-A"] in runner.calls
    assert ["commit", "-m", "优化首页"] in runner.calls
    push = ["push", "-u", "origin", "HEAD:main"]
    assert push in runner.calls
    assert all("--force" not in call for call in runner.calls)
    assert result["remote_commit_sha"] == sha


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
            ("merge-base", "--is-ancestor", "origin/main", "HEAD"): GitCommandResult(
                1, "", ""
            ),
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
def test_real_git_init_uses_remote_main_as_ancestor(tmp_path: Path) -> None:
    target_work = tmp_path / "target-work"
    target_work.mkdir()
    _git(target_work, "init")
    _configure_author(target_work)
    (target_work / "README.md").write_text("apphub", encoding="utf-8")
    _git(target_work, "add", "-A")
    _git(target_work, "commit", "-m", "initialize main")
    _git(target_work, "branch", "-M", "main")
    target_bare = tmp_path / "target.git"
    subprocess.run(
        ["git", "clone", "--bare", str(target_work), str(target_bare)],
        check=True,
        capture_output=True,
    )

    template_work = tmp_path / "template-work"
    template_work.mkdir()
    _git(template_work, "init")
    _configure_author(template_work)
    (template_work / "index.html").write_text("template", encoding="utf-8")
    _git(template_work, "add", "-A")
    _git(template_work, "commit", "-m", "template")
    _git(template_work, "branch", "-M", "template")
    template_bare = tmp_path / "template.git"
    subprocess.run(
        ["git", "clone", "--bare", str(template_work), str(template_bare)],
        check=True,
        capture_output=True,
    )

    site = tmp_path / "site"
    (site / ".opscli").mkdir(parents=True)
    binding = site / ".opscli" / "app.json"
    binding.write_text('{"app_id":"app-1"}\n', encoding="utf-8")

    service = GitService()
    initialized = service.initialize(
        site,
        repo_url=str(target_bare),
        template_repo_url=str(template_bare),
        template_branch="template",
        apply_template=True,
    )

    assert initialized["template_applied"] is True
    assert (site / "README.md").read_text(encoding="utf-8") == "apphub"
    assert (site / "index.html").read_text(encoding="utf-8") == "template"
    assert binding.is_file()

    _configure_author(site)
    pushed = service.push_all(site, repo_url=str(target_bare), message="应用模板")

    assert pushed["committed"] is True
    assert _git(target_bare, "rev-parse", "refs/heads/main") == pushed["commit_sha"]
    assert _git(site, "merge-base", "--is-ancestor", "origin/main", "HEAD") == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_real_git_existing_source_is_not_overwritten(tmp_path: Path) -> None:
    target_work = tmp_path / "target-work"
    target_work.mkdir()
    _git(target_work, "init")
    _configure_author(target_work)
    (target_work / "README.md").write_text("remote readme", encoding="utf-8")
    (target_work / "index.html").write_text("remote index", encoding="utf-8")
    _git(target_work, "add", "-A")
    _git(target_work, "commit", "-m", "initialize main")
    _git(target_work, "branch", "-M", "main")
    target_bare = tmp_path / "target.git"
    subprocess.run(
        ["git", "clone", "--bare", str(target_work), str(target_bare)],
        check=True,
        capture_output=True,
    )

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("local index", encoding="utf-8")
    service = GitService()

    service.initialize(
        site,
        repo_url=str(target_bare),
        template_repo_url=str(target_bare),
        template_branch="main",
        apply_template=False,
    )

    assert (site / "index.html").read_text(encoding="utf-8") == "local index"
    assert (site / "README.md").read_text(encoding="utf-8") == "remote readme"


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
