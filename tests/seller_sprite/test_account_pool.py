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


def test_account_pool_reserves_one_account_and_caps_workers_at_five():
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    expected = {
        0: (0, 0),
        1: (1, 0),
        2: (1, 1),
        3: (2, 1),
        4: (3, 1),
        5: (4, 1),
        6: (5, 1),
        7: (5, 2),
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
    accounts = _accounts(7)
    pool.load(accounts)

    pool.mark_unavailable(accounts[0])
    replacement = pool.take_standby(attempted_accounts=set())

    assert replacement == accounts[5]
    assert [account.name for account in pool.working_accounts] == [
        "account-2",
        "account-3",
        "account-4",
        "account-5",
        "account-6",
    ]
    assert pool.standby_accounts == (accounts[6],)


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


def test_account_pool_restores_persisted_quarantine_after_process_restart(tmp_path):
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    accounts = _accounts(2)
    first_store = SellerSpriteTaskQueueStore(db_path=db_path)
    first_pool = SellerSpriteAccountPool(quarantine_store=first_store)
    first_pool.load(accounts)
    first_pool.mark_unavailable(accounts[0])

    restarted_store = SellerSpriteTaskQueueStore(db_path=db_path)
    restarted_pool = SellerSpriteAccountPool(quarantine_store=restarted_store)
    restarted_pool.load(accounts)

    assert restarted_pool.working_accounts == (accounts[1],)
    assert restarted_pool.standby_accounts == ()

    changed = SellerSpriteAccount(
        name=accounts[0].name,
        username=accounts[0].username,
        password="rotated-secret",
    )
    restarted_pool.load([changed, accounts[1]])

    assert restarted_pool.working_accounts == (changed,)
    assert restarted_pool.standby_accounts == (accounts[1],)


def test_account_pool_releases_expired_persisted_quarantine_on_refresh():
    from opscli.seller_sprite.services.account_pool import (
        SellerSpriteAccountPool,
        seller_sprite_account_attempt_key,
    )

    accounts = _accounts(2)

    class MutableQuarantineStore:
        def __init__(self):
            self.active = {seller_sprite_account_attempt_key(accounts[0])}

        def list_active_account_quarantines(self):
            return set(self.active)

        def quarantine_account(self, **kwargs):
            return None

    store = MutableQuarantineStore()
    pool = SellerSpriteAccountPool(quarantine_store=store)
    pool.load(accounts)
    assert accounts[0] not in pool.working_accounts + pool.standby_accounts

    store.active.clear()
    pool.refresh(accounts)

    assert accounts[0] in pool.standby_accounts


def test_account_pool_releases_transient_failure_after_cooldown(monkeypatch):
    """未确认的登录失败只在当前进程短暂冷却，且不写持久隔离。"""
    from opscli.seller_sprite.services import account_pool as account_pool_module
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    now = [100.0]
    monkeypatch.setattr(account_pool_module, "monotonic", lambda: now[0])
    accounts = _accounts(2)

    class RecordingQuarantineStore:
        def __init__(self):
            self.writes = []

        def list_active_account_quarantines(self):
            return set()

        def quarantine_account(self, **kwargs):
            self.writes.append(kwargs)

    store = RecordingQuarantineStore()
    pool = SellerSpriteAccountPool(quarantine_store=store)
    pool.load(accounts)
    pool.mark_unavailable(
        accounts[0],
        persist_quarantine=False,
        temporary_cooldown_seconds=10,
    )

    pool.refresh(accounts)
    assert accounts[0] not in pool.working_accounts + pool.standby_accounts
    assert pool.has_temporary_unavailable_accounts is True
    assert store.writes == []

    now[0] += 11
    pool.refresh(accounts)

    assert accounts[0] in pool.standby_accounts
    assert pool.has_temporary_unavailable_accounts is False


def test_account_pool_keeps_failover_available_when_quarantine_write_fails():
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    accounts = _accounts(2)

    class FailingQuarantineStore:
        def list_active_account_quarantines(self):
            return set()

        def quarantine_account(self, **kwargs):
            raise OSError("quarantine store unavailable")

    pool = SellerSpriteAccountPool(quarantine_store=FailingQuarantineStore())
    pool.load(accounts)

    persisted = pool.mark_unavailable(accounts[0])

    assert persisted is False
    assert accounts[0] not in pool.working_accounts + pool.standby_accounts


def test_account_pool_only_reports_all_attempted_after_each_known_account_ran():
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    accounts = _accounts(3)
    pool = SellerSpriteAccountPool()
    pool.load(accounts)

    assert not pool.all_accounts_attempted({accounts[0]})
    assert not pool.all_accounts_attempted({accounts[0], accounts[2]})
    assert pool.all_accounts_attempted(set(accounts))


def test_account_pool_prioritizes_changed_password_for_same_identity():
    """同一身份换新密码后，应先于其他冷备用账号参加当前任务接替。"""
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    pool = SellerSpriteAccountPool()
    accounts = _accounts(3)
    failed = accounts[0]
    pool.load(accounts)
    pool.mark_unavailable(failed)
    changed = SellerSpriteAccount(
        name=failed.name,
        username=failed.username,
        password="rotated-secret",
    )

    pool.refresh([changed, accounts[1], accounts[2]])
    replacement = pool.take_standby(attempted_accounts={failed})

    assert replacement == changed


def test_account_pool_defers_busy_healthy_account_without_duplication():
    """暂时冲突的健康账号应按接口顺序归还，且不得重复登记。"""
    from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool

    pool = SellerSpriteAccountPool()
    accounts = _accounts(8)
    pool.load(accounts)
    pool.mark_unavailable(accounts[0])
    replacement = pool.take_standby(attempted_accounts=set())

    pool.defer_working_account(replacement)
    pool.defer_working_account(replacement)

    working = set(pool.working_accounts)
    assert replacement not in working
    assert pool.standby_accounts.count(replacement) == 1
    assert not working.intersection(pool.standby_accounts)
    assert pool.standby_accounts == (accounts[5], accounts[6], accounts[7])
