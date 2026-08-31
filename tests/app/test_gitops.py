"""D9 Git 编排和 credential helper 安全测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import GitNonFastForwardError
from opscli.app.services.gitops import GitCommandResult, GitRunner, GitService, _parse_git_version


class FakeRunner:
    """按命令返回稳定结果并记录参数。"""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], Path | None, str | None]] = []

    def run(self, cwd, args, *, credential_file=None, input_text=None, check=True):
        self.calls.append((args, credential_file, input_text))
        code, stdout = self.responses.get(tuple(args), (0, ""))
        return GitCommandResult(code, stdout, "")


def test_parse_git_version() -> None:
    assert _parse_git_version("git version 2.45.2.windows.1") == (2, 45, 2)


def test_clean_local_ahead_uses_normal_push(tmp_path: Path) -> None:
    local = "b" * 40
    remote = "a" * 40
    runner = FakeRunner({
        ("rev-parse", "HEAD"): (0, local),
        ("rev-parse", "origin/main"): (0, remote),
        ("merge-base", "--is-ancestor", "origin/main", "HEAD"): (0, ""),
    })
    service = GitService(runner=runner)

    sha, pushed = service.select_publish_sha(
        tmp_path,
        tmp_path / "credentials",
        dirty=False,
        message="publish",
    )

    assert (sha, pushed) == (local, True)
    push_call = next(call for call in runner.calls if call[0][0] == "push")
    assert push_call[0] == ["push", "origin", "HEAD:main"]
    assert "--force" not in push_call[0]


def test_diverged_branch_is_rejected(tmp_path: Path) -> None:
    runner = FakeRunner({
        ("rev-parse", "HEAD"): (0, "b" * 40),
        ("rev-parse", "origin/main"): (0, "a" * 40),
        ("merge-base", "--is-ancestor", "origin/main", "HEAD"): (1, ""),
        ("merge-base", "--is-ancestor", "HEAD", "origin/main"): (1, ""),
    })

    with pytest.raises(GitNonFastForwardError):
        GitService(runner=runner).select_publish_sha(
            tmp_path,
            tmp_path / "credentials",
            dirty=False,
            message="publish",
        )


def test_git_runner_places_controlled_helper_before_subcommand(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    token = "secret-token-value"

    GitRunner().run(
        tmp_path,
        ["credential", "approve"],
        credential_file=tmp_path / "git-credentials",
        input_text=f"password={token}\n\n",
    )

    command = captured["command"]
    assert command[:5] == [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        f"credential.helper=store --file={tmp_path / 'git-credentials'}",
    ]
    assert token not in " ".join(command)
    assert token in captured["input"]

