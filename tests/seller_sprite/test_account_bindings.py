"""卖家精灵用户专属账号绑定仓储测试。"""

import os
import stat
from pathlib import Path


def test_account_binding_store_encrypts_password_and_reuses_named_account(tmp_path: Path):
    from opscli.seller_sprite.services.account_bindings import (
        SellerSpriteAccountBindingStore,
    )

    db_path = tmp_path / "bindings.sqlite3"
    key_path = tmp_path / "bindings.key"
    store = SellerSpriteAccountBindingStore(db_path=db_path, key_path=key_path)

    first = store.bind(
        user_email="First@Example.com",
        account_name="team-a",
        username="seller@example.com",
        password="first-secret",
    )
    second = store.bind(
        user_email="second@example.com",
        account_name="team-a",
        username="seller@example.com",
        password="updated-secret",
    )

    assert first.user_email == "first@example.com"
    assert second.account.account_id == first.account.account_id
    assert store.get_binding("FIRST@example.com").account.password == "updated-secret"
    assert store.get_binding("second@example.com").account.password == "updated-secret"
    assert len(key_path.read_bytes()) == 32
    if os.name != "nt":
        assert key_path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR

    persisted = db_path.read_bytes()
    wal_path = Path(f"{db_path}-wal")
    if wal_path.exists():
        persisted += wal_path.read_bytes()
    assert b"first-secret" not in persisted
    assert b"updated-secret" not in persisted


def test_account_binding_list_is_masked_and_does_not_decrypt_password(tmp_path: Path):
    from opscli.seller_sprite.services.account_bindings import (
        SellerSpriteAccountBindingStore,
    )

    store = SellerSpriteAccountBindingStore(
        db_path=tmp_path / "bindings.sqlite3",
        key_path=tmp_path / "bindings.key",
    )
    store.bind(
        user_email="user@example.com",
        account_name="team-a",
        username="seller@example.com",
        password="secret",
    )
    store.crypto.decrypt = lambda ciphertext: (_ for _ in ()).throw(
        AssertionError("列表不应解密密码")
    )

    bindings = store.list_bindings()

    assert bindings[0]["user_email"] == "user@example.com"
    assert bindings[0]["account_name"] == "team-a"
    assert bindings[0]["username"] == "s***@example.com"
    assert "password" not in bindings[0]


def test_account_binding_rebind_updates_public_bound_at(tmp_path: Path, monkeypatch):
    from opscli.seller_sprite.services import account_bindings as module

    store = module.SellerSpriteAccountBindingStore(
        db_path=tmp_path / "bindings.sqlite3",
        key_path=tmp_path / "bindings.key",
    )
    store.bind(
        user_email="user@example.com",
        account_name="team-a",
        username="first@example.com",
        password="first-secret",
    )
    monkeypatch.setattr(
        module,
        "_now_iso",
        lambda: "2026-07-20T12:00:00+08:00",
    )

    rebound = store.bind(
        user_email="user@example.com",
        account_name="team-b",
        username="second@example.com",
        password="second-secret",
    )

    assert rebound.bound_at == "2026-07-20T12:00:00+08:00"
    assert store.list_bindings()[0]["bound_at"] == "2026-07-20T12:00:00+08:00"


def test_account_binding_unbind_keeps_reusable_account(tmp_path: Path):
    from opscli.seller_sprite.services.account_bindings import (
        SellerSpriteAccountBindingStore,
    )

    store = SellerSpriteAccountBindingStore(
        db_path=tmp_path / "bindings.sqlite3",
        key_path=tmp_path / "bindings.key",
    )
    binding = store.bind(
        user_email="user@example.com",
        account_name="team-a",
        username="seller@example.com",
        password="secret",
    )

    assert store.unbind("USER@example.com") is True
    assert store.get_binding_reference("user@example.com") is None
    assert store.get_account(binding.account.account_id).password == "secret"
