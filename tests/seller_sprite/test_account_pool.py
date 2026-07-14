"""卖家精灵多账号工作池测试。"""

from opscli.seller_sprite.accounts import SellerSpriteAccount


def _accounts(count: int, *, password_suffix: str = "") -> list[SellerSpriteAccount]:
    return [
        SellerSpriteAccount(
            name=f"account-{index}",
            username=f"user-{index}@example.com",
            password=f"secret-{index}{password_suffix}",
        )
        for index in range(1, count + 1)
    ]


def test_account_pool_reserves_one_account_and_caps_workers_at_four():
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    expected = {
        0: (0, 0),
        1: (1, 0),
        2: (1, 1),
        3: (2, 1),
        4: (3, 1),
        5: (4, 1),
        6: (4, 2),
    }

    for count, (working_count, standby_count) in expected.items():
        pool = SellerSpriteAccountPool()
        pool.load(_accounts(count))

        assert len(pool.working_accounts) == working_count
        assert len(pool.standby_accounts) == standby_count
        assert [account.name for account in pool.working_accounts] == [
            f"account-{index}" for index in range(1, working_count + 1)
        ]


def test_account_pool_promotes_cold_standby_after_working_account_fails():
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    pool = SellerSpriteAccountPool()
    accounts = _accounts(5)
    pool.load(accounts)

    pool.mark_unavailable(accounts[0])
    replacement = pool.take_standby(attempted_account_keys=set())

    assert replacement == accounts[4]
    assert [account.name for account in pool.working_accounts] == [
        "account-2",
        "account-3",
        "account-4",
        "account-5",
    ]
    assert pool.standby_accounts == ()


def test_account_pool_keeps_same_failed_credentials_unavailable_until_password_changes():
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool, seller_sprite_account_key

    pool = SellerSpriteAccountPool()
    accounts = _accounts(2)
    pool.load(accounts)
    failed = accounts[0]
    pool.mark_unavailable(failed)

    pool.refresh(accounts)
    assert seller_sprite_account_key(failed) not in {
        seller_sprite_account_key(account) for account in pool.standby_accounts
    }

    changed = SellerSpriteAccount(
        name=failed.name,
        username=failed.username,
        password="new-secret",
    )
    pool.refresh([changed, accounts[1]])

    assert changed in pool.standby_accounts
    activated = pool.activate_standby_until_target()
    assert activated == (changed,)
    assert pool.working_accounts == (changed,)
