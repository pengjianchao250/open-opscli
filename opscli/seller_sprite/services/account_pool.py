"""卖家精灵进程内工作账号与冷备用账号池。"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.domain.constants import ACCOUNT_FAILURE_REASON_AUTHENTICATION

# 并发上限固定为3，避免账号接口返回过多账号时无界创建浏览器会话。
DEFAULT_MAX_WORKING_ACCOUNTS = 3
# 明确认证失败后隔离 24 小时，既阻断重启重试风暴，也允许临时误判自动恢复。
DEFAULT_ACCOUNT_QUARANTINE_TTL_SECONDS = 86400
logger = logging.getLogger(__name__)


class AccountQuarantineStore(Protocol):
    """账号池使用的持久隔离存储接口。"""

    def list_active_account_quarantines(self) -> set[tuple[str, str]]:
        """返回有效隔离键集合。

        返回：
            账号身份散列与凭据版本散列组成的集合。
        """
        ...

    def quarantine_account(
        self,
        *,
        account_key: str,
        credential_version: str,
        reason: str,
        error_code: str,
        ttl_seconds: int,
    ) -> None:
        """保存账号隔离状态。

        参数：
            account_key: 脱敏账号身份散列。
            credential_version: 凭据版本散列。
            reason: 隔离原因。
            error_code: 触发隔离的稳定错误码。
            ttl_seconds: 隔离有效秒数。

        返回：
            无。
        """
        ...


def seller_sprite_account_key(account: SellerSpriteAccount) -> str:
    """返回不含明文凭证的稳定账号身份键。"""
    identity = (
        f"seller_sprite:{account.name.strip().casefold()}:{account.username.strip().casefold()}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def seller_sprite_account_attempt_key(account: SellerSpriteAccount) -> tuple[str, str]:
    """返回包含凭证版本的尝试键，使同身份新密码可重新参与接替。"""
    return seller_sprite_account_key(account), _credential_version(account)


def mask_seller_sprite_username(username: str) -> str:
    """返回适合日志和审计使用的脱敏用户名。"""
    value = username.strip()
    if "@" in value:
        local, domain = value.split("@", 1)
        prefix = local[:1] if local else "*"
        return f"{prefix}***@{domain}"
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[:1]}***{value[-1:]}"


class SellerSpriteAccountPool:
    """按接口顺序管理最多三个工作账号和冷备用账号。"""

    def __init__(
        self,
        *,
        max_working_accounts: int = DEFAULT_MAX_WORKING_ACCOUNTS,
        quarantine_store: AccountQuarantineStore | None = None,
        quarantine_ttl_seconds: int = DEFAULT_ACCOUNT_QUARANTINE_TTL_SECONDS,
    ) -> None:
        """创建账号池。

        参数：
            max_working_accounts: 最大并行工作账号数。
            quarantine_store: 可选的持久隔离存储。
            quarantine_ttl_seconds: 明确认证失败后的隔离秒数。

        返回：
            无。
        """
        self.max_working_accounts = max(1, int(max_working_accounts))
        self.quarantine_store = quarantine_store
        self.quarantine_ttl_seconds = max(1, int(quarantine_ttl_seconds))
        self._working: list[SellerSpriteAccount] = []
        self._standby: list[SellerSpriteAccount] = []
        self._unavailable_versions: set[tuple[str, str]] = set()
        self._persisted_unavailable_versions: set[tuple[str, str]] = set()
        self._account_order: dict[str, int] = {}
        self._target_working_count = 0

    @property
    def working_accounts(self) -> tuple[SellerSpriteAccount, ...]:
        """返回当前工作账号快照。"""
        return tuple(self._working)

    @property
    def standby_accounts(self) -> tuple[SellerSpriteAccount, ...]:
        """返回当前冷备用账号快照。"""
        return tuple(self._standby)

    @property
    def target_working_count(self) -> int:
        """返回当前账号总量对应的目标工作槽数量。"""
        return self._target_working_count

    def load(self, accounts: list[SellerSpriteAccount]) -> None:
        """使用首次账号接口结果建立工作池和冷备用池。"""
        ordered = self._prepare_accounts(accounts)
        self._working = ordered[: self._target_working_count]
        self._standby = ordered[self._target_working_count :]

    def refresh(self, accounts: list[SellerSpriteAccount]) -> None:
        """合并刷新结果，并让密码已变化的失效账号恢复候选资格。"""
        ordered = self._prepare_accounts(accounts)
        by_key = {seller_sprite_account_key(account): account for account in ordered}

        # 保留仍存在且凭证版本可用的工作账号，避免刷新时无故重建健康会话。
        working_keys: set[str] = set()
        refreshed_working: list[SellerSpriteAccount] = []
        for current in self._working:
            key = seller_sprite_account_key(current)
            refreshed = by_key.get(key)
            if refreshed is None or self._is_unavailable(refreshed):
                continue
            refreshed_working.append(refreshed)
            working_keys.add(key)
        self._working = refreshed_working[: self._target_working_count]
        working_keys = {seller_sprite_account_key(account) for account in self._working}

        # 空槽由当前故障任务显式领取备用，刷新本身不提前激活冷备用会话。
        self._standby = [
            account
            for account in ordered
            if seller_sprite_account_key(account) not in working_keys
            and not self._is_unavailable(account)
        ]

    def mark_unavailable(self, account: SellerSpriteAccount) -> bool:
        """将当前凭证版本移出账号池，并尽力持久化隔离。

        参数：
            account: 已确认认证失败的账号凭据。

        返回：
            持久化成功或无需持久化时返回 ``True``；降级为进程内隔离时返回 ``False``。
        """
        key = seller_sprite_account_key(account)
        credential_version = _credential_version(account)
        attempt_key = (key, credential_version)
        self._unavailable_versions.add(attempt_key)
        persisted = self.quarantine_store is None
        try:
            if self.quarantine_store is not None:
                self.quarantine_store.quarantine_account(
                    account_key=key,
                    credential_version=credential_version,
                    reason=ACCOUNT_FAILURE_REASON_AUTHENTICATION,
                    error_code="SELLER_SPRITE_AUTHENTICATION_ERROR",
                    ttl_seconds=self.quarantine_ttl_seconds,
                )
                self._persisted_unavailable_versions.add(attempt_key)
                persisted = True
        except Exception as exc:  # noqa: BLE001
            # SQLite 隔离是增强保护，写失败不能打断已经完成的任务原子改绑。
            logger.warning(
                "卖家精灵账号隔离持久化失败，已降级为进程内隔离：error=%s",
                type(exc).__name__,
            )
        finally:
            self._working = [
                item
                for item in self._working
                if seller_sprite_account_key(item) != key
            ]
            self._standby = [
                item
                for item in self._standby
                if seller_sprite_account_key(item) != key
            ]
        return persisted

    def take_standby(
        self,
        *,
        attempted_accounts: set[SellerSpriteAccount],
    ) -> SellerSpriteAccount | None:
        """按接口顺序取出当前凭证版本尚未被任务尝试的冷备用账号。"""
        attempted_versions = {
            seller_sprite_account_attempt_key(account) for account in attempted_accounts
        }
        for index, account in enumerate(self._standby):
            if (
                seller_sprite_account_attempt_key(account) in attempted_versions
                or self._is_unavailable(account)
            ):
                continue
            replacement = self._standby.pop(index)
            self._working.append(replacement)
            return replacement
        return None

    def defer_working_account(self, account: SellerSpriteAccount) -> None:
        """将暂不可领取任务的健康账号归还冷备用池。"""
        key = seller_sprite_account_key(account)
        self._working = [
            item for item in self._working if seller_sprite_account_key(item) != key
        ]
        if self._is_unavailable(account) or any(
            seller_sprite_account_key(item) == key for item in self._standby
        ):
            return
        self._standby.append(account)
        self._standby.sort(
            key=lambda item: self._account_order.get(
                seller_sprite_account_key(item),
                len(self._account_order),
            )
        )

    def activate_standby_until_target(self) -> tuple[SellerSpriteAccount, ...]:
        """按接口顺序使用可用备用账号补足当前目标工作槽。"""
        activated: list[SellerSpriteAccount] = []
        while len(self._working) < self._target_working_count:
            replacement = self.take_standby(attempted_accounts=set())
            if replacement is None:
                break
            activated.append(replacement)
        return tuple(activated)

    def all_accounts_attempted(
        self,
        attempted_accounts: set[SellerSpriteAccount],
    ) -> bool:
        """判断当前全部已知账号凭据是否真正执行过认证。

        参数：
            attempted_accounts: 当前任务已经执行过认证的账号集合。

        返回：
            存在已知账号且每个凭据版本均被尝试过时返回 ``True``。
        """
        known_accounts = self._working + self._standby
        attempted_versions = {
            seller_sprite_account_attempt_key(account)
            for account in attempted_accounts
        }
        return bool(known_accounts) and all(
            seller_sprite_account_attempt_key(account) in attempted_versions
            for account in known_accounts
        )

    def _is_unavailable(self, account: SellerSpriteAccount) -> bool:
        """判断当前账号凭证版本是否已确认不可用。"""
        return (
            seller_sprite_account_key(account),
            _credential_version(account),
        ) in self._unavailable_versions

    def _reload_persisted_quarantines(self) -> None:
        """合并仍有效的持久隔离，使进程重启不丢失认证失败状态。"""
        if self.quarantine_store is None:
            return
        active = self.quarantine_store.list_active_account_quarantines()
        self._unavailable_versions.difference_update(
            self._persisted_unavailable_versions
        )
        self._unavailable_versions.update(active)
        self._persisted_unavailable_versions = active

    def _prepare_accounts(
        self,
        accounts: list[SellerSpriteAccount],
    ) -> list[SellerSpriteAccount]:
        """统一过滤隔离账号并计算工作槽目标，避免加载与刷新规则漂移。"""
        self._reload_persisted_quarantines()
        ordered = [
            account
            for account in _deduplicate_accounts(accounts)
            if not self._is_unavailable(account)
        ]
        self._account_order = {
            seller_sprite_account_key(account): index
            for index, account in enumerate(ordered)
        }
        count = len(ordered)
        self._target_working_count = (
            0 if count == 0 else min(self.max_working_accounts, max(1, count - 1))
        )
        return ordered


def _deduplicate_accounts(accounts: list[SellerSpriteAccount]) -> list[SellerSpriteAccount]:
    """按规范化账号身份去重并保留接口首次出现顺序。"""
    seen: set[str] = set()
    ordered: list[SellerSpriteAccount] = []
    for account in accounts:
        key = seller_sprite_account_key(account)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(account)
    return ordered


def _credential_version(account: SellerSpriteAccount) -> str:
    """计算仅用于内存比较的凭证版本摘要。"""
    return hashlib.sha256(account.password.encode("utf-8")).hexdigest()
