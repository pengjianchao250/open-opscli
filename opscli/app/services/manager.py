"""`create / init / push` 三命令业务编排。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from opscli.app.domain.constants import (
    BINDING_SCHEMA_VERSION,
    MESSAGE_MAX_LENGTH,
)
from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import AppYaml, SiteBinding
from opscli.app.services.binding import BindingStore
from opscli.app.services.gitcred import GitCredentialStore
from opscli.app.services.gitops import GitService
from opscli.app.services.publish import PublishService
from opscli.app.transport.client import AppHubClient
from opscli.auth.config import get_app_template_branch, get_app_template_repo


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

    def create_site(self, site_name: str, *, path: str | Path | None = None) -> dict:
        app_yaml = AppYaml.from_site_name(site_name)
        if path is not None:
            root = self.binding_store.prepare_root(path)
            if self.binding_store.is_bound(root):
                binding = self.binding_store.load(root)
                if binding.site_name != app_yaml.title:
                    raise AppProjectError(
                        "APP-ALREADY-BOUND",
                        f"目录已绑定站点：{binding.site_name} ({binding.app_id})",
                    )
                return self._binding_result(root, binding, "目录已绑定该站点，无需重复创建。")

        payload = self.client.create_app(app_yaml.to_dict())
        binding = SiteBinding.from_create_response(
            app_yaml.title,
            payload,
            template_repo_url=get_app_template_repo(),
            template_branch=get_app_template_branch(),
        )
        root = self.binding_store.prepare_root(path or binding.slug)
        self.binding_store.save(root, binding)
        credential_saved = self._save_inline_credential(root, binding, payload)
        return {
            **self._binding_result(root, binding, "站点、独立仓库和 main 已创建并完成本地绑定。"),
            "credential_saved": credential_saved,
        }

    def init_git(self, path: str | Path = ".") -> dict:
        root = self.binding_store.prepare_root(path)
        binding = self.binding_store.load(root)
        app_detail = self.client.get_app(binding.slug) if binding.schema_version == 1 else {}
        git_config = self.client.get_git_config(binding.slug)
        binding = self._refresh_binding(binding, app_detail=app_detail, git_config=git_config)
        self.binding_store.save(root, binding)
        binding, credential_result = self._ensure_credential(root, binding, git_config)

        source_exists = self.binding_store.has_source_files(root)
        template_repo_url = binding.template_repo_url
        template_branch = binding.template_branch
        if not source_exists:
            template_repo_url = get_app_template_repo()
            template_branch = get_app_template_branch()
        result = self.git_service.initialize(
            root,
            repo_url=binding.repo_url,
            template_repo_url=template_repo_url,
            template_branch=template_branch,
            apply_template=not source_exists,
        )
        if result["template_applied"]:
            binding = binding.migrated(
                template_repo_url=template_repo_url,
                template_branch=template_branch,
            )
        self.binding_store.save(root, binding)
        return {
            **self._binding_result(root, binding, "Git 已基于远端 main 初始化。"),
            **credential_result,
            **result,
            "message": (
                "Git 已基于远端 main 初始化并应用模板内容。"
                if result["template_applied"]
                else "Git 已基于远端 main 初始化；已有源码未被覆盖。"
            ),
        }

    def push(self, path: str | Path = ".", *, message: str) -> dict:
        summary = message.strip()
        if not summary:
            raise AppProjectError("APP-ARGUMENT", "push 必须提供一句话修改总结。")
        if len(summary) > MESSAGE_MAX_LENGTH:
            raise AppProjectError("APP-ARGUMENT", f"修改总结最长 {MESSAGE_MAX_LENGTH} 字符。")

        root = self.binding_store.prepare_root(path)
        binding = self.binding_store.load(root)
        app_detail = self.client.get_app(binding.slug)
        self._assert_pushable(app_detail)
        git_config = self.client.get_git_config(binding.slug)
        binding = self._refresh_binding(binding, app_detail=app_detail, git_config=git_config)
        self.binding_store.save(root, binding)
        binding, credential_result = self._ensure_credential(root, binding, git_config)

        git_result = self.git_service.push_all(
            root,
            repo_url=binding.repo_url,
            message=summary,
        )
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
            **git_result,
            **publish_result,
            "version": (
                final_detail.get("current_version")
                or final_detail.get("display_version")
                or final_detail.get("version")
            ),
            "url": final_detail.get("url"),
            "message": publish_result.get("message")
            or "站点源码已推送，AppHub 发布完成。",
        }

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
            repo_url=repo_url,
            git_username=_optional_text(git_config.get("username")) or binding.git_username,
            owner_user_id=_optional_text(app_detail.get("owner_user_id"))
            or binding.owner_user_id,
            owner_email=_optional_text(
                app_detail.get("owner_email") or app_detail.get("owner")
            )
            or binding.owner_email,
        )

    def _assert_pushable(self, app_detail: dict[str, Any]) -> None:
        status = _optional_text(app_detail.get("status"))
        if status in {"disabled", "archived", "deleted"}:
            raise AppProjectError(
                "APP-STATE",
                f"应用当前状态为 {status}，不能推送发布。",
                fix_hint="请先在 AppHub 处理应用生命周期状态。",
            )

    def _binding_result(self, root: Path, binding: SiteBinding, message: str) -> dict:
        return {
            "app_id": binding.app_id,
            "site_name": binding.site_name,
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
