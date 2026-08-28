"""集成账号远端获取与客户端解密。"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from opscli.auth import AuthClient
from opscli.auth.config import get_ops_system_url
from opscli.config import __version__
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import parse_remote_response


ENV_INTEGRATION_ACCOUNT_ENCRYPT_KEY = "INTEGRATION_ACCOUNT_ENCRYPT_KEY"
DEFAULT_INTEGRATION_ACCOUNT_ENCRYPT_KEY = "G9wmJAd50hIsQm5z4HNRQkAqaEbBAdYh1GQEC0Jxkfo="

_logger = logging.getLogger("opscli.integration_accounts")


class IntegrationAccountError(RemoteError):
    """集成账号接口错误。"""

    code = "INTEGRATION_ACCOUNT_ERROR"


class IntegrationAccountHttpError(IntegrationAccountError):
    """集成账号 HTTP 错误。"""

    code = "INTEGRATION_ACCOUNT_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class IntegrationAccountBusinessError(IntegrationAccountError):
    """集成账号业务错误。"""

    code = "INTEGRATION_ACCOUNT_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code


class IntegrationAccountBadJsonError(IntegrationAccountError):
    """集成账号响应结构错误。"""

    code = "INTEGRATION_ACCOUNT_BAD_JSON"


@dataclass(frozen=True)
class IntegrationAccountRecord:
    """单个集成账号。"""

    name: str
    username: str
    password: str


@dataclass(frozen=True)
class IntegrationAccountBundle:
    """平台账号集合。"""

    platform: str
    default_account: str | None
    accounts: tuple[IntegrationAccountRecord, ...]


class IntegrationAccountClient:
    """统一拉取并解密各平台集成账号。"""

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
        encrypt_key: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.jwt = jwt
        self.session_id = session_id
        self.encrypt_key = (
            encrypt_key
            or os.getenv(ENV_INTEGRATION_ACCOUNT_ENCRYPT_KEY)
            or DEFAULT_INTEGRATION_ACCOUNT_ENCRYPT_KEY
        )
        self.ops_system_url = get_ops_system_url().rstrip("/")

    def _get_auth(self, alias: str = "ops") -> tuple[dict[str, str], dict[str, str]]:
        # 显式任务凭证与请求级 MCP 上下文只能二选一，避免后台任务混用不同用户身份。
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {
                "Authorization": f"Bearer {jwt}",
                "X-Opscli-Version": __version__,
            }
            return headers, {"polarisUserToken": self.session_id}
        if self.jwt:
            return {
                "Authorization": f"Bearer {self.jwt}",
                "X-Opscli-Version": __version__,
            }, {}
        mcp_headers = get_mcp_request_headers()
        if _has_mcp_api_key(mcp_headers):
            return mcp_headers, {}
        headers, cookies = self.auth_client.build_request_auth(alias)
        headers.update(mcp_headers)
        return headers, cookies

    def get_accounts(self, platform: str) -> IntegrationAccountBundle:
        """拉取指定平台账号并解密。"""
        headers, cookies = self._get_auth("ops")
        started_at = time.monotonic()
        _logger.info("[KEEPA-TRACE] integration_accounts_start platform=%s", platform)
        try:
            response = httpx.get(
                f"{self.ops_system_url}/api/v1/integration-accounts",
                params={"platform": platform},
                headers=headers,
                cookies=cookies,
                timeout=20,
            )
        except Exception as exc:
            _logger.warning(
                "[KEEPA-TRACE] integration_accounts_error platform=%s error_type=%s elapsed_ms=%s",
                platform,
                type(exc).__name__,
                int((time.monotonic() - started_at) * 1000),
            )
            raise
        _logger.info(
            "[KEEPA-TRACE] integration_accounts_done platform=%s status=%s elapsed_ms=%s",
            platform,
            response.status_code,
            int((time.monotonic() - started_at) * 1000),
        )
        payload = parse_remote_response(
            response,
            http_error_cls=IntegrationAccountHttpError,
            business_error_cls=IntegrationAccountBusinessError,
            bad_json_error_cls=IntegrationAccountBadJsonError,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise IntegrationAccountBadJsonError("集成账号接口返回缺少 data 对象")

        records: list[IntegrationAccountRecord] = []
        for item in data.get("accounts") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            username = str(item.get("username") or "").strip()
            password = str(item.get("password") or "").strip()
            if not name or not username or not password:
                continue
            records.append(
                IntegrationAccountRecord(
                    name=name,
                    username=decrypt_integration_account_value(username, self.encrypt_key),
                    password=decrypt_integration_account_value(password, self.encrypt_key),
                )
            )

        default_account = str(data.get("default_account") or "").strip() or None
        return IntegrationAccountBundle(
            platform=str(data.get("platform") or platform).strip() or platform,
            default_account=default_account,
            accounts=tuple(records),
        )


def decrypt_integration_account_value(encrypted_b64: str, raw_key: str) -> str:
    """解密集成账号字段。"""
    try:
        data = base64.b64decode(encrypted_b64)
    except Exception as exc:
        raise IntegrationAccountBadJsonError("集成账号字段不是有效的 base64") from exc
    if len(data) <= 16:
        raise IntegrationAccountBadJsonError("集成账号字段密文长度非法")

    iv = data[:16]
    ciphertext = data[16:]
    key = hashlib.sha256(raw_key.encode("utf-8")).digest()[:32]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    try:
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise IntegrationAccountBadJsonError("集成账号字段解密失败，请检查密钥或密文") from exc
    return plaintext.decode("utf-8")


def _has_mcp_api_key(headers: dict[str, str]) -> bool:
    return bool(headers.get("X-MCP-API-Key"))
