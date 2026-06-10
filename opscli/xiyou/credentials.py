"""西柚洞察服务端凭据来源。"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.xiyou.config import XiyouSettings, load_settings
from opscli.xiyou.domain.exceptions import XiyouConfigError


@dataclass(frozen=True)
class XiyouCredential:
    """西柚洞察 API 凭据。"""

    authorization: str
    cookie: str | None = None
    source: str | None = None
    operator: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    version: Any | None = None
    headers: dict[str, str] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含敏感字段的凭据摘要。"""
        return {
            "has_authorization": bool(self.authorization),
            "has_cookie": bool(self.cookie),
            "has_headers": bool(self.headers),
            "source": self.source,
            "operator": self.operator,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "version": self.version,
        }


class XiyouCredentialStore:
    """读写西柚洞察本地补登凭据。"""

    def __init__(self, path: str | Path | None = None) -> None:
        settings = load_settings()
        self.path = Path(path or settings.credential_path).expanduser()

    def load(self) -> XiyouCredential | None:
        """读取本地 credential.json，不存在时返回 None。"""
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise XiyouConfigError(f"西柚 credential.json 不是有效 JSON：{self.path}") from exc
        if not isinstance(payload, dict):
            raise XiyouConfigError(f"西柚 credential.json 结构错误：{self.path}")
        authorization = normalize_authorization(payload.get("authorization"))
        cookie = payload.get("cookie")
        return XiyouCredential(
            authorization=authorization,
            cookie=str(cookie).strip() if cookie else None,
            source=_optional_str(payload.get("source")),
            operator=_optional_str(payload.get("operator")),
            updated_at=_optional_str(payload.get("updated_at")),
            expires_at=_optional_str(payload.get("expires_at")),
            version=payload.get("version"),
            headers=_optional_headers(payload.get("headers")),
        )

    def save(
        self,
        *,
        authorization: str,
        cookie: str | None = None,
        source: str = "manual",
        operator: str | None = None,
    ) -> XiyouCredential:
        """校验 JWT 元数据后原子写入 credential.json。"""
        normalized = normalize_authorization(authorization)
        expires_at = parse_jwt_expires_at(normalized)
        updated_at = datetime.now(timezone.utc).isoformat()
        credential = XiyouCredential(
            authorization=normalized,
            cookie=str(cookie).strip() if cookie else None,
            source=source,
            operator=str(operator).strip() if operator else None,
            updated_at=updated_at,
            expires_at=expires_at,
        )
        payload = {
            "authorization": credential.authorization,
            "cookie": credential.cookie,
            "source": credential.source,
            "operator": credential.operator,
            "updated_at": credential.updated_at,
            "expires_at": credential.expires_at,
        }
        self._write_atomic(payload)
        return credential

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.replace(tmp_path, self.path)
        except PermissionError:
            # 部分受限 Windows 运行环境允许写文件但拒绝 rename/replace。
            # 兜底写入发生在所有校验通过之后，避免失败 token 覆盖旧凭据。20260610
            self.path.write_text(tmp_path.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


class XiyouCredentialProvider:
    """从服务端配置读取西柚洞察凭据。"""

    def __init__(
        self,
        settings: XiyouSettings | None = None,
        *,
        auth_client: Any | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.auth_client = auth_client
        self.jwt = jwt
        self.session_id = session_id

    def get_default(self) -> XiyouCredential:
        """读取默认凭据。"""
        if self.settings.credential_latest_url:
            from opscli.xiyou.credential_service import (
                XiyouCredentialServiceClient,
                get_cached_remote_credential,
            )

            client = XiyouCredentialServiceClient(
                self.settings,
                auth_client=self.auth_client,
                jwt=self.jwt,
                session_id=self.session_id,
            )
            return get_cached_remote_credential(self.settings, client=client)
        if not self.settings.authorization:
            raise XiyouConfigError("missing OPSCLI_XIYOU_CREDENTIAL_LATEST_URL or OPSCLI_XIYOU_AUTHORIZATION")
        return XiyouCredential(
            authorization=normalize_authorization(self.settings.authorization),
            cookie=self.settings.cookie,
            source="env",
        )


def normalize_authorization(value: Any) -> str:
    """规范化从浏览器或后台提交来的 authorization 字段。"""
    text = str(value or "").strip().strip('"').strip("'")
    if text.lower().startswith("authorization:"):
        text = text.split(":", 1)[1].strip()
    if not text:
        raise XiyouConfigError("authorization 不能为空")
    return text


def parse_jwt_expires_at(authorization: str) -> str:
    """解析西柚 JWT exp，返回 UTC ISO 时间。"""
    payload = decode_jwt_payload(authorization)
    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise XiyouConfigError("authorization JWT 缺少有效 exp")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise XiyouConfigError(f"authorization JWT 已过期：{expires_at.isoformat()}")
    return expires_at.isoformat()


def decode_jwt_payload(authorization: str) -> dict[str, Any]:
    """不验签解析 JWT payload，用于格式与过期时间校验。"""
    token = _strip_bearer(authorization)
    parts = token.split(".")
    if len(parts) != 3:
        raise XiyouConfigError("authorization 不是有效 JWT")
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise XiyouConfigError("authorization JWT payload 解析失败") from exc
    if not isinstance(payload, dict):
        raise XiyouConfigError("authorization JWT payload 结构错误")
    return payload


def _strip_bearer(authorization: str) -> str:
    text = authorization.strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_headers(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    headers = {str(key): str(item) for key, item in value.items() if item is not None}
    return headers or None
