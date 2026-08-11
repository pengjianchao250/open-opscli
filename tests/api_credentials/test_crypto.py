"""API Key 信封加密测试。"""

import base64

import pytest

from opscli.api_credentials.crypto import ApiKeyCipher


def _cipher() -> ApiKeyCipher:
    return ApiKeyCipher(base64.b64encode(b"k" * 32).decode("ascii"))


def test_envelope_encryption_round_trip_and_public_fields():
    cipher = _cipher()

    encrypted = cipher.encrypt("secret-api-key-1234", account_id=41, version=2)

    assert b"secret-api-key-1234" not in encrypted.ciphertext
    assert b"secret-api-key-1234" not in encrypted.encrypted_dek
    assert encrypted.masked == "secr****1234"
    assert cipher.decrypt(
        encrypted.ciphertext,
        encrypted.nonce,
        encrypted.encrypted_dek,
        encrypted.dek_nonce,
        account_id=41,
        version=2,
    ) == "secret-api-key-1234"


def test_envelope_encryption_binds_ciphertext_to_account_and_version():
    cipher = _cipher()
    encrypted = cipher.encrypt("secret-api-key", account_id=41, version=2)

    with pytest.raises(ValueError, match="API Key 解密失败"):
        cipher.decrypt(
            encrypted.ciphertext,
            encrypted.nonce,
            encrypted.encrypted_dek,
            encrypted.dek_nonce,
            account_id=42,
            version=2,
        )


@pytest.mark.parametrize("raw", [b"short", b"x" * 31, b"x" * 33])
def test_master_key_must_decode_to_32_bytes(raw):
    with pytest.raises(ValueError, match="32 字节"):
        ApiKeyCipher(base64.b64encode(raw).decode("ascii"))
