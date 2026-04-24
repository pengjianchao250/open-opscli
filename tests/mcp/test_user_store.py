from pathlib import Path

from opscli.mcp.user_store import API_KEY_PREFIX, MCPUserStore


def test_add_user_stores_hash_and_creates_private_dir(tmp_path: Path):
    store = MCPUserStore(base_dir=tmp_path)

    result = store.add_user(description="测试用户")

    assert result["api_key"].startswith(API_KEY_PREFIX)
    assert result["user_id"].startswith("u_")
    assert store.path.exists()
    assert store.credential_dir(result["user_id"]).exists()
    assert result["api_key"] not in store.path.read_text(encoding="utf-8")


def test_verify_api_key_returns_user(tmp_path: Path):
    store = MCPUserStore(base_dir=tmp_path)
    created = store.add_user(description="测试用户")

    user = store.verify_api_key(created["api_key"])

    assert user is not None
    assert user.user_id == created["user_id"]
    assert user.credential_dir == store.credential_dir(created["user_id"])


def test_rotate_invalidates_old_key(tmp_path: Path):
    store = MCPUserStore(base_dir=tmp_path)
    created = store.add_user(description="测试用户")

    rotated = store.rotate_api_key(created["user_id"])

    assert store.verify_api_key(created["api_key"]) is None
    assert store.verify_api_key(rotated["api_key"]) is not None


def test_remove_user_deletes_credentials_by_default(tmp_path: Path):
    store = MCPUserStore(base_dir=tmp_path)
    created = store.add_user(description="测试用户")
    credential_dir = store.credential_dir(created["user_id"])
    (credential_dir / "credentials.bin").write_text("x", encoding="utf-8")

    assert store.remove_user(created["user_id"]) is True

    assert store.verify_api_key(created["api_key"]) is None
    assert not credential_dir.exists()
