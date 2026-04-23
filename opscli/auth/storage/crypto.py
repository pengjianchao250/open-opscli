"""AES-256-GCM 加密工具模块。

为凭证文件提供对称加密能力，密钥自动生成并存储在本地文件中。
加密格式：[12 字节随机 nonce] + [AES-GCM 密文]，解密时按前 12 字节切割 nonce。
"""
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Crypto:
    """AES-256-GCM 加密器，管理密钥的生成、加载和加解密操作。

    密钥文件首次使用时自动生成（256 位），存储权限为 600（仅属主可读写）。
    """

    def __init__(self, key_path: Path):
        """
        Args:
            key_path: 密钥文件路径，不存在时自动创建
        """
        self._key_path = Path(key_path)
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        """加载已有密钥，或首次使用时生成 256 位 AES 密钥并持久化。"""
        if self._key_path.exists():
            return self._key_path.read_bytes()
        # 生成 256 位随机密钥
        key = AESGCM.generate_key(bit_length=256)
        self._key_path.write_bytes(key)
        # 权限设为 600（仅属主可读写），防止其他用户读取密钥
        self._key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return key

    def encrypt(self, plaintext: str) -> bytes:
        """加密明文字符串。

        使用 12 字节（96 位）随机 nonce，拼接格式为 nonce + ciphertext。
        96 位 nonce 是 NIST 推荐的 GCM nonce 长度，可保证安全性和性能。

        Args:
            plaintext: 待加密的明文字符串

        Returns:
            bytes: nonce(12B) + AES-GCM 密文
        """
        nonce = os.urandom(12)  # 96 位随机 nonce
        return nonce + AESGCM(self._key).encrypt(nonce, plaintext.encode(), None)

    def decrypt(self, ciphertext: bytes) -> str:
        """解密密文，还原为明文字符串。

        按约定前 12 字节为 nonce，剩余部分为 AES-GCM 密文。

        Args:
            ciphertext: nonce(12B) + AES-GCM 密文

        Returns:
            str: 解密后的明文

        Raises:
            cryptography.exceptions.InvalidTag: 密钥不匹配或数据被篡改
        """
        return AESGCM(self._key).decrypt(ciphertext[:12], ciphertext[12:], None).decode()
