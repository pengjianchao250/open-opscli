"""AppHub 完整客户端业务编排。"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.publish import PublishManager
from opscli.app.services.runner import run_project
from opscli.app.services.sse import parse_sse
from opscli.app.services.templates import manifest_data, render_template


ProgressCallback = Callable[[dict[str, Any]], None]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENV = {"PORT", "APP_BASE_PATH", "APP_DB_PATH", "APP_SLUG"}


class AppManager(PublishManager):
    """在发布编排之上补齐 AppHub 项目全生命周期。"""

    def init_project(
        self,
        slug: str,
        *,
        path: str | Path | None = None,
        runtime: str = "streamlit",
        title: str | None = None,
        offline: bool = False,
    ) -> dict:
        root = Path(path or slug).expanduser().resolve()
        raw = manifest_data(slug=slug, runtime=runtime, title=title)
        self.project_loader.validator.validate(raw)
        files = render_template(root, slug=slug, runtime=runtime, title=title)
        if offline:
            return {
                "slug": slug,
                "path": str(root),
                "runtime": runtime,
                "files": files,
                "registered": False,
                "message": "模板已生成；尚未登记 AppHub 或绑定 Git。",
            }

        created = self.client.create_app(raw)
        repo_url = str(created["repo_url"])
        owner_email = str(created.get("owner_email") or "apphub-user@local.invalid")
        self.git_service.initialize(root, repo_url, author_email=owner_email)
        project = self.project_loader.load(root)
        issued = created.get("git_credential")
        if isinstance(issued, dict) and issued.get("token"):
            binding = self.credentials.store_issued(
                project,
                repo_url=repo_url,
                username=str(issued["username"]),
                token=str(issued["token"]),
                token_hint=str(issued["token_hint"]),
            )
        else:
            config = self.client.get_git_config(slug)
            binding = self.credentials.bind(project, rotate=config.bound)
        commit_sha = self.git_service.initial_push(
            root,
            self.credentials.credential_file,
            f"init: {slug}",
        )
        return {
            "slug": slug,
            "path": str(root),
            "runtime": runtime,
            "files": files,
            "registered": True,
            "repo_url": repo_url,
            "commit_sha": commit_sha,
            "git": binding,
            "message": "AppHub 项目已初始化并推送 main。",
        }

    def run(self, path: str | Path = ".", *, port: int = 8000) -> dict:
        return run_project(self.project_loader.load(path), port=port)

    def validate(self, path: str | Path = ".") -> dict:
        project = self.project_loader.load(path)
        return self.validator.validate(project).to_dict()

    def pull(self, path: str | Path = ".") -> dict:
        project = self.project_loader.load(path)
        config = self.client.get_git_config(project.slug)
        self.git_service.preflight(project.root, project.slug, config.repo_url)
        credential_file = self.credentials.ensure_usable(project, config)
        self.git_service.pull(project.root, credential_file)
        return {"slug": project.slug, "message": "git pull 完成。"}

    def versions(self, path: str | Path = ".", *, page: int = 1, size: int = 20) -> dict:
        project = self.project_loader.load(path)
        return self.client.list_releases(project.slug, page=page, size=size, is_rollback=None)

    def rollback(
        self,
        version: int,
        path: str | Path = ".",
        *,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        project = self.project_loader.load(path)
        preflight = self.client.rollback_preflight(project.slug, version)
        started = self.client.start_rollback(project.slug, version)
        release_id = int(started["release_id"])
        commit_sha = str(started.get("commit_sha") or "")
        with self.client.resume_stream(project.slug, release_id, 0) as response:
            result = self._consume_stream(
                project,
                commit_sha,
                response,
                expected_release_id=release_id,
                require_first_frame=False,
                on_progress=on_progress,
            )
        payload = result.to_dict()
        payload["preflight"] = preflight
        return payload

    def logs(
        self,
        path: str | Path = ".",
        *,
        build: bool = False,
        tail: int = 200,
        follow: bool = False,
        release: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        project = self.project_loader.load(path)
        log_type = "build" if build else "runtime"
        if not follow:
            return self.client.get_logs(project.slug, log_type=log_type, tail=tail, release=release)
        frames = 0
        with self.client.logs_stream(project.slug, log_type=log_type, tail=tail, release=release) as response:
            for frame in parse_sse(response.iter_lines()):
                if frame.event == "done":
                    break
                frames += 1
                if on_progress:
                    on_progress(frame.data)
        return {"slug": project.slug, "follow": True, "frames": frames}

    def env_get(self, path: str | Path = ".") -> dict:
        return self.client.get_env(self.project_loader.load(path).slug)

    def env_set(self, key: str, value: str, path: str | Path = ".") -> dict:
        _validate_env_key(key)
        project = self.project_loader.load(path)
        current = self.client.get_env(project.slug).get("env") or {}
        return self.client.put_env(project.slug, {**current, key: value})

    def env_unset(self, key: str, path: str | Path = ".") -> dict:
        _validate_env_key(key)
        project = self.project_loader.load(path)
        current = dict(self.client.get_env(project.slug).get("env") or {})
        current.pop(key, None)
        return self.client.put_env(project.slug, current)

    def secret_list(self, path: str | Path = ".") -> dict:
        return self.client.list_secrets(self.project_loader.load(path).slug)

    def secret_set(self, key: str, value: str, path: str | Path = ".") -> dict:
        _validate_env_key(key)
        return self.client.put_secrets(self.project_loader.load(path).slug, {key: value})

    def secret_unset(self, key: str, path: str | Path = ".") -> dict:
        _validate_env_key(key)
        return self.client.delete_secret(self.project_loader.load(path).slug, key)

    def members_list(self, path: str | Path = ".") -> dict:
        return self.client.list_members(self.project_loader.load(path).slug)

    def members_add(self, email: str, path: str | Path = ".") -> dict:
        return self.client.add_member(self.project_loader.load(path).slug, _validate_email(email))

    def members_remove(self, email: str, path: str | Path = ".") -> dict:
        return self.client.remove_member(self.project_loader.load(path).slug, _validate_email(email))

    def db_info(self, path: str | Path = ".") -> dict:
        return self.client.get_db(self.project_loader.load(path).slug)

    def db_backups(self, path: str | Path = ".") -> dict:
        payload = self.db_info(path)
        return {"backups": payload.get("backups") or []}

    def db_restore(
        self,
        backup_date: str,
        confirm: str,
        path: str | Path = ".",
        *,
        filename: str | None = None,
    ) -> dict:
        project = self.project_loader.load(path)
        if confirm != project.slug:
            raise AppProjectError("DB-007-CONFIRM", "确认串与应用 slug 不一致。")
        return self.client.restore_db(
            project.slug,
            backup_date=backup_date,
            confirm=confirm,
            filename=filename,
        )


def _validate_email(email: str) -> str:
    value = email.strip().lower()
    if not _EMAIL.fullmatch(value):
        raise AppProjectError("INVALID_ARGUMENT", f"邮箱格式不正确：{email}")
    return value


def _validate_env_key(key: str) -> None:
    if not _ENV_KEY.fullmatch(key):
        raise AppProjectError("INVALID_ARGUMENT", f"环境变量键不合法：{key}")
    if key in _RESERVED_ENV:
        raise AppProjectError(
            "INVALID_ARGUMENT",
            f"{key} 是平台保留键。",
            fix_hint="平台保留键由 AppHub 注入，请使用其他键名。",
        )
