"""create、init、push 三命令业务编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.app.domain.constants import BINDING_SCHEMA_VERSION, MESSAGE_MAX_LENGTH
from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import AppCreateRequest, SiteBinding, slugify_site_name
from opscli.app.services.binding import BindingStore
from opscli.app.services.gitcred import GitCredentialStore
from opscli.app.services.gitops import GitService
from opscli.app.services.manifest import AppManifestStore
from opscli.app.transport.client import AppHubClient


class AppManager:
    def __init__(
        self,
        *,
        client: AppHubClient | None = None,
        binding_store: BindingStore | None = None,
        git_service: GitService | None = None,
        manifest_store: AppManifestStore | None = None,
        credential_store: GitCredentialStore | None = None,
    ) -> None:
        self.client = client or AppHubClient()
        self.binding_store = binding_store or BindingStore()
        self.git_service = git_service or GitService()
        self.manifest_store = manifest_store or AppManifestStore()
        self.credential_store = credential_store or GitCredentialStore(
            runner=self.git_service.runner
        )

    def close(self) -> None:
        self.client.close()

    def create_app(self, app_name: str, *, path: str | Path | None = None) -> dict:
        """创建并绑定应用，不消费或保存创建响应中的 Git 凭据。"""
        request = AppCreateRequest.from_app_name(app_name)
        root = self.binding_store.prepare_root(path if path is not None else request.name)
        if self.binding_store.is_bound(root):
            binding = self.binding_store.load(root)
            if binding.slug != request.name:
                raise AppProjectError(
                    "APP-ALREADY-BOUND",
                    f"目录已绑定应用：{binding.app_name} ({binding.app_id})",
                )
            binding = binding.migrated()
            self.binding_store.save(root, binding)
            self.manifest_store.sync_identity(root, binding)
            return self._binding_result(root, binding, "目录已绑定该应用，无需重复创建。")

        binding = self._create_binding(root, request)
        return {
            **self._binding_result(root, binding, "应用和独立仓库已创建并保存本地基础信息。"),
            "credential_saved": False,
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

    def _prepare_repository(
        self,
        root: Path,
        *,
        app_slug: str | None = None,
    ) -> tuple[SiteBinding, dict[str, Any], dict[str, Any], dict[str, Any]]:
        binding = self._ensure_binding(root, app_slug=app_slug)
        self.manifest_store.sync_identity(root, binding)
        app_detail = self.client.get_app(binding.slug)
        git_config = self.client.get_git_config(binding.slug)
        binding = self._refresh_binding(
            binding,
            app_detail=app_detail,
            git_config=git_config,
        )
        self.binding_store.save(root, binding)
        self.manifest_store.sync_identity(root, binding)
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

        discovered_name, discovered_slug = self.manifest_store.discover_identity(root)
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
            self.manifest_store.sync_identity(root, binding)
            return binding

        request = AppCreateRequest.from_app_name(app_name, slug=candidate_slug)
        return self._create_binding(root, request)

    def _create_binding(
        self,
        root: Path,
        request: AppCreateRequest,
    ) -> SiteBinding:
        """保存应用基础绑定，忽略创建响应中的内联 Git 凭据。"""
        payload = self.client.create_app(request.to_dict())
        binding = SiteBinding.from_create_response(request.title, payload)
        self.binding_store.save(root, binding)
        self.manifest_store.sync_identity(root, binding)
        return binding

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
def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
