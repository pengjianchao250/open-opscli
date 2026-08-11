"""API Key 的 AES-256-GCM 加密实现。"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EncryptedApiKey:
    """可直接写入 MySQL 的 API Key 密文。"""

    ciphertext: bytes
    nonce: bytes
    encrypted_dek: bytes
    dek_nonce: bytes
    masked: str
    fingerprint: str


class ApiKeyCipher:
    """使用部署主密钥执行认证加密。"""

    def __init__(self, master_key_b64: str) -> None:
        """创建信封加密器。

        Args:
            master_key_b64: Base64 编码的 32 字节主密钥。

        Raises:
            ValueError: 主密钥不是合法 Base64 或长度不是 32 字节。
        """
        try:
            key = base64.b64decode(master_key_b64, validate=True)
        except Exception as exc:
            raise ValueError("API 凭据主密钥必须是有效 Base64") from exc
        if len(key) != 32:
            raise ValueError("API 凭据主密钥解码后必须为 32 字节")
        self._cipher = AESGCM(key)

    def encrypt(self, api_key: str, *, account_id: int, version: int) -> EncryptedApiKey:
        """使用每条凭据独立的数据密钥加密 API Key。

        Args:
            api_key: 待加密的明文 API Key。
            account_id: 密钥所属账号 ID，用于认证附加数据。
            version: 账号内密钥版本，用于认证附加数据。

        Returns:
            密文、随机数、被主密钥包裹的数据密钥和脱敏摘要。

        Raises:
            ValueError: API Key 为空。
        """
        secret = str(api_key or "").strip()
        if not secret:
            raise ValueError("API Key 不能为空")
        # 每条凭据使用随机 DEK，后续更换 KEK 时只需重包裹 DEK，无需暴露或重加密 API Key。
        associated_data = _associated_data(account_id, version)
        data_key = AESGCM.generate_key(bit_length=256)
        data_cipher = AESGCM(data_key)
        nonce = os.urandom(12)
        ciphertext = data_cipher.encrypt(
            nonce,
            secret.encode("utf-8"),
            associated_data,
        )
        dek_nonce = os.urandom(12)
        encrypted_dek = self._cipher.encrypt(
            dek_nonce,
            data_key,
            associated_data + b":dek",
        )
        return EncryptedApiKey(
            ciphertext=ciphertext,
            nonce=nonce,
            encrypted_dek=encrypted_dek,
            dek_nonce=dek_nonce,
            masked=_mask_secret(secret),
            fingerprint=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        )

    def decrypt(
        self,
        ciphertext: bytes,
        nonce: bytes,
        encrypted_dek: bytes,
        dek_nonce: bytes,
        *,
        account_id: int,
        version: int,
    ) -> str:
        """解包数据密钥并验证解密 API Key。

        Args:
            ciphertext: API Key 密文。
            nonce: API Key 加密随机数。
            encrypted_dek: 被主密钥包裹的数据密钥。
            dek_nonce: 数据密钥包裹随机数。
            account_id: 密钥所属账号 ID。
            version: 账号内密钥版本。

        Returns:
            验证通过后的明文 API Key。

        Raises:
            ValueError: 主密钥、账号、版本或任一密文不匹配。
        """
        try:
            associated_data = _associated_data(account_id, version)
            data_key = self._cipher.decrypt(
                dek_nonce,
                encrypted_dek,
                associated_data + b":dek",
            )
            plaintext = AESGCM(data_key).decrypt(
                nonce,
                ciphertext,
                associated_data,
            )
        except Exception as exc:
            raise ValueError("API Key 解密失败，请检查主密钥或密文") from exc
        return plaintext.decode("utf-8")


def _associated_data(account_id: int, version: int) -> bytes:
    return f"opscli-api-credential:{account_id}:{version}".encode("ascii")


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"
