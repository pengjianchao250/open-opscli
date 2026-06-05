"""西柚洞察服务端凭据来源。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.xiyou.config import XiyouSettings, load_settings
from opscli.xiyou.domain.exceptions import XiyouConfigError


@dataclass(frozen=True)
class XiyouCredential:
    """西柚洞察 API 凭据。"""

    authorization: str
    cookie: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的凭据摘要。"""
        return {
            "has_authorization": bool(self.authorization),
            "has_cookie": bool(self.cookie),
        }


class XiyouCredentialProvider:
    """从服务端配置读取西柚洞察凭据。"""

    def __init__(self, settings: XiyouSettings | None = None) -> None:
        self.settings = settings or load_settings()

    def get_default(self) -> XiyouCredential:
        """读取默认凭据。"""
        if not self.settings.authorization:
            raise XiyouConfigError("缺少 OPSCLI_XIYOU_AUTHORIZATION")
        return XiyouCredential(
            authorization=self.settings.authorization,
            cookie=self.settings.cookie,
        )

