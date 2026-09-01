"""Git 初始化与普通推送测试。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from opscli.app.services.gitops import GitCommandResult, GitService, _parse_git_version


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], GitCommandResult] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def run(self, cwd, args, *, check=True):
        self.calls.append(args)
        result = self.responses.get(tuple(args), GitCommandResult(0, "", ""))
        if check and result.returncode != 0:
            raise AssertionError(f"unexpected checked failure: {args}")
        return result


def test_parse_git_version() -> None:
    assert _parse_git_version("git version 2.45.2.windows.1") == (2, 45, 2)


def test_empty_project_fetches_template_and_sets_origin(tmp_path: Path) -> None:
    runner = FakeRunner({
        ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
        ("remote", "get-url", "template"): GitCommandResult(2, "", "missing"),
        ("remote", "get-url", "origin"): GitCommandResult(2, "", "missing"),
    })
    service = GitService(runner=runner)

    result = service.initialize(
        tmp_path,
        repo_url="https://gitlab.example/sites/demo.git",
        template_repo_url="https://gitlab.example/templates/sites.git",
        template_branch="template",
        apply_template=True,
    )

    assert result["template_applied"] is True
    assert ["fetch", "template", "template"] in runner.calls
    assert ["checkout", "-B", "main", "FETCH_HEAD"] in runner.calls
    assert ["remote", "add", "origin", "https://gitlab.example/sites/demo.git"] in runner.calls


def test_push_commits_every_change_and_never_forces(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sha = "a" * 40
    runner = FakeRunner({
        ("--version",): GitCommandResult(0, "git version 2.45.2", ""),
        ("remote", "get-url", "origin"): GitCommandResult(
            0, "https://gitlab.example/sites/demo.git", ""
        ),
        ("status", "--porcelain"): GitCommandResult(0, " M index.html", ""),
        ("rev-parse", "--verify", "HEAD"): GitCommandResult(0, sha, ""),
    })
    service = GitService(runner=runner)

    result = service.push_all(
        tmp_path,
        repo_url="https://gitlab.example/sites/demo.git",
        message="优化首页",
    )

    assert ["add", "-A"] in runner.calls
    assert ["commit", "-m", "优化首页"] in runner.calls
    push = ["push", "-u", "origin", "HEAD:main"]
    assert push in runner.calls
    assert "--force" not in push
    assert result == {"commit_sha": sha, "committed": True, "pushed": True}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_real_git_template_init_preserves_binding_and_pushes(tmp_path: Path) -> None:
    template_work = tmp_path / "template-work"
    template_work.mkdir()
    _git(template_work, "init")
    _git(template_work, "config", "user.name", "Test User")
    _git(template_work, "config", "user.email", "test@example.com")
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
    target_bare = tmp_path / "target.git"
    target_bare.mkdir()
    _git(target_bare, "init", "--bare")

    site = tmp_path / "site"
    (site / ".opscli").mkdir(parents=True)
    binding = site / ".opscli" / "app.json"
    binding.write_text('{"site_id":"site-1"}\n', encoding="utf-8")

    service = GitService()
    initialized = service.initialize(
        site,
        repo_url=str(target_bare),
        template_repo_url=str(template_bare),
        template_branch="template",
        apply_template=True,
    )

    assert initialized["template_applied"] is True
    assert (site / "index.html").read_text(encoding="utf-8") == "template"
    assert binding.is_file()

    _git(site, "config", "user.name", "Test User")
    _git(site, "config", "user.email", "test@example.com")
    pushed = service.push_all(site, repo_url=str(target_bare), message="绑定站点")

    assert pushed["committed"] is True
    assert _git(target_bare, "rev-parse", "refs/heads/main") == pushed["commit_sha"]


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
