"""Git credential helper 适配测试。"""

from pathlib import Path

from opscli.app.domain.exceptions import AppGitError
from opscli.app.services.gitcred import GitCredentialStore
from opscli.app.services.gitops import GitCommandResult


class FakeRunner:
    def __init__(self, result: GitCommandResult) -> None:
        self.result = result

    def run(self, cwd, args, *, check=True, input_text=None):
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
