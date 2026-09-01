"""`create / init / push` 三命令业务编排。"""

from __future__ import annotations

import os
from pathlib import Path

from opscli.app.domain.constants import (
    APP_TEMPLATE_BRANCH_DEFAULT,
    APP_TEMPLATE_BRANCH_ENV,
    APP_TEMPLATE_REPO_DEFAULT,
    APP_TEMPLATE_REPO_ENV,
    MESSAGE_MAX_LENGTH,
)
from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding
from opscli.app.services.binding import BindingStore
from opscli.app.services.gitops import GitService
from opscli.app.transport.client import AppHubClient


class AppManager:
    def __init__(
        self,
        *,
        client: AppHubClient | None = None,
        binding_store: BindingStore | None = None,
        git_service: GitService | None = None,
    ) -> None:
        self.client = client or AppHubClient()
        self.binding_store = binding_store or BindingStore()
        self.git_service = git_service or GitService()

    def close(self) -> None:
        self.client.close()

    def create_site(self, site_name: str, *, path: str | Path | None = None) -> dict:
        normalized_name = site_name.strip()
        if not normalized_name:
            raise AppProjectError("APP-ARGUMENT", "站点名称不能为空。")
        if path is not None:
            root = self.binding_store.prepare_root(path)
            if self.binding_store.is_bound(root):
                binding = self.binding_store.load(root)
                if binding.site_name != normalized_name:
                    raise AppProjectError(
                        "APP-ALREADY-BOUND",
                        f"目录已绑定站点：{binding.site_name} ({binding.site_id})",
                    )
                return self._binding_result(root, binding, "目录已绑定该站点，无需重复创建。")

        payload = self.client.create_site(normalized_name)
        binding = SiteBinding.from_create_response(
            normalized_name,
            payload,
            template_repo_url=os.getenv(APP_TEMPLATE_REPO_ENV) or APP_TEMPLATE_REPO_DEFAULT,
            template_branch=os.getenv(APP_TEMPLATE_BRANCH_ENV) or APP_TEMPLATE_BRANCH_DEFAULT,
        )
        root = self.binding_store.prepare_root(path or binding.slug)
        self.binding_store.save(root, binding)
        return self._binding_result(root, binding, "站点已创建并绑定本地目录。")

    def _binding_result(self, root: Path, binding: SiteBinding, message: str) -> dict:
        return {
            "site_id": binding.site_id,
            "site_name": binding.site_name,
            "slug": binding.slug,
            "path": str(root),
            "repo_url": binding.repo_url,
            "binding_file": str(root / ".opscli" / "app.json"),
            "message": message,
        }

    def init_git(self, path: str | Path = ".") -> dict:
        root = self.binding_store.prepare_root(path)
        binding = self.binding_store.load(root)
        source_exists = self.binding_store.has_source_files(root)
        result = self.git_service.initialize(
            root,
            repo_url=binding.repo_url,
            template_repo_url=binding.template_repo_url,
            template_branch=binding.template_branch,
            apply_template=not source_exists,
        )
        return {
            "site_id": binding.site_id,
            "site_name": binding.site_name,
            "slug": binding.slug,
            "path": str(root),
            "repo_url": binding.repo_url,
            **result,
            "message": (
                "Git 已初始化并获取模板。"
                if result["template_applied"]
                else "Git 已初始化；检测到已有源码，已跳过模板且未覆盖文件。"
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
        result = self.git_service.push_all(root, repo_url=binding.repo_url, message=summary)
        return {
            "site_id": binding.site_id,
            "site_name": binding.site_name,
            "slug": binding.slug,
            "path": str(root),
            "repo_url": binding.repo_url,
            **result,
            "message": "站点源码已推送。",
        }
