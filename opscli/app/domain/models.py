"""AppHub 请求模型与本地站点绑定模型。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from opscli.app.domain.constants import (
    APP_DEFAULT_ENTRYPOINT,
    APP_DEFAULT_PYTHON,
    APP_DEFAULT_RUNTIME,
    APP_TEMPLATE_BRANCH_DEFAULT,
    APP_TEMPLATE_REPO_DEFAULT,
    BINDING_SCHEMA_VERSION,
    GIT_DEFAULT_BRANCH,
)
from opscli.app.domain.exceptions import AppProjectError

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_SLUG_VALID_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")


@dataclass(frozen=True)
class AppYaml:
    """第一阶段 create 使用的完整 AppYaml 默认配置。"""

    name: str
    title: str
    description: str = ""
    contact: str | None = None
    runtime: str = APP_DEFAULT_RUNTIME
    python: str = APP_DEFAULT_PYTHON
    entrypoint: str = APP_DEFAULT_ENTRYPOINT

    @classmethod
    def from_site_name(cls, site_name: str) -> "AppYaml":
        title = site_name.strip()
        if not title:
            raise AppProjectError("APP-ARGUMENT", "站点名称不能为空。")
        return cls(name=slugify_site_name(title), title=title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": "apps.aukeys/v1",
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "contact": self.contact,
            "runtime": self.runtime,
            "python": self.python,
            "entrypoint": self.entrypoint,
            "resources": {"cpu": None, "memory": None},
            "services": {"sqlite": False},
            "opscli": {"auth_mode": "viewer", "datasets": []},
            "llm": {"enabled": False},
            "access": {"visibility": "members"},
        }


@dataclass(frozen=True)
class SiteBinding:
    """本地目录与 AppHub 应用、独立源码仓库的非敏感绑定。"""

    app_id: str
    site_name: str
    slug: str
    repo_url: str
    default_branch: str = GIT_DEFAULT_BRANCH
    git_username: str | None = None
    owner_user_id: str | None = None
    owner_email: str | None = None
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
        slug = _required_text(payload, "slug")
        repo_url = _required_text(payload, "repo_url")
        app_id = _optional_text(
            payload.get("app_id") or payload.get("id") or payload.get("site_id")
        ) or slug
        return cls(
            app_id=app_id,
            site_name=str(payload.get("site_name") or payload.get("title") or site_name),
            slug=slug,
            repo_url=repo_url,
            git_username=_optional_text(
                payload.get("git_username")
                or _nested_value(payload, "git_credential", "username")
            ),
            owner_user_id=_optional_text(payload.get("owner_user_id")),
            owner_email=_optional_text(payload.get("owner_email") or payload.get("owner")),
            created_at=_optional_text(payload.get("created_at")),
            template_repo_url=template_repo_url,
            template_branch=template_branch,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SiteBinding":
        try:
            source_version = int(payload.get("schema_version", 1))
        except (TypeError, ValueError) as exc:
            raise AppProjectError("APP-BINDING-INVALID", "站点绑定版本格式错误。") from exc
        if source_version not in (1, BINDING_SCHEMA_VERSION):
            raise AppProjectError(
                "APP-BINDING-VERSION",
                f"不支持的站点绑定版本：{source_version}",
            )
        try:
            app_id = payload.get("app_id") or payload.get("site_id")
            binding = cls(
                schema_version=source_version,
                app_id=str(app_id),
                site_name=str(payload["site_name"]),
                slug=str(payload["slug"]),
                repo_url=str(payload["repo_url"]),
                default_branch=str(payload.get("default_branch") or GIT_DEFAULT_BRANCH),
                git_username=_optional_text(payload.get("git_username")),
                owner_user_id=_optional_text(payload.get("owner_user_id")),
                owner_email=_optional_text(
                    payload.get("owner_email") or payload.get("created_by")
                ),
                created_at=_optional_text(payload.get("created_at")),
                template_repo_url=str(
                    payload.get("template_repo_url") or APP_TEMPLATE_REPO_DEFAULT
                ),
                template_branch=str(
                    payload.get("template_branch") or APP_TEMPLATE_BRANCH_DEFAULT
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AppProjectError(
                "APP-BINDING-INVALID",
                "站点绑定文件字段不完整或格式错误。",
            ) from exc
        if not binding.app_id or binding.app_id == "None":
            raise AppProjectError("APP-BINDING-INVALID", "站点绑定缺少 app_id/site_id。")
        return binding

    def migrated(self, **changes: Any) -> "SiteBinding":
        return replace(self, schema_version=BINDING_SCHEMA_VERSION, **changes)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = BINDING_SCHEMA_VERSION
        return payload


def slugify_site_name(value: str) -> str:
    """把显示名称稳定转换为 AppHub 接受的 slug。"""
    normalized = _SLUG_INVALID_RE.sub("-", value.strip().lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:12]
        normalized = f"app-{digest}"
    normalized = normalized[:64].rstrip("-")
    if len(normalized) < 3:
        normalized = f"app-{normalized}".rstrip("-")
    if not _SLUG_VALID_RE.fullmatch(normalized):
        raise AppProjectError("APP-SLUG-INVALID", f"无法生成合法站点 slug：{normalized}")
    return normalized


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise AppProjectError(
            "APPHUB-PROTOCOL",
            f"AppHub 响应缺少字段：{key}",
        )
    return value


def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _nested_value(payload: dict[str, Any], parent: str, key: str) -> Any:
    nested = payload.get(parent)
    return nested.get(key) if isinstance(nested, dict) else None
