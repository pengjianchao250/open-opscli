import pytest
from pathlib import Path

from opscli.auth.storage.crypto import Crypto


def test_encrypt_decrypt_roundtrip(tmp_path):
    c = Crypto(key_path=tmp_path / ".key")
    text = '{"session_id": "test-uuid"}'
    assert c.decrypt(c.encrypt(text)) == text


def test_key_auto_generated_with_600_perm(tmp_path):
    key_path = tmp_path / ".key"
    Crypto(key_path=key_path)
    assert key_path.exists()
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_different_nonce_each_time(tmp_path):
    c = Crypto(key_path=tmp_path / ".key")
    assert c.encrypt("hello") != c.encrypt("hello")