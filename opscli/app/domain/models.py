"""AppHub 发布链领域数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppManifest:
    """通过本地同构校验后的 app.yaml。"""

    api_version: str
    name: str
    runtime: str
    python: str
    entrypoint: str
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class AppProject:
    """待发布项目及其 manifest。"""

    root: Path
    manifest_path: Path
    manifest: AppManifest

    @property
    def slug(self) -> str:
        """返回应用唯一 slug。"""
        return self.manifest.name


@dataclass(frozen=True)
class GitConfig:
    """AppHub 返回的 Git 接入信息。"""

    repo_url: str
    username: str | None
    bound: bool
    token_hint: str | None = None
    issued_at: str | None = None


@dataclass(frozen=True)
class PublishSession:
    """断线续订所需的最小本地句柄。"""

    release_id: int
    last_seq: int
    slug: str
    commit_sha: str
    started_at: str

    def to_dict(self) -> dict:
        """转换为 JSON 可序列化结构。"""
        return asdict(self)


@dataclass(frozen=True)
class SSEFrame:
    """解析后的单个 SSE 帧。"""

    event: str
    data: dict[str, Any]


@dataclass
class PublishResult:
    """publish 命令的稳定结果。"""

    slug: str
    release_id: int | None
    status: str
    commit_sha: str
    version: str | None = None
    tag: str | None = None
    url: str | None = None
    message: str | None = None
    noop: bool = False
    error_code: str | None = None
    fix_hint: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict:
        """转换为稳定输出结构。"""
        return asdict(self)

