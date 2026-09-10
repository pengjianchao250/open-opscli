"""create、init、push 三命令业务编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.app.domain.constants import BINDING_SCHEMA_VERSION, MESSAGE_MAX_LENGTH
from opscli.app.domain.exceptions import AppGitError, AppProjectError
from opscli.app.domain.models import (
    AppCreateRequest,
    SiteBinding,
    slugify_site_name,
    validate_app_id,
    validate_default_branch,
    validate_repo_url,
)
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
            binding = self._ensure_binding(root)
            if binding.slug != request.name:
                raise AppProjectError(
                    "APP-ALREADY-BOUND",
                    f"目录已绑定应用：{binding.app_name} ({binding.app_id})",
                )
            self._verify_detail(binding, self.client.get_app(binding.app_id))
            binding = binding.migrated(apphub_url=self.client.api_base_url)
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
        app_id: str | None = None,
        rotate_git_credential: bool = False,
    ) -> dict:
        """初始化已绑定应用，或通过明确的公开 ID 恢复已有应用。"""
        root = self.binding_store.prepare_root(path)
        binding, credential_result, git_result, _ = self._prepare_repository(
            root,
            app_slug=app_slug,
            app_id=app_id,
            rotate_git_credential=rotate_git_credential,
        )
        return {
            **self._binding_result(
                root,
                binding,
                f"Git 已绑定应用仓库并基于远端 {binding.default_branch} 初始化。",
            ),
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
            branch=binding.default_branch,
        )
        message_text = (
            "源码已推送到远端仓库。"
            if git_result.get("pushed")
            else f"远端 {binding.default_branch} 已是最新源码，无需重复推送。"
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
        app_id: str | None = None,
        rotate_git_credential: bool = False,
    ) -> tuple[SiteBinding, dict[str, Any], dict[str, Any], dict[str, Any]]:
        root.mkdir(parents=True, exist_ok=True)
        binding = self._ensure_binding(root, app_slug=app_slug, app_id=app_id)
        app_detail = self.client.get_app(binding.app_id)
        self._verify_detail(binding, app_detail)
        git_config = self.client.get_git_config(binding.app_id)
        binding = self._refresh_binding(
            binding,
            app_detail=app_detail,
            git_config=git_config,
        )
        if not self.git_service.origin_matches(root, repo_url=binding.repo_url):
            self.client.preflight_git_bind(binding.app_id)
        binding, credential_result = self._ensure_credential(
            root,
            binding,
            git_config,
            rotate_git_credential=rotate_git_credential,
        )
        self.binding_store.save(root, binding)
        self.manifest_store.sync_identity(root, binding)
        git_result = self.git_service.initialize(
            root,
            repo_url=binding.repo_url,
            branch=binding.default_branch,
        )
        return binding, credential_result, git_result, app_detail

    def _ensure_binding(
        self,
        root: Path,
        *,
        app_slug: str | None = None,
        app_id: str | None = None,
    ) -> SiteBinding:
        # --app 保留 slug 含义，仅作声明核对，绝不把名称当作远端身份。
        if app_id is not None:
            validate_app_id(app_id)
        if self.binding_store.is_bound(root):
            binding = self.binding_store.load(root)
            if app_id is not None and binding.app_id != app_id:
                raise AppProjectError(
                    "APP-ALREADY-BOUND",
                    f"目录已绑定应用：{binding.app_name} ({binding.app_id})",
                )
            if binding.apphub_url != self.client.api_base_url:
                raise AppProjectError(
                    "APP-BINDING-ENVIRONMENT", "此目录绑定了其他 AppHub 环境。",
                    fix_hint="切回原控制面环境；操作另一环境的应用请使用独立目录。",
                )
            if app_slug is not None and binding.slug != slugify_site_name(app_slug):
                raise AppProjectError("APP-ALREADY-BOUND", "--app 与目录绑定的 slug 不一致。")
            return binding
        if app_id is None:
            raise AppProjectError(
                "APP-NOT-BOUND", "目录未绑定应用，不能按名称自动选择或创建。",
                fix_hint="已有应用使用 opscli app init --app-id <app_id>；新应用先执行 app create。",
            )
        detail = self.client.get_app(app_id)
        binding = SiteBinding.from_app_detail(root.name, detail)
        if binding.app_id != app_id:
            raise AppProjectError("APPHUB-PROTOCOL", "AppHub 返回的 app_id 与请求不一致。")
        if app_slug is not None and binding.slug != slugify_site_name(app_slug):
            raise AppProjectError("APP-ARGUMENT", "--app 与指定 ID 的 slug 不一致。")
        return binding

    def _create_binding(
        self,
        root: Path,
        request: AppCreateRequest,
    ) -> SiteBinding:
        """保存应用基础绑定，忽略创建响应中的内联 Git 凭据。"""
        request_payload = request.to_dict()
        state = self.binding_store.prepare_creation(
            root, request_payload, scope=self.client.creation_scope(),
        )
        payload = self.client.create_app(request_payload)
        binding = SiteBinding.from_create_response(request.title, payload).migrated(
            apphub_url=self.client.api_base_url,
        )
        if binding.slug != request.name:
            raise AppProjectError("APPHUB-PROTOCOL", "AppHub 创建响应的 slug 与请求不一致。")
        self.binding_store.save(root, binding)
        self.binding_store.complete_creation(root, state, binding.app_id)
        self.manifest_store.sync_identity(root, binding)
        return binding

    def _ensure_credential(
        self,
        root: Path,
        binding: SiteBinding,
        git_config: dict[str, Any],
        *,
        rotate_git_credential: bool,
    ) -> tuple[SiteBinding, dict[str, Any]]:
        username = _optional_text(git_config.get("username")) or binding.git_username
        bound = bool(git_config.get("bound"))
        if not rotate_git_credential:
            try:
                self.git_service.probe_remote_branch(
                    root,
                    repo_url=binding.repo_url,
                    branch=binding.default_branch,
                )
            except AppGitError as exc:
                if exc.code != "GIT-002":
                    raise
                if bound:
                    raise AppGitError(
                        "GIT-CREDENTIAL-ROTATION-REQUIRED",
                        "平台已有 Git 凭据，但本机凭据缺失或失效，已停止自动轮换。",
                        fix_hint=(
                            "确认其他机器旧凭据可以失效后，执行 "
                            "opscli app init --rotate-git-credential。"
                        ),
                    ) from exc
            else:
                return binding.migrated(git_username=username), {
                    "credential_refreshed": False,
                    "credential_rotated": False,
                }

        rotate = bound and rotate_git_credential
        issued = self.client.issue_git_credential(rotate=rotate)
        token = _optional_text(issued.get("token"))
        issued_username = _optional_text(issued.get("username")) or username
        if token is None or issued_username is None:
            raise AppGitError("GIT-002", "AppHub 签发的 Git 凭据不完整。")
        try:
            self.git_service.probe_remote_branch_with_basic_auth(
                root,
                repo_url=binding.repo_url,
                username=issued_username,
                token=token,
                branch=binding.default_branch,
            )
            self.credential_store.save_credential(
                root,
                repo_url=binding.repo_url,
                username=issued_username,
                token=token,
            )
        finally:
            issued.clear()
            token = ""
        binding = binding.migrated(git_username=issued_username)
        return binding, {"credential_refreshed": True, "credential_rotated": rotate}

    def _refresh_binding(
        self,
        binding: SiteBinding,
        *,
        app_detail: dict[str, Any],
        git_config: dict[str, Any],
    ) -> SiteBinding:
        repo_url = validate_repo_url(git_config.get("repo_url"), code="APPHUB-PROTOCOL")
        detail_repo_url = app_detail.get("repo_url")
        if detail_repo_url is not None and validate_repo_url(
            detail_repo_url, code="APPHUB-PROTOCOL"
        ) != repo_url:
            raise AppProjectError("APPHUB-PROTOCOL", "应用详情和 Git 配置的 repo_url 不一致。")
        # Git 配置同样必须明确标识应用，不能接受缺 ID 的旧响应。
        git_app_id = validate_app_id(git_config.get("app_id"), code="APPHUB-PROTOCOL")
        if git_app_id != binding.app_id:
            raise AppProjectError("APPHUB-PROTOCOL", "Git 配置的 app_id 与绑定不一致。")
        default_branch = validate_default_branch(
            git_config.get("default_branch") or app_detail.get("default_branch") or binding.default_branch,
            code="APPHUB-PROTOCOL",
        )
        return binding.migrated(
            apphub_url=self.client.api_base_url,
            app_name=_optional_text(app_detail.get("title")) or binding.app_name,
            repo_url=repo_url,
            default_branch=default_branch,
            git_username=_optional_text(git_config.get("username")) or binding.git_username,
            owner_user_id=_optional_text(app_detail.get("owner_user_id"))
            or binding.owner_user_id,
            owner_email=_optional_text(
                app_detail.get("owner_email") or app_detail.get("owner")
            )
            or binding.owner_email,
        )

    def _verify_detail(self, binding: SiteBinding, detail: dict[str, Any]) -> None:
        """校验身份后才修改本地声明、凭据或 Git，防止串用同名应用。"""
        remote_id = validate_app_id(detail.get("app_id"), code="APPHUB-PROTOCOL")
        if remote_id != binding.app_id or detail.get("slug") != binding.slug:
            raise AppProjectError("APPHUB-PROTOCOL", "AppHub 返回的应用身份与本地绑定不一致。")

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
