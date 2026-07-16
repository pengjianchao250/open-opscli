"""卖家精灵进程内工作账号与冷备用账号池。"""

from __future__ import annotations

import hashlib

from opscli.seller_sprite.accounts import SellerSpriteAccount


# 并发上限固定为3，避免账号接口返回过多账号时无界创建浏览器会话。
DEFAULT_MAX_WORKING_ACCOUNTS = 3


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
    """按接口顺序管理最多四个工作账号和冷备用账号。"""

    def __init__(self, *, max_working_accounts: int = DEFAULT_MAX_WORKING_ACCOUNTS) -> None:
        self.max_working_accounts = max(1, int(max_working_accounts))
        self._working: list[SellerSpriteAccount] = []
        self._standby: list[SellerSpriteAccount] = []
        self._unavailable_versions: set[tuple[str, str]] = set()
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
        ordered = _deduplicate_accounts(accounts)
        count = len(ordered)
        self._target_working_count = (
            0 if count == 0 else min(self.max_working_accounts, max(1, count - 1))
        )
        self._working = ordered[: self._target_working_count]
        self._standby = ordered[self._target_working_count :]

    def refresh(self, accounts: list[SellerSpriteAccount]) -> None:
        """合并刷新结果，并让密码已变化的失效账号恢复候选资格。"""
        ordered = _deduplicate_accounts(accounts)
        count = len(ordered)
        self._target_working_count = (
            0 if count == 0 else min(self.max_working_accounts, max(1, count - 1))
        )
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

    def mark_unavailable(self, account: SellerSpriteAccount) -> None:
        """将当前凭证版本标记为不可用并移出工作池和备用池。"""
        key = seller_sprite_account_key(account)
        self._unavailable_versions.add((key, _credential_version(account)))
        self._working = [item for item in self._working if seller_sprite_account_key(item) != key]
        self._standby = [item for item in self._standby if seller_sprite_account_key(item) != key]

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

    def activate_standby_until_target(self) -> tuple[SellerSpriteAccount, ...]:
        """按接口顺序使用可用备用账号补足当前目标工作槽。"""
        activated: list[SellerSpriteAccount] = []
        while len(self._working) < self._target_working_count:
            replacement = self.take_standby(attempted_accounts=set())
            if replacement is None:
                break
            activated.append(replacement)
        return tuple(activated)

    def _is_unavailable(self, account: SellerSpriteAccount) -> bool:
        """判断当前账号凭证版本是否已确认不可用。"""
        return (
            seller_sprite_account_key(account),
            _credential_version(account),
        ) in self._unavailable_versions


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
