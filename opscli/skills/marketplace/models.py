"""Skill 技能广场数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillCategoryInfo:
    id: int
    name: str
    slug: str
    skill_count: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "SkillCategoryInfo":
        return cls(
            id=d.get("id", 0),
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            skill_count=d.get("skill_count", 0),
        )


@dataclass
class SkillItem:
    id: int
    identifier: str          # pengjianchao@ops-auth
    username: str
    skill_name: str
    title: str
    description: str
    latest_version: str
    oss_url: str
    install_count: int
    usage_count: int
    favorite_count: int
    rating_avg: float
    rating_count: int
    status: int
    is_official: bool
    category: SkillCategoryInfo | None = None
    tags: list[str] = field(default_factory=list)
    is_favorited: bool = False
    user_rating: dict | None = None
    created_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SkillItem":
        cat = d.get("category")
        return cls(
            id=d.get("id", 0),
            identifier=d.get("identifier", ""),
            username=d.get("username", ""),
            skill_name=d.get("skill_name", ""),
            title=d.get("title", ""),
            description=d.get("description") or "",
            latest_version=d.get("latest_version", ""),
            oss_url=d.get("oss_url", ""),
            install_count=d.get("install_count", 0),
            usage_count=d.get("usage_count", 0),
            favorite_count=d.get("favorite_count", 0),
            rating_avg=float(d.get("rating_avg", 0)),
            rating_count=d.get("rating_count", 0),
            status=d.get("status", 1),
            is_official=bool(d.get("is_official", False)),
            category=SkillCategoryInfo.from_dict(cat) if isinstance(cat, dict) else None,
            tags=d.get("tags") or [],
            is_favorited=bool(d.get("is_favorited", False)),
            user_rating=d.get("user_rating"),
            created_at=d.get("created_at", ""),
        )

    @property
    def short_desc(self) -> str:
        """截断简介，最多 30 字符。"""
        if not self.description:
            return ""
        return self.description[:30] + ("..." if len(self.description) > 30 else "")

    @property
    def rating_stars(self) -> str:
        """将评分均值转为星级字符串，如 ★4.8。"""
        if self.rating_count == 0:
            return "-"
        return f"★{self.rating_avg:.1f}"


@dataclass
class SkillVersionInfo:
    id: int
    skill_id: int
    version: str
    changelog: str
    oss_url: str
    file_size: int | None
    file_hash: str | None
    created_by: int
    created_at: str

    @classmethod
    def from_dict(cls, d: dict) -> "SkillVersionInfo":
        return cls(
            id=d.get("id", 0),
            skill_id=d.get("skill_id", 0),
            version=d.get("version", ""),
            changelog=d.get("changelog") or "",
            oss_url=d.get("oss_url", ""),
            file_size=d.get("file_size"),
            file_hash=d.get("file_hash"),
            created_by=d.get("created_by", 0),
            created_at=d.get("created_at", ""),
        )


@dataclass
class MarketplaceListResult:
    items: list[SkillItem]
    total: int
    page: int
    limit: int

    @property
    def total_pages(self) -> int:
        if self.limit <= 0:
            return 1
        return max(1, (self.total + self.limit - 1) // self.limit)
