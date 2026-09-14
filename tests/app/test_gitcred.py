"""Git credential helper 适配测试。"""

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppGitError
from opscli.app.services.gitcred import GitCredentialStore
from opscli.app.services.gitops import GitCommandResult


class FakeRunner:
    def __init__(self, result: GitCommandResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def run(self, cwd, args, *, check=True, input_text=None):
        self.calls.append(
            {"cwd": cwd, "args": args, "check": check, "input_text": input_text}
        )
        return self.result


def test_has_credential_matches_server_token_hint(tmp_path: Path) -> None:
    runner = FakeRunner(
        GitCommandResult(
            0,
            "protocol=http\nhost=git.example\nusername=owner\npassword=issued-token-12345678\n",
            "",
        )
    )

    store = GitCredentialStore(runner=runner)

    assert store.has_credential(
        tmp_path,
        repo_url="http://git.example/apps/demo.git",
        username="owner",
        token_hint="12345678",
    )
    assert not store.has_credential(
        tmp_path,
        repo_url="http://git.example/apps/demo.git",
        username="owner",
        token_hint="87654321",
    )


def test_has_credential_accepts_missing_token_hint_for_legacy_configs(tmp_path: Path) -> None:
    runner = FakeRunner(
        GitCommandResult(
            0,
            "username=owner\npassword=legacy-token\n",
            "",
        )
    )

    assert GitCredentialStore(runner=runner).has_credential(
        tmp_path,
        repo_url="https://git.example/apps/demo.git",
        username="owner",
    )


def test_erase_credential_rejects_matching_helper_entry(tmp_path: Path) -> None:
    runner = FakeRunner(GitCommandResult(0, "", ""))

    GitCredentialStore(runner=runner).erase_credential(
        tmp_path,
        repo_url="https://git.example/apps/demo.git",
        username="owner",
    )

    assert runner.calls == [
        {
            "cwd": tmp_path,
            "args": ["credential", "reject"],
            "check": False,
            "input_text": "protocol=https\nhost=git.example\nusername=owner\n\n",
        }
    ]


def test_erase_credential_reports_helper_failure(tmp_path: Path) -> None:
    runner = FakeRunner(GitCommandResult(1, "", "helper failed"))

    with pytest.raises(AppGitError, match="清理本机旧 Git 凭据失败"):
        GitCredentialStore(runner=runner).erase_credential(
            tmp_path,
            repo_url="https://git.example/apps/demo.git",
            username="owner",
        )
