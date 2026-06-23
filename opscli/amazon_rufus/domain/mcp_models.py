"""Amazon Rufus MCP-facing 数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from opscli.amazon_rufus.constants import DEFAULT_RUFUS_TIMEOUT_SECONDS


@dataclass(frozen=True)
class RufusGetRequest:
    """MCP 后端获取请求，只保留允许 Agent 传入的安全字段。"""

    asin: str
    country: str
    question: str | None = None
    questions: list[str] | None = None
    skills_dir: str | None = None
    timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS

    def to_backend_kwargs(self) -> dict[str, Any]:
        """转换为 RufusManager.get_backend 参数。"""
        return {
            "asin": self.asin,
            "country": self.country,
            "question": self.question,
            "questions": self.questions,
            "skills_dir": self.skills_dir,
            "timeout_seconds": self.timeout_seconds,
            "include_upload_payload": False,
        }


@dataclass(frozen=True)
class RufusWatchLoginRequest:
    """MCP 登录采集请求，不暴露 cookie、headers 或 storage_state。"""

    asin: str
    country: str
    timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS
    chrome_path: str | None = None
    launch_if_needed: bool = True
    close_browser: bool = True

    def to_manager_kwargs(self) -> dict[str, Any]:
        """转换为 RufusManager.watch_login 参数。"""
        return asdict(self)


@dataclass(frozen=True)
class RufusRemoteConsentRequest:
    """MCP 远程授权偏好请求。"""

    country: str
    allowed: bool | None = None


@dataclass(frozen=True)
class RufusMcpResult:
    """MCP-safe 结果包装，集中表达可返回字段。"""

    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为 MCP Tool 可直接返回的数据。"""
        return dict(self.payload)
