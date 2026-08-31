"""受控 Git credential 文件的绑定、探测与吊销。"""

from __future__ import annotations

import os
import getpass
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from opscli.app.domain.exceptions import GitCredentialError
from opscli.app.domain.models import AppProject, GitConfig
from opscli.app.services.gitops import GitRunner, GitService
from opscli.app.transport.client import AppHubClient
from opscli.config import CONFIG_DIR


class GitCredentialService:
    """唯一允许执行 git credential 子进程的服务。"""

    def __init__(
        self,
        client: AppHubClient,
        git_service: GitService,
        *,
        base_dir: Path | None = None,
        runner: GitRunner | None = None,
    ) -> None:
        self.client = client
        self.git_service = git_service
        self.runner = runner or git_service.runner
        self.base_dir = (base_dir or CONFIG_DIR).expanduser().resolve()
        self.credential_file = self.base_dir / "app" / "git-credentials"

    def bind(self, project: AppProject, *, rotate: bool) -> dict:
        """签发、落盘并通过 ls-remote 验证凭据。"""
        config = self.client.get_git_config(project.slug)
        self.git_service.preflight(project.root, project.slug, config.repo_url)
        username, token, token_hint = self.client.issue_git_credential(rotate=rotate)
        try:
            self._approve(config.repo_url, username, token, project.root)
            self.git_service.probe(project.root, config.repo_url, self.credential_file)
        except Exception:
            self._reject(config.repo_url, username, project.root)
            raise
        finally:
            token = ""
        return {"slug": project.slug, "username": username, "token_hint": token_hint, "bound": True}

    def status(self, project: AppProject) -> dict:
        """返回服务端绑定状态和本地探活结果。"""
        config = self.client.get_git_config(project.slug)
        self.git_service.preflight(project.root, project.slug, config.repo_url)
        local_exists = self.credential_file.is_file()
        usable = False
        if local_exists:
            try:
                self.git_service.probe(project.root, config.repo_url, self.credential_file)
                usable = True
            except GitCredentialError:
                usable = False
        return {
            "slug": project.slug,
            "repo_url": config.repo_url,
            "server_bound": config.bound,
            "local_credential": local_exists,
            "usable": usable,
            "token_hint": config.token_hint,
        }

    def ensure_usable(self, project: AppProject, config: GitConfig) -> Path:
        """发布前确认本地受控凭据可用。"""
        if not self.credential_file.is_file():
            hint = "执行 opscli app git bind。"
            if config.bound:
                hint = "服务端已有凭据但本机无副本；执行 opscli app git bind --rotate。"
            raise GitCredentialError("GIT-002", "本机没有 AppHub Git 凭据。", fix_hint=hint)
        self.git_service.probe(project.root, config.repo_url, self.credential_file)
        return self.credential_file

    def revoke(self) -> dict:
        """吊销服务端凭据并清理本地受控文件。"""
        revoked_count = self.client.revoke_git_credential()
        if self.credential_file.exists() and not self.credential_file.is_symlink():
            self.credential_file.unlink()
        return {"revoked": True, "revoked_count": revoked_count, "local_removed": True}

    def _approve(self, repo_url: str, username: str, token: str, cwd: Path) -> None:
        self.credential_file.parent.mkdir(parents=True, exist_ok=True)
        if self.credential_file.is_symlink():
            raise GitCredentialError("GIT-002", "受控 Git credential 文件不能是符号链接。")
        payload = _credential_payload(repo_url, username=username, password=token)
        self.runner.run(
            cwd,
            ["credential", "approve"],
            credential_file=self.credential_file,
            input_text=payload,
        )
        if os.name != "nt":
            self.credential_file.chmod(0o600)
        else:
            self._restrict_windows_acl()

    def _reject(self, repo_url: str, username: str, cwd: Path) -> None:
        if not self.credential_file.parent.exists():
            return
        payload = _credential_payload(repo_url, username=username)
        self.runner.run(
            cwd,
            ["credential", "reject"],
            credential_file=self.credential_file,
            input_text=payload,
            check=False,
        )

    def _restrict_windows_acl(self) -> None:
        """Windows 下移除继承 ACL，仅授予当前用户读写权限。"""
        completed = subprocess.run(
            [
                "icacls",
                str(self.credential_file),
                "/inheritance:r",
                "/grant:r",
                f"{getpass.getuser()}:(R,W)",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            shell=False,
            check=False,
        )
        if completed.returncode != 0:
            self.credential_file.unlink(missing_ok=True)
            raise GitCredentialError(
                "GIT-002",
                "无法收紧 Git credential 文件的 Windows ACL，已删除本地凭据。",
                fix_hint="确认当前用户可调用 icacls 后重新执行 app git bind。",
            )


def _credential_payload(repo_url: str, *, username: str, password: str | None = None) -> str:
    parsed = urlsplit(repo_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise GitCredentialError("GIT-002", "AppHub repo_url 必须是 HTTP(S) 地址。")
    lines = [f"protocol={parsed.scheme}", f"host={parsed.netloc}", f"username={username}"]
    if password is not None:
        lines.append(f"password={password}")
    return "\n".join(lines) + "\n\n"
