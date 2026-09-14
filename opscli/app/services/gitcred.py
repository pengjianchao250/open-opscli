"""通过 Git credential helper 管理用户级 Gitea 凭据。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from opscli.app.domain.exceptions import AppGitError
from opscli.app.services.gitops import GitRunner


class GitCredentialStore:
    def __init__(self, runner: GitRunner | None = None) -> None:
        self.runner = runner or GitRunner()

    def has_credential(
        self,
        root: Path,
        *,
        repo_url: str,
        username: str | None,
        token_hint: str | None = None,
    ) -> bool:
        request = _credential_payload(repo_url, username=username)
        result = self.runner.run(
            root,
            ["credential", "fill"],
            check=False,
            input_text=request,
        )
        if result.returncode != 0:
            return False
        fields = _parse_fields(result.stdout)
        password = fields.get("password")
        if not password or (username is not None and fields.get("username") != username):
            return False
        return token_hint is None or password.endswith(token_hint)

    def save_credential(
        self,
        root: Path,
        *,
        repo_url: str,
        username: str,
        token: str,
    ) -> None:
        if not token or not username:
            raise AppGitError("GIT-002", "AppHub 返回的 Git 凭据不完整。")
        payload = _credential_payload(repo_url, username=username, password=token)
        result = self.runner.run(
            root,
            ["credential", "approve"],
            check=False,
            input_text=payload,
        )
        if result.returncode != 0:
            raise AppGitError(
                "GIT-002",
                "Git 凭据写入系统 credential helper 失败。",
                fix_hint="检查 Git Credential Manager 后重新执行 app init。",
            )

    def erase_credential(
        self,
        root: Path,
        *,
        repo_url: str,
        username: str | None,
    ) -> None:
        request = _credential_payload(repo_url, username=username)
        result = self.runner.run(
            root,
            ["credential", "reject"],
            check=False,
            input_text=request,
        )
        if result.returncode != 0:
            raise AppGitError(
                "GIT-002",
                "清理本机旧 Git 凭据失败。",
                fix_hint="检查 Git Credential Manager 后重新执行 app init。",
            )


def _credential_payload(
    repo_url: str,
    *,
    username: str | None,
    password: str | None = None,
) -> str:
    parsed = urlsplit(repo_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppGitError("GIT-002", "仅支持为 HTTP(S) 仓库保存 Git 凭据。")
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    fields = [f"protocol={parsed.scheme}", f"host={host}"]
    if username:
        fields.append(f"username={username}")
    if password:
        fields.append(f"password={password}")
    return "\n".join(fields) + "\n\n"


def _parse_fields(value: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, item = line.partition("=")
        if separator:
            fields[key] = item
    return fields
