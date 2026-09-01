"""Codex 站点绑定数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from opscli.app.domain.constants import (
    APP_TEMPLATE_BRANCH_DEFAULT,
    APP_TEMPLATE_REPO_DEFAULT,
    BINDING_SCHEMA_VERSION,
)
from opscli.app.domain.exceptions import AppProjectError


@dataclass(frozen=True)
class SiteBinding:
    """本地目录与 AppHub 站点、目标源码仓库的绑定。"""

    site_id: str
    site_name: str
    slug: str
    repo_url: str
    created_by: str | None = None
    created_at: str | None = None
    template_repo_url: str = APP_TEMPLATE_REPO_DEFAULT
    template_branch: str = APP_TEMPLATE_BRANCH_DEFAULT
    schema_version: int = BINDING_SCHEMA_VERSION

    @classmethod
    def from_create_response(
        cls,
        site_name: str,
        payload: dict[str, Any],
        *,
        template_repo_url: str,
        template_branch: str,
    ) -> "SiteBinding":
        site_id = payload.get("site_id") or payload.get("id") or payload.get("project_id")
        slug = payload.get("slug")
        repo_url = payload.get("repo_url")
        missing = [
            key
            for key, value in (("site_id", site_id), ("slug", slug), ("repo_url", repo_url))
            if value in (None, "")
        ]
        if missing:
            raise AppProjectError(
                "APPHUB-PROTOCOL",
                f"创建站点响应缺少字段：{', '.join(missing)}",
                fix_hint="后续接入正式 AppHub 服务时统一响应契约。",
            )
        return cls(
            site_id=str(site_id),
            site_name=str(payload.get("site_name") or payload.get("name") or site_name),
            slug=str(slug),
            repo_url=str(repo_url),
            created_by=_optional_text(payload.get("created_by") or payload.get("creator")),
            created_at=_optional_text(payload.get("created_at")),
            template_repo_url=template_repo_url,
            template_branch=template_branch,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SiteBinding":
        try:
            binding = cls(
                schema_version=int(payload["schema_version"]),
                site_id=str(payload["site_id"]),
                site_name=str(payload["site_name"]),
                slug=str(payload["slug"]),
                repo_url=str(payload["repo_url"]),
                created_by=_optional_text(payload.get("created_by")),
                created_at=_optional_text(payload.get("created_at")),
                template_repo_url=str(payload["template_repo_url"]),
                template_branch=str(payload["template_branch"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AppProjectError("APP-BINDING-INVALID", "站点绑定文件字段不完整或格式错误。") from exc
        if binding.schema_version != BINDING_SCHEMA_VERSION:
            raise AppProjectError(
                "APP-BINDING-VERSION",
                f"不支持的站点绑定版本：{binding.schema_version}",
            )
        return binding

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
