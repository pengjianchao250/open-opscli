"""AppHub 创建请求与本地应用绑定模型。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from opscli.app.domain.constants import BINDING_SCHEMA_VERSION, GIT_DEFAULT_BRANCH
from opscli.app.domain.exceptions import AppProjectError

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_SLUG_VALID_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")


def validate_app_id(value: Any, *, code: str = "APP-BINDING-INVALID") -> str:
    """校验公开应用 ID，保留大小写且不把名称或数字转换为身份。"""
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9]{5}", value) is None:
        raise AppProjectError(code, "应用 app_id 必须是五位大小写字母数字，请按应用 ID 重新绑定。")
    return value


@dataclass(frozen=True)
class AppCreateRequest:
    """AppHub 创建应用请求。"""

    name: str
    title: str
    description: str = ""
    contact: str | None = None

    @classmethod
    def from_app_name(
        cls,
        app_name: str,
        *,
        slug: str | None = None,
    ) -> "AppCreateRequest":
        title = app_name.strip()
        if not title:
            raise AppProjectError("APP-ARGUMENT", "应用名称不能为空。")
        normalized_slug = slugify_site_name(slug) if slug else slugify_site_name(title)
        return cls(name=normalized_slug, title=title)

    @classmethod
    def from_site_name(cls, site_name: str) -> "AppCreateRequest":
        return cls.from_app_name(site_name)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "apiVersion": "apps.aukeys/v1",
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "resources": {"cpu": None, "memory": None},
            "database": {"kind": "sqlite", "path": "/data/app.db"},
            "opscli": {"auth_mode": "viewer", "datasets": []},
            "llm": {"enabled": False},
            "access": {"visibility": "members"},
        }
        # contact 未填写时省略字段，兼容尚未接收该可选字段的 AppHub 服务版本。
        if self.contact is not None:
            payload["contact"] = self.contact
        return payload


@dataclass(frozen=True)
class SiteBinding:
    """本地目录与 AppHub 应用、独立源码仓库的非敏感绑定。"""

    app_id: str
    app_name: str
    slug: str
    repo_url: str
    default_branch: str = GIT_DEFAULT_BRANCH
    git_username: str | None = None
    owner_user_id: str | None = None
    owner_email: str | None = None
    created_at: str | None = None
    schema_version: int = BINDING_SCHEMA_VERSION
    # 控制面环境参与目录绑定，防止两个环境偶然生成相同公开 ID。
    apphub_url: str | None = None

    @property
    def site_name(self) -> str:
        """兼容旧 SDK 字段名。"""
        return self.app_name

    @classmethod
    def from_create_response(
        cls,
        app_name: str,
        payload: dict[str, Any],
    ) -> "SiteBinding":
        return cls._from_remote_payload(app_name, payload)

    @classmethod
    def from_app_detail(
        cls,
        app_name: str,
        payload: dict[str, Any],
    ) -> "SiteBinding":
        return cls._from_remote_payload(app_name, payload)

    @classmethod
    def _from_remote_payload(
        cls,
        app_name: str,
        payload: dict[str, Any],
    ) -> "SiteBinding":
        """只接受服务端明确返回的公开 ID，不用 slug 补齐身份。"""
        slug = _required_text(payload, "slug")
        repo_url = _required_text(payload, "repo_url")
        app_id = validate_app_id(payload.get("app_id"), code="APPHUB-PROTOCOL")
        return cls(
            app_id=app_id,
            app_name=str(payload.get("title") or payload.get("site_name") or app_name),
            slug=slug,
            repo_url=repo_url,
            default_branch=str(payload.get("default_branch") or GIT_DEFAULT_BRANCH),
            git_username=_optional_text(
                payload.get("git_username")
                or _nested_value(payload, "git_credential", "username")
            ),
            owner_user_id=_optional_text(payload.get("owner_user_id")),
            owner_email=_optional_text(payload.get("owner_email") or payload.get("owner")),
            created_at=_optional_text(payload.get("created_at")),
            apphub_url=_optional_text(payload.get("apphub_url")),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SiteBinding":
        """读取有明确应用 ID 的本地绑定，旧名称绑定需显式恢复。"""
        try:
            source_version = int(payload.get("schema_version", 1))
        except (TypeError, ValueError) as exc:
            raise AppProjectError("APP-BINDING-INVALID", "应用绑定版本格式错误。") from exc
        if source_version not in (1, 2, BINDING_SCHEMA_VERSION):
            raise AppProjectError(
                "APP-BINDING-VERSION",
                f"不支持的应用绑定版本：{source_version}",
            )
        try:
            app_id = validate_app_id(payload.get("app_id"))
            app_name = _optional_text(
                payload.get("app_name") or payload.get("site_name")
            )
            slug = _optional_text(payload.get("slug"))
            repo_url = _optional_text(payload.get("repo_url"))
            if app_name is None or slug is None or repo_url is None:
                raise ValueError("missing required binding fields")
            binding = cls(
                schema_version=source_version,
                app_id=app_id,
                app_name=app_name,
                slug=slug,
                repo_url=repo_url,
                default_branch=str(payload.get("default_branch") or GIT_DEFAULT_BRANCH),
                git_username=_optional_text(payload.get("git_username")),
                owner_user_id=_optional_text(payload.get("owner_user_id")),
                owner_email=_optional_text(
                    payload.get("owner_email") or payload.get("created_by")
                ),
                created_at=_optional_text(payload.get("created_at")),
                apphub_url=_optional_text(payload.get("apphub_url")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AppProjectError(
                "APP-BINDING-INVALID",
                "应用绑定文件字段不完整或格式错误。",
            ) from exc
        if not _SLUG_VALID_RE.fullmatch(binding.slug):
            raise AppProjectError("APP-BINDING-INVALID", "应用绑定 slug 格式错误。")
        return binding

    def migrated(self, **changes: Any) -> "SiteBinding":
        return replace(self, schema_version=BINDING_SCHEMA_VERSION, **changes)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = BINDING_SCHEMA_VERSION
        return payload


def slugify_site_name(value: str) -> str:
    """把名称稳定转换为 AppHub 接受的 slug。"""
    normalized = _SLUG_INVALID_RE.sub("-", value.strip().lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:12]
        normalized = f"app-{digest}"
    normalized = normalized[:64].rstrip("-")
    if len(normalized) < 3:
        normalized = f"app-{normalized}".rstrip("-")
    if not _SLUG_VALID_RE.fullmatch(normalized):
        raise AppProjectError("APP-SLUG-INVALID", f"无法生成合法应用 slug：{normalized}")
    return normalized


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise AppProjectError("APPHUB-PROTOCOL", f"AppHub 响应缺少字段：{key}")
    return value


def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _nested_value(payload: dict[str, Any], parent: str, key: str) -> Any:
    nested = payload.get(parent)
    return nested.get(key) if isinstance(nested, dict) else None
