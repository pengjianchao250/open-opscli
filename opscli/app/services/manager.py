"""create、init、push 三命令业务编排。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from opscli.app.domain.constants import (
    BINDING_SCHEMA_VERSION,
    MCP_REST_API_BASE_URL_BY_APPHUB_ORIGIN,
    MCP_REST_API_BASE_URL_ENV_KEY,
    MESSAGE_MAX_LENGTH,
)
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
from opscli.app.services.migration_contract import (
    inspect_migration_frontend_build,
    inspect_migration_public_paths,
    inspect_migration_runtime_assets,
)
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

    def create_app(
        self,
        app_name: str,
        *,
        path: str | Path | None = None,
        include_default_database: bool = True,
    ) -> dict:
        """创建并绑定应用，不消费或保存创建响应中的 Git 凭据。"""
        request = AppCreateRequest.from_app_name(
            app_name,
            include_default_database=include_default_database,
        )
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

    def bind_app(self, path: str | Path, *, app_id: str) -> dict:
        """只保存明确指定的 AppHub 应用绑定，不初始化 Git 或推送源码。"""
        root = self.binding_store.prepare_root(path)
        binding = self._ensure_binding(root, app_id=app_id)
        detail = self.client.get_app(binding.app_id)
        self._verify_detail(binding, detail)
        binding = binding.migrated(
            apphub_url=self.client.api_base_url,
            app_name=_optional_text(detail.get("title")) or binding.app_name,
            owner_user_id=_optional_text(detail.get("owner_user_id")) or binding.owner_user_id,
            owner_email=_optional_text(detail.get("owner_email") or detail.get("owner"))
            or binding.owner_email,
        )
        self.binding_store.save(root, binding)
        self.manifest_store.sync_identity(root, binding)
        return self._binding_result(root, binding, "应用绑定已保存；尚未初始化仓库或推送源码。")

    def init_git(
        self,
        path: str | Path = ".",
        *,
        app_slug: str | None = None,
        app_id: str | None = None,
    ) -> dict:
        """初始化已绑定应用，或通过明确的公开 ID 恢复已有应用。"""
        git_environment = self._ensure_git_environment()
        root = self.binding_store.prepare_root(path)
        binding, credential_result, git_result, runtime_env_result = (
            self._prepare_repository(
                root,
                app_slug=app_slug,
                app_id=app_id,
            )
        )
        return {
            **self._binding_result(
                root,
                binding,
                f"Git 已绑定应用仓库并基于远端 {binding.default_branch} 初始化。",
            ),
            **credential_result,
            **git_result,
            **runtime_env_result,
            "git_environment": git_environment,
        }

    def push(self, path: str | Path = ".", *, message: str) -> dict:
        summary = self._validate_message(message, command="push")
        git_environment = self._ensure_git_environment()
        root = self.binding_store.prepare_root(path)
        migration_project = self._is_migration_project(root)
        if migration_project:
            self._validate_migration_push(root)
        binding, credential_result, git_init_result, runtime_env_result = (
            self._prepare_repository(
                root,
                manifest_policy="validate",
            )
        )
        git_result = self.git_service.push_all(
            root,
            repo_url=binding.repo_url,
            message=summary,
            branch=binding.default_branch,
        )
        message_text = (
            "推送成功；运营系统将自动部署并发布当前站点，您可以前往运营系统查看发布状态、或进行站点权限设置。"
            if git_result.get("pushed")
            else f"远端 {binding.default_branch} 已是最新源码，无需重复推送。"
        )
        return {
            **self._binding_result(root, binding, ""),
            **credential_result,
            **git_init_result,
            **runtime_env_result,
            **git_result,
            "git_environment": git_environment,
            "message": message_text,
        }

    def _ensure_git_environment(self) -> dict:
        ensure = getattr(self.git_service, "ensure_environment", None)
        if ensure is None:
            return {}
        return ensure(install=True)

    def _prepare_repository(
        self,
        root: Path,
        *,
        app_slug: str | None = None,
        app_id: str | None = None,
        manifest_policy: Literal["sync", "validate"] = "sync",
    ) -> tuple[SiteBinding, dict[str, Any], dict[str, Any], dict[str, Any]]:
        root.mkdir(parents=True, exist_ok=True)
        binding = self._ensure_binding(root, app_slug=app_slug, app_id=app_id)
        if manifest_policy == "validate":
            manifest = self.manifest_store.validate_identity(root, binding, required=True)
            self.manifest_store.validate_production_assets(root, manifest)
        app_detail = self.client.get_app(binding.app_id)
        self._verify_detail(binding, app_detail)
        git_config = self.client.get_git_config(binding.app_id)
        binding = self._refresh_binding(
            binding,
            app_detail=app_detail,
            git_config=git_config,
        )
        runtime_env_result = self._ensure_runtime_environment(binding.app_id)
        if not self.git_service.origin_matches(root, repo_url=binding.repo_url):
            self.client.preflight_git_bind(binding.app_id)
        binding, credential_result = self._ensure_credential(
            root,
            binding,
            git_config,
        )
        self.binding_store.save(root, binding)
        if manifest_policy == "sync":
            self.manifest_store.sync_identity(root, binding)
        git_result = self.git_service.initialize(
            root,
            repo_url=binding.repo_url,
            branch=binding.default_branch,
            credential_username=binding.git_username,
        )
        return binding, credential_result, git_result, runtime_env_result

    def _is_migration_project(self, root: Path) -> bool:
        marker = root / ".opscli" / "project.json"
        if not marker.is_file():
            return False
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppProjectError("APP-MIGRATION-MARKER", f"迁移项目标识读取失败：{marker}") from exc
        return isinstance(payload, dict) and payload.get("origin_type") == "migration_copy"

    def _validate_migration_push(self, root: Path) -> None:
        marker_path = root / ".opscli" / "project.json"
        migration = _read_json_object(marker_path, "APP-MIGRATION-MARKER")
        source_value = migration.get("source_root")
        if not isinstance(source_value, str) or not source_value.strip():
            raise AppProjectError("APP-MIGRATION-PATH", "迁移项目缺少有效的源目录标识。")
        source_root = Path(source_value).expanduser().resolve()
        target_root = root.resolve()
        if (
            source_root == target_root
            or source_root in target_root.parents
            or target_root in source_root.parents
        ):
            raise AppProjectError(
                "APP-MIGRATION-PATH",
                "迁移项目源目录和目标目录无效或互相包含。",
            )
        for relative in (
            Path("copy-manifest.json"),
            Path("startup-manifest.json"),
            Path("adaptation-manifest.json"),
            Path("migration.json"),
        ):
            state_file = (
                root
                / ".opscli"
                / "migration"
                / str(migration.get("migration_id"))
                / relative
            )
            if not state_file.is_file():
                raise AppProjectError(
                    "APP-MIGRATION-GATE",
                    f"迁移项目缺少必要状态文件：{relative.name}",
                    fix_hint="执行 opscli app migrate verify 或重新扫描迁移项目。",
                )
        migration_dir = root / ".opscli" / "migration" / str(migration.get("migration_id"))
        state = _read_json_object(migration_dir / "migration.json", "APP-MIGRATION-STATE")
        adaptation = _read_json_object(
            migration_dir / "adaptation-manifest.json", "APP-MIGRATION-STATE"
        )
        if not state.get("delivery_ready") or adaptation.get("status") != "ready":
            raise AppProjectError(
                "APP-MIGRATION-GATE",
                "迁移适配尚未达到交付条件。",
                fix_hint="执行 opscli app migrate resume 和 verify，完成启动与适配检查后再推送。",
                detail={
                    "phase": state.get("phase"),
                    "adaptation_status": adaptation.get("status"),
                    "delivery_ready": bool(state.get("delivery_ready")),
                },
            )
        frontend_build = inspect_migration_frontend_build(root)
        if not frontend_build["ready"]:
            raise AppProjectError(
                "APP-MIGRATION-BUILD-CONTRACT",
                "迁移项目的前端生产构建配置与 packageManager 声明不一致。",
                fix_hint=(
                    "让 Corepack 在 frontend/package.json 所在目录解析 pnpm 版本后再构建；"
                    "不要使用 pmOnFail=ignore 绕过版本校验。"
                ),
                detail=frontend_build,
            )
        public_paths = inspect_migration_public_paths(root)
        if not public_paths["ready"]:
            raise AppProjectError(
                "APP-MIGRATION-PUBLIC-PATH",
                "迁移项目的浏览器资源或 API 使用根绝对 URL，无法适配 AppHub 动态访问前缀。",
                fix_hint=(
                    "将 href、src、CSS url() 和浏览器请求改为相对 URL，"
                    "重新执行 opscli app migrate scan-startup、resume 和 verify。"
                ),
                detail=public_paths,
            )
        runtime_assets = inspect_migration_runtime_assets(root)
        if not runtime_assets["ready"]:
            raise AppProjectError(
                "APP-MIGRATION-RUNTIME-ASSET",
                "迁移项目引用了公开数据快照，但快照不会进入最终运行镜像。",
                fix_hint=(
                    "让 Dockerfile 最终运行阶段复制 public，并确保 .gitignore 和 "
                    ".dockerignore 不会排除 public 下的数据快照后再推送。"
                ),
                detail=runtime_assets,
            )
        tracked = self.git_service.runner.run(
            root,
            [
                "ls-files",
                "--",
                ".env",
                ".env.*",
                "*.db",
                "*.sqlite",
                "*.sqlite3",
                "data",
                ":(exclude).env.example",
            ],
            check=False,
        )
        if tracked.stdout:
            raise AppProjectError(
                "APP-MIGRATION-SENSITIVE",
                "迁移项目存在默认禁止推送的本地敏感或运行时文件。",
                fix_hint="将敏感文件从 Git 索引移除后再推送。",
                detail={"tracked": tracked.stdout.splitlines()},
            )

    def _ensure_runtime_environment(self, app_id: str) -> dict[str, Any]:
        expected_value = self._expected_mcp_rest_api_base_url()
        payload = self.client.get_app_env(app_id)
        current_env = _custom_env(payload)
        existing_value = current_env.get(MCP_REST_API_BASE_URL_ENV_KEY)
        if existing_value is not None and existing_value.strip():
            status = (
                "existing"
                if existing_value == expected_value
                else "mismatch_preserved"
            )
            return {
                "runtime_env_key": MCP_REST_API_BASE_URL_ENV_KEY,
                "runtime_env_value": existing_value,
                "runtime_env_expected_value": expected_value,
                "runtime_env_status": status,
                "runtime_env_updated": False,
            }

        updated_env = {
            **current_env,
            MCP_REST_API_BASE_URL_ENV_KEY: expected_value,
        }
        saved = self.client.update_app_env(app_id, updated_env)
        saved_env = _custom_env(saved) if "env" in saved else None
        if saved_env is None:
            saved_env = _custom_env(self.client.get_app_env(app_id))
        if saved_env.get(MCP_REST_API_BASE_URL_ENV_KEY) != expected_value:
            raise AppProjectError(
                "APPHUB-PROTOCOL",
                f"AppHub 未保存环境变量 {MCP_REST_API_BASE_URL_ENV_KEY}。",
            )
        for key, value in current_env.items():
            if saved_env.get(key) != value:
                raise AppProjectError(
                    "APPHUB-PROTOCOL",
                    f"AppHub 保存环境变量时未保留已有键：{key}",
                )
        return {
            "runtime_env_key": MCP_REST_API_BASE_URL_ENV_KEY,
            "runtime_env_value": expected_value,
            "runtime_env_expected_value": expected_value,
            "runtime_env_status": "configured",
            "runtime_env_updated": True,
        }

    def _expected_mcp_rest_api_base_url(self) -> str:
        origin = self.client.control_plane_url.rstrip("/").lower()
        expected = MCP_REST_API_BASE_URL_BY_APPHUB_ORIGIN.get(origin)
        if expected is None:
            supported = ", ".join(sorted(MCP_REST_API_BASE_URL_BY_APPHUB_ORIGIN))
            raise AppProjectError(
                "APPHUB-ENVIRONMENT-UNSUPPORTED",
                f"当前 AppHub 环境未配置 MCP REST 地址：{self.client.control_plane_url}",
                fix_hint=f"切换到受支持的 AppHub 环境后重试：{supported}",
            )
        return expected

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
    ) -> tuple[SiteBinding, dict[str, Any]]:
        """验证本机凭据，认证失败时按平台状态自动签发或轮换。"""
        username = _optional_text(git_config.get("username")) or binding.git_username
        bound = bool(git_config.get("bound"))
        try:
            self.git_service.probe_remote_branch(
                root,
                repo_url=binding.repo_url,
                branch=binding.default_branch,
                repository_not_found_is_auth=True,
            )
        except AppGitError as exc:
            if exc.code != "GIT-002":
                raise
        else:
            return binding.migrated(git_username=username), {
                "credential_refreshed": False,
            }

        issued = self.client.issue_git_credential(rotate=bound)
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
            self.credential_store.erase_credential(
                root,
                repo_url=binding.repo_url,
                username=username,
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
        return binding, {"credential_refreshed": True}

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


def _read_json_object(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppProjectError(code, f"迁移项目标识读取失败：{path}") from exc
    if not isinstance(payload, dict):
        raise AppProjectError(code, f"迁移项目标识必须是 JSON 对象：{path}")
    return payload


def _custom_env(payload: dict[str, Any]) -> dict[str, str]:
    raw_env = payload.get("env")
    if not isinstance(raw_env, dict):
        raise AppProjectError("APPHUB-PROTOCOL", "AppHub 环境变量响应缺少 env 对象。")
    env: dict[str, str] = {}
    for key, value in raw_env.items():
        if not isinstance(key, str) or not key:
            raise AppProjectError("APPHUB-PROTOCOL", "AppHub 返回了无效的环境变量键。")
        if not isinstance(value, str):
            raise AppProjectError(
                "APPHUB-PROTOCOL",
                f"AppHub 环境变量 {key} 的值必须是字符串。",
            )
        env[key] = value
    return env
