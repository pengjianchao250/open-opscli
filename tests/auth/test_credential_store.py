import pytest
from datetime import datetime, timezone, timedelta
from opscli.auth.storage.credential_store import CredentialStore


@pytest.fixture
def store(tmp_path):
    return CredentialStore(base_dir=tmp_path)


def test_save_and_load_session(store):
    store.save_session("uuid-1234", "user@example.com", "2099-05-17T10:00:00+00:00", "dc-abc")
    d = store.load()
    assert d["session_id"] == "uuid-1234"
    assert d["device_code"] == "dc-abc"
    assert d["email"] == "user@example.com"


def test_save_and_load_token(store):
    store.save_session("uuid-1234", "user@example.com", "2099-05-17T10:00:00+00:00", "dc-abc")
    store.save_token("ops", "eyJhbGci...", expires_in=7200)
    d = store.load()
    assert d["tokens"]["ops"]["jwt"] == "eyJhbGci..."


def test_save_session_clears_cached_tokens_when_account_changes(store):
    store.save_session("uuid-1234", "user@example.com", "2099-05-17T10:00:00+00:00", "dc-abc")
    store.save_token("ops", "old-jwt", expires_in=7200)

    store.save_session("uuid-5678", "other@example.com", "2099-05-18T10:00:00+00:00", "dc-def")

    d = store.load()
    assert d["session_id"] == "uuid-5678"
    assert d["email"] == "other@example.com"
    assert d["tokens"] == {}


def test_load_returns_none_when_empty(store):
    assert store.load() is None


def test_clear(store):
    store.save_session("uuid-1234", "user@example.com", "2099-05-17T10:00:00+00:00", "dc-abc")
    store.clear()
    assert store.load() is None
