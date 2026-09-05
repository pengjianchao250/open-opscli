"""create、init、push、release 四命令业务编排。"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from opscli.app.domain.constants import BINDING_SCHEMA_VERSION, MESSAGE_MAX_LENGTH
from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import AppYaml, SiteBinding, slugify_site_name
from opscli.app.services.binding import BindingStore
from opscli.app.services.gitcred import GitCredentialStore
from opscli.app.services.gitops import GitService
from opscli.app.services.publish import PublishService
from opscli.app.transport.client import AppHubClient

_YAML_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")


class AppManager:
    def __init__(
        self,
        *,
        client: AppHubClient | None = None,
        binding_store: BindingStore | None = None,
        git_service: GitService | None = None,
        credential_store: GitCredentialStore | None = None,
        publish_service: PublishService | None = None,
        release_event_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.client = client or AppHubClient()
        self.binding_store = binding_store or BindingStore()
        self.git_service = git_service or GitService()
        self.credential_store = credential_store or GitCredentialStore(
            runner=self.git_service.runner
        )
        self.publish_service = publish_service or PublishService(self.client)
        self.release_event_handler = release_event_handler

    def close(self) -> None:
        self.client.close()

    def create_app(self, app_name: str, *, path: str | Path | None = None) -> dict:
        app_yaml = AppYaml.from_app_name(app_name)
        if path is not None:
            root = self.binding_store.prepare_root(path)
            if self.binding_store.is_bound(root):
                binding = self.binding_store.load(root)
                if binding.slug != app_yaml.name:
                    raise AppProjectError(
                        "APP-ALREADY-BOUND",
                        f"目录已绑定应用：{binding.app_name} ({binding.app_id})",
                    )
                binding = binding.migrated()
                self.binding_store.save(root, binding)
                return self._binding_result(root, binding, "目录已绑定该应用，无需重复创建。")
        else:
            root = self.binding_store.prepare_root(app_yaml.name)

        binding, credential_saved = self._create_binding(root, app_yaml)
        return {
            **self._binding_result(root, binding, "应用和独立仓库已创建并保存本地基础信息。"),
            "credential_saved": credential_saved,
        }

    def create_site(self, site_name: str, *, path: str | Path | None = None) -> dict:
        """兼容旧 SDK 方法名。"""
        return self.create_app(site_name, path=path)

    def init_git(
        self,
        path: str | Path = ".",
        *,
        app_slug: str | None = None,
    ) -> dict:
        root = self.binding_store.prepare_root(path)
        binding, credential_result, git_result, _ = self._prepare_repository(
            root,
            app_slug=app_slug,
        )
        return {
            **self._binding_result(root, binding, "Git 已绑定应用仓库并基于远端 main 初始化。"),
            **credential_result,
            **git_result,
        }

    def push(self, path: str | Path = ".", *, message: str) -> dict:
        summary = self._validate_message(message, command="push")
        root = self.binding_store.prepare_root(path)
        binding, credential_result, git_init_result, _ = self._prepare_repository(root)
        git_result = self.git_service.push_all(
            root,
            repo_url=binding.repo_url,
            message=summary,
        )
        message_text = (
            "源码已推送到远端仓库。"
            if git_result.get("pushed")
            else "远端 main 已是最新源码，无需重复推送。"
        )
        return {
            **self._binding_result(root, binding, ""),
            **credential_result,
            **git_init_result,
            **git_result,
            "message": message_text,
        }

    def release(self, path: str | Path = ".", *, message: str) -> dict:
        summary = self._validate_message(message, command="release")
        root = self.binding_store.prepare_root(path)
        binding, credential_result, git_init_result, app_detail = self._prepare_repository(root)
        git_result = self.git_service.push_all(
            root,
            repo_url=binding.repo_url,
            message=summary,
        )
        self._assert_releasable(app_detail)
        releases = self.client.list_releases(
            binding.slug,
            page=1,
            size=1,
            is_rollback=False,
        )
        publish_result = self.publish_service.publish(
            binding.slug,
            commit_sha=git_result["remote_commit_sha"],
            message=summary,
            releases_payload=releases,
            on_event=self.release_event_handler,
        )
        final_detail = app_detail
        if publish_result["status"] != "noop":
            final_detail = self.client.get_app(binding.slug)
        return {
            **self._binding_result(root, binding, ""),
            **credential_result,
            **git_init_result,
            **git_result,
            **publish_result,
            "version": (
                final_detail.get("current_version")
                or final_detail.get("display_version")
                or final_detail.get("version")
            ),
            "url": final_detail.get("url"),
            "message": publish_result.get("message") or "AppHub 应用版本已发布。",
        }

    def _prepare_repository(
        self,
        root: Path,
        *,
        app_slug: str | None = None,
    ) -> tuple[SiteBinding, dict[str, Any], dict[str, Any], dict[str, Any]]:
        binding = self._ensure_binding(root, app_slug=app_slug)
        app_detail = self.client.get_app(binding.slug)
        git_config = self.client.get_git_config(binding.slug)
        binding = self._refresh_binding(
            binding,
            app_detail=app_detail,
            git_config=git_config,
        )
        self.binding_store.save(root, binding)
        binding, credential_result = self._ensure_credential(root, binding, git_config)
        git_result = self.git_service.initialize(root, repo_url=binding.repo_url)
        return binding, credential_result, git_result, app_detail

    def _ensure_binding(
        self,
        root: Path,
        *,
        app_slug: str | None,
    ) -> SiteBinding:
        if self.binding_store.is_bound(root):
            binding = self.binding_store.load(root)
            if app_slug is not None and binding.slug != slugify_site_name(app_slug):
                raise AppProjectError(
                    "APP-ALREADY-BOUND",
                    f"目录已绑定应用：{binding.app_name} ({binding.slug})",
                )
            return binding

        discovered_name, discovered_slug = _discover_app_identity(root)
        candidate_slug = slugify_site_name(app_slug) if app_slug else discovered_slug
        app_name = discovered_name or root.name or candidate_slug

        accessible_payload = self.client.list_accessible_apps()
        accessible_apps = accessible_payload.get("apps")
        if not isinstance(accessible_apps, list):
            raise AppProjectError(
                "APPHUB-PROTOCOL",
                "AppHub 可访问应用响应缺少 apps 列表。",
            )
        matches = [
            item
            for item in accessible_apps
            if isinstance(item, dict) and _optional_text(item.get("slug")) == candidate_slug
        ]
        if len(matches) > 1:
            raise AppProjectError(
                "APP-AMBIGUOUS",
                f"存在多个匹配应用：{candidate_slug}",
                fix_hint="请使用 --app 显式指定应用 slug。",
            )
        if matches:
            summary = matches[0]
            detail = self.client.get_app(candidate_slug)
            binding = SiteBinding.from_app_detail(
                _optional_text(detail.get("title"))
                or _optional_text(summary.get("title"))
                or app_name,
                detail,
            )
            self.binding_store.save(root, binding)
            return binding

        app_yaml = AppYaml.from_app_name(app_name, slug=candidate_slug)
        binding, _ = self._create_binding(root, app_yaml)
        return binding

    def _create_binding(
        self,
        root: Path,
        app_yaml: AppYaml,
    ) -> tuple[SiteBinding, bool]:
        payload = self.client.create_app(app_yaml.to_dict())
        binding = SiteBinding.from_create_response(app_yaml.title, payload)
        self.binding_store.save(root, binding)
        credential_saved = self._save_inline_credential(root, binding, payload)
        return binding, credential_saved

    def _save_inline_credential(
        self,
        root: Path,
        binding: SiteBinding,
        payload: dict[str, Any],
    ) -> bool:
        credential = payload.get("git_credential")
        if not isinstance(credential, dict):
            return False
        token = credential.get("token")
        username = credential.get("username") or binding.git_username
        if not token or not username:
            return False
        self.credential_store.save_credential(
            root,
            repo_url=binding.repo_url,
            username=str(username),
            token=str(token),
        )
        return True

    def _ensure_credential(
        self,
        root: Path,
        binding: SiteBinding,
        git_config: dict[str, Any],
    ) -> tuple[SiteBinding, dict[str, Any]]:
        username = _optional_text(git_config.get("username")) or binding.git_username
        if self.credential_store.has_credential(
            root,
            repo_url=binding.repo_url,
            username=username,
        ):
            return binding, {"credential_refreshed": False, "credential_rotated": False}

        rotate = bool(git_config.get("bound"))
        issued = self.client.issue_git_credential(rotate=rotate)
        token = _optional_text(issued.get("token"))
        issued_username = _optional_text(issued.get("username")) or username
        if token is None or issued_username is None:
            raise AppProjectError("GIT-002", "AppHub 签发的 Git 凭据不完整。")
        self.credential_store.save_credential(
            root,
            repo_url=binding.repo_url,
            username=issued_username,
            token=token,
        )
        binding = binding.migrated(git_username=issued_username)
        self.binding_store.save(root, binding)
        return binding, {"credential_refreshed": True, "credential_rotated": rotate}

    def _refresh_binding(
        self,
        binding: SiteBinding,
        *,
        app_detail: dict[str, Any],
        git_config: dict[str, Any],
    ) -> SiteBinding:
        repo_url = _optional_text(git_config.get("repo_url")) or _optional_text(
            app_detail.get("repo_url")
        )
        if repo_url is None:
            raise AppProjectError(
                "APPHUB-PROTOCOL",
                "AppHub git-config 响应缺少 repo_url。",
            )
        app_id = _optional_text(
            app_detail.get("app_id") or app_detail.get("id") or app_detail.get("site_id")
        ) or binding.app_id
        return binding.migrated(
            app_id=app_id,
            app_name=_optional_text(app_detail.get("title")) or binding.app_name,
            repo_url=repo_url,
            git_username=_optional_text(git_config.get("username")) or binding.git_username,
            owner_user_id=_optional_text(app_detail.get("owner_user_id"))
            or binding.owner_user_id,
            owner_email=_optional_text(
                app_detail.get("owner_email") or app_detail.get("owner")
            )
            or binding.owner_email,
        )

    def _assert_releasable(self, app_detail: dict[str, Any]) -> None:
        status = _optional_text(app_detail.get("status"))
        if status in {"disabled", "archived", "deleted"}:
            raise AppProjectError(
                "APP-STATE",
                f"应用当前状态为 {status}，不能发布版本。",
                fix_hint="请先在 AppHub 处理应用生命周期状态。",
            )

    def _validate_message(self, message: str, *, command: str) -> str:
        summary = message.strip()
        if not summary:
            raise AppProjectError("APP-ARGUMENT", f"{command} 必须提供说明。")
        if len(summary) > MESSAGE_MAX_LENGTH:
            raise AppProjectError("APP-ARGUMENT", f"说明最长 {MESSAGE_MAX_LENGTH} 字符。")
        return summary

    def _binding_result(self, root: Path, binding: SiteBinding, message: str) -> dict:
        return {
            "app_id": binding.app_id,
            "app_name": binding.app_name,
            "slug": binding.slug,
            "path": str(root),
            "repo_url": binding.repo_url,
            "default_branch": binding.default_branch,
            "git_username": binding.git_username,
            "binding_schema_version": BINDING_SCHEMA_VERSION,
            "binding_file": str(root / ".opscli" / "app.json"),
            "message": message,
        }


def _discover_app_identity(root: Path) -> tuple[str | None, str]:
    app_yaml = root / "app.yaml"
    values: dict[str, str] = {}
    if app_yaml.is_file():
        try:
            for line in app_yaml.read_text(encoding="utf-8").splitlines():
                match = _YAML_SCALAR_RE.match(line)
                if not match:
                    continue
                key, raw_value = match.groups()
                value = raw_value.strip().strip('"').strip("'")
                if key in {"name", "title"} and value:
                    values[key] = value
        except (OSError, UnicodeError) as exc:
            raise AppProjectError(
                "APP-BINDING-INVALID",
                f"读取 app.yaml 失败：{exc}",
            ) from exc
    app_name = values.get("title") or values.get("name") or root.name
    slug = slugify_site_name(values.get("name") or root.name)
    return app_name, slug


def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
