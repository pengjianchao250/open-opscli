"""MCP Tool 调用限额控制。

本模块为 MCP 外部服务类工具提供统一的每日限额能力。限额逻辑集中在
Tool 注册切面中执行，避免卖家精灵、西柚、Sif 等业务工具各自重复实现。
SQLite 作为单机部署下的本地持久化存储，同时负责限额判断、长期日加额
和审计记录。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo


ENV_QUOTA_ENABLED = "OPSCLI_MCP_QUOTA_ENABLED"
ENV_QUOTA_CONFIG_PATH = "OPSCLI_MCP_QUOTA_CONFIG_PATH"
ENV_SQLITE_PATH = "OPSCLI_MCP_QUOTA_SQLITE_PATH"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class QuotaPolicy:
    """单个 MCP Tool 的每日限额策略。

    Args:
        tool_name: MCP Tool 函数名，如 seller_sprite_run。
        service: 业务服务名，用于 SQLite 记录和响应 quota.service。
        daily_limit: 每个用户每天可成功调用的次数。
        timezone: 自然日统计时区，当前固定使用北京时间。
    """

    tool_name: str
    service: str
    daily_limit: int
    timezone: str = "Asia/Shanghai"


@dataclass(frozen=True)
class QuotaConfig:
    """MCP 限额运行配置。

    Args:
        enabled: 是否启用限额总开关。
        sqlite_path: SQLite 限额库路径，None 表示使用默认路径或环境变量。
        policies: 当前启用的 Tool 限额策略表。
        path: 实际读取的配置文件路径，None 表示使用代码默认配置。
    """

    enabled: bool
    sqlite_path: Path | None
    policies: dict[str, QuotaPolicy]
    path: Path | None = None


@dataclass(frozen=True)
class QuotaTicket:
    """一次已占用限额的调用凭证。

    调用前占用成功后生成该对象，调用结束时用于成功结算或失败退回。
    """

    policy: QuotaPolicy
    identity: str
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class QuotaDecision:
    """限额检查结果。

    allowed 为 False 时，调用方应直接返回 error_response，不再执行真实工具。
    """

    allowed: bool
    ticket: QuotaTicket | None = None
    error_response: dict[str, Any] | None = None


class QuotaUnavailableError(Exception):
    """限额存储不可用。

    SQLite 是限额的强依赖。该异常会被转换为 MCP_QUOTA_UNAVAILABLE，
    防止存储故障时绕过每日限额。
    """


class QuotaStore(Protocol):
    """限额存储协议，便于测试和后续 DI 替换。"""

    async def reserve(self, policy: QuotaPolicy, identity: str) -> tuple[bool, dict[str, Any]]:
        """尝试占用一次调用次数。"""

    async def refund_failure(self, policy: QuotaPolicy, identity: str) -> dict[str, Any]:
        """业务失败后退回调用次数并增加失败次数。"""

    async def snapshot(self, policy: QuotaPolicy, identity: str) -> dict[str, Any]:
        """读取当前身份的额度快照，不占用次数。"""


class QuotaIdentityResolver:
    """解析当前 MCP 请求的限额身份。"""

    def resolve(self) -> str | None:
        """按邮箱优先、API Key 哈希兜底的顺序返回身份标识。"""
        from opscli.mcp.context import get_current_api_key, get_current_user_email

        email = get_current_user_email()
        if email:
            return f"email:{email.strip().lower()}"

        local_email = _load_local_quota_email()
        if local_email:
            return f"email:{local_email}"

        api_key = get_current_api_key()
        if api_key:
            # API Key 使用与 MCP 用户表一致的 sha256:<digest> 格式，便于运维对照。
            return f"api_key:{_hash_api_key(api_key)}"

        return None


class SQLiteQuotaStore:
    """基于 SQLite 的 MCP 限额存储。

    SQLite 表按“服务 + 北京时间日期 + 身份哈希”做唯一键。调用前使用
    BEGIN IMMEDIATE 获取写锁，确保同一台机器上的并发 MCP 请求不会超卖次数。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _default_sqlite_path()

    async def reserve(self, policy: QuotaPolicy, identity: str) -> tuple[bool, dict[str, Any]]:
        """尝试占用一次调用次数，超限时返回 allowed=False。"""
        now = datetime.now(UTC)
        identity_type, identity_key, identity_hash = _identity_public_parts(identity)
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                effective_limit = self._effective_daily_limit(conn, policy, identity_type, identity_key)
                calls, failures = self._read_or_create_record(
                    conn,
                    policy,
                    identity_type,
                    identity_key,
                    identity_hash,
                    now,
                )
                if calls >= effective_limit:
                    conn.commit()
                    return False, _snapshot(policy.service, effective_limit, calls, failures, now)

                calls += 1
                self._update_record(
                    conn,
                    policy,
                    identity_key,
                    identity_hash,
                    calls,
                    failures,
                    effective_limit,
                    now,
                )
                conn.commit()
                return True, _snapshot(policy.service, effective_limit, calls, failures, now)
        except QuotaUnavailableError:
            raise
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    async def refund_failure(self, policy: QuotaPolicy, identity: str) -> dict[str, Any]:
        """业务失败后退回一次 calls，并累计 failures。"""
        now = datetime.now(UTC)
        identity_type, identity_key, identity_hash = _identity_public_parts(identity)
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                effective_limit = self._effective_daily_limit(conn, policy, identity_type, identity_key)
                calls, failures = self._read_or_create_record(
                    conn,
                    policy,
                    identity_type,
                    identity_key,
                    identity_hash,
                    now,
                )
                calls = max(calls - 1, 0)
                failures += 1
                self._update_record(
                    conn,
                    policy,
                    identity_key,
                    identity_hash,
                    calls,
                    failures,
                    effective_limit,
                    now,
                )
                conn.commit()
                return _snapshot(policy.service, effective_limit, calls, failures, now)
        except QuotaUnavailableError:
            raise
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    async def snapshot(self, policy: QuotaPolicy, identity: str) -> dict[str, Any]:
        """读取当前身份的额度快照，不占用次数。"""
        now = datetime.now(UTC)
        identity_type, identity_key, identity_hash = _identity_public_parts(identity)
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                effective_limit = self._effective_daily_limit(conn, policy, identity_type, identity_key)
                calls, failures = self._read_or_create_record(
                    conn,
                    policy,
                    identity_type,
                    identity_key,
                    identity_hash,
                    now,
                )
                conn.commit()
                return _snapshot(policy.service, effective_limit, calls, failures, now)
        except QuotaUnavailableError:
            raise
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    async def upsert_bonus_daily_limit(self, service: str, email: str, bonus_daily_limit: int) -> None:
        """写入某服务某邮箱的长期日加额记录。"""
        if bonus_daily_limit < 0:
            raise ValueError("bonus_daily_limit 不能为负数")

        now = datetime.now(UTC)
        normalized_email = email.strip().lower()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO mcp_quota_bonus_daily (
                        service, email, bonus_daily_limit, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(service, email) DO UPDATE SET
                        bonus_daily_limit = excluded.bonus_daily_limit,
                        updated_at = excluded.updated_at
                    """,
                    (
                        service,
                        normalized_email,
                        bonus_daily_limit,
                        _updated_at_iso(now),
                        _updated_at_iso(now),
                    ),
                )
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    def _connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接并确保基础表存在。"""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")
            self._ensure_schema(conn)
            return conn
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """初始化每日限额记录表。"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_quota_daily (
                service TEXT NOT NULL,
                day TEXT NOT NULL,
                identity_hash TEXT NOT NULL,
                identity_type TEXT NOT NULL,
                identity_key TEXT NOT NULL DEFAULT '',
                calls INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                limit_count INTEGER NOT NULL,
                reset_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, day, identity_hash)
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mcp_quota_daily)")}
        if "identity_key" not in columns:
            # 兼容早期 SQLite 方案创建的本地库，新增可对照身份字段。
            conn.execute("ALTER TABLE mcp_quota_daily ADD COLUMN identity_key TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_quota_bonus_daily (
                service TEXT NOT NULL,
                email TEXT NOT NULL,
                bonus_daily_limit INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, email)
            )
            """
        )

    def _read_or_create_record(
        self,
        conn: sqlite3.Connection,
        policy: QuotaPolicy,
        identity_type: str,
        identity_key: str,
        identity_hash: str,
        now: datetime,
    ) -> tuple[int, int]:
        """读取当前日记录，不存在时创建空记录。"""
        day = _beijing_day_key(now)
        row = conn.execute(
            """
            SELECT calls, failures
            FROM mcp_quota_daily
            WHERE service = ? AND day = ? AND identity_hash = ?
            """,
            (policy.service, day, identity_hash),
        ).fetchone()
        if row:
            return int(row["calls"]), int(row["failures"])

        conn.execute(
            """
            INSERT INTO mcp_quota_daily (
                service, day, identity_hash, identity_type, identity_key,
                calls, failures, limit_count, reset_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
            """,
            (
                policy.service,
                day,
                identity_hash,
                identity_type,
                identity_key,
                policy.daily_limit,
                _reset_at_iso(now),
                _updated_at_iso(now),
            ),
        )
        return 0, 0

    def _update_record(
        self,
        conn: sqlite3.Connection,
        policy: QuotaPolicy,
        identity_key: str,
        identity_hash: str,
        calls: int,
        failures: int,
        effective_limit: int,
        now: datetime,
    ) -> None:
        """更新调用次数、失败次数和当前策略快照。"""
        conn.execute(
            """
            UPDATE mcp_quota_daily
            SET identity_key = ?, calls = ?, failures = ?, limit_count = ?, reset_at = ?, updated_at = ?
            WHERE service = ? AND day = ? AND identity_hash = ?
            """,
            (
                identity_key,
                calls,
                failures,
                effective_limit,
                _reset_at_iso(now),
                _updated_at_iso(now),
                policy.service,
                _beijing_day_key(now),
                identity_hash,
            ),
        )

    def _effective_daily_limit(
        self,
        conn: sqlite3.Connection,
        policy: QuotaPolicy,
        identity_type: str,
        identity_key: str,
    ) -> int:
        """返回基础额度叠加长期日加额后的实际日额度。"""
        if identity_type != "email":
            return policy.daily_limit
        row = conn.execute(
            """
            SELECT bonus_daily_limit
            FROM mcp_quota_bonus_daily
            WHERE service = ? AND email = ?
            """,
            (policy.service, identity_key.strip().lower()),
        ).fetchone()
        bonus_daily_limit = int(row["bonus_daily_limit"]) if row else 0
        return policy.daily_limit + bonus_daily_limit


class QuotaLimiter:
    """MCP Tool 限额编排器。

    该类只依赖策略表、存储协议和身份解析器，便于测试注入内存存储，
    也便于后续从 OPS 后端动态加载更灵活的策略。
    """

    def __init__(
        self,
        *,
        policies: dict[str, QuotaPolicy],
        store: QuotaStore,
        identity_resolver: QuotaIdentityResolver | Callable[[], str | None] | None = None,
    ) -> None:
        self.policies = policies
        self.store = store
        self.identity_resolver = identity_resolver or QuotaIdentityResolver()

    async def before_call(self, tool_name: str) -> QuotaDecision:
        """在真实工具执行前检查并占用限额。"""
        policy = self.policies.get(tool_name)
        if not policy:
            return QuotaDecision(allowed=True)

        identity = self._resolve_identity()
        if not identity:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_IDENTITY_MISSING",
                    "无法识别当前 MCP 调用用户，已阻断受限服务调用",
                    _empty_snapshot(policy),
                ),
            )

        try:
            allowed, snapshot = await self.store.reserve(policy, identity)
        except QuotaUnavailableError as exc:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_UNAVAILABLE",
                    f"限额服务不可用：{exc}",
                    _empty_snapshot(policy),
                ),
            )

        if not allowed:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_EXCEEDED",
                    "已超出当前服务的每日调用限额",
                    snapshot,
                ),
            )

        return QuotaDecision(
            allowed=True,
            ticket=QuotaTicket(policy=policy, identity=identity, snapshot=snapshot),
        )

    async def after_call(self, ticket: QuotaTicket | None, response: dict[str, Any]) -> dict[str, Any]:
        """真实工具返回后结算限额并补充 quota 元信息。"""
        if not ticket:
            return response

        snapshot = ticket.snapshot
        if response.get("success") is False:
            try:
                snapshot = await self.store.refund_failure(ticket.policy, ticket.identity)
            except QuotaUnavailableError:
                # 失败退回阶段 SQLite 异常不覆盖原业务错误，只返回占用时快照。
                snapshot = ticket.snapshot
        response["quota"] = snapshot
        return response

    async def after_exception(self, ticket: QuotaTicket | None) -> None:
        """真实工具抛出异常时退回限额后继续向外抛出原异常。"""
        if not ticket:
            return
        try:
            await self.store.refund_failure(ticket.policy, ticket.identity)
        except QuotaUnavailableError:
            pass

    async def quota_snapshot(self, tool_name: str, identity: str | None = None) -> dict[str, Any]:
        """读取某个受限工具当前身份的额度快照。"""
        policy = self.policies.get(tool_name)
        if not policy:
            raise ValueError(f"未配置限额策略：{tool_name}")

        resolved_identity = identity or self._resolve_identity()
        if not resolved_identity:
            raise ValueError("无法识别当前 MCP 调用用户，无法读取额度")

        return await self.store.snapshot(policy, resolved_identity)

    def _resolve_identity(self) -> str | None:
        """兼容对象解析器和函数解析器两种 DI 形式。"""
        if callable(self.identity_resolver) and not hasattr(self.identity_resolver, "resolve"):
            return self.identity_resolver()
        return self.identity_resolver.resolve()  # type: ignore[union-attr]


def default_quota_policies() -> dict[str, QuotaPolicy]:
    """返回当前启用的 MCP Tool 限额策略。"""
    return {
        "seller_sprite_run": QuotaPolicy(
            tool_name="seller_sprite_run",
            service="seller_sprite",
            daily_limit=5,
        ),
        # 预留后续服务接入点：xiyou_run / sif_run 暂不启用。
    }


def load_quota_config(path: str | Path | None = None) -> QuotaConfig:
    """读取 MCP 限额配置文件。

    配置文件只覆盖代码默认策略，缺失时继续使用默认 seller_sprite_run=5。
    读取优先级为：显式 path、环境变量、工作目录 configs、项目 configs、用户配置目录。
    """
    config_path = Path(path).expanduser() if path else _find_quota_config_path()
    if not config_path or not config_path.exists():
        return QuotaConfig(
            enabled=True,
            sqlite_path=None,
            policies=default_quota_policies(),
            path=None,
        )

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"MCP 限额配置读取失败: {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"MCP 限额配置必须是 JSON object: {config_path}")

    return QuotaConfig(
        enabled=bool(payload.get("enabled", True)),
        sqlite_path=_parse_sqlite_path(payload.get("sqlite_path")),
        policies=_merge_policy_config(payload.get("policies", {})),
        path=config_path,
    )


_default_limiter: QuotaLimiter | None = None


def get_quota_limiter() -> QuotaLimiter:
    """获取默认限额编排器，供 MCP Tool 注册切面使用。"""
    global _default_limiter
    if _default_limiter is None:
        config = load_quota_config()
        sqlite_path = os.environ.get(ENV_SQLITE_PATH) or config.sqlite_path
        _default_limiter = QuotaLimiter(
            policies=config.policies if config.enabled and _quota_enabled() else {},
            store=SQLiteQuotaStore(sqlite_path),
        )
    return _default_limiter


def _quota_enabled() -> bool:
    """读取限额总开关，默认启用。"""
    value = os.environ.get(ENV_QUOTA_ENABLED, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _default_sqlite_path() -> Path:
    """返回默认 SQLite 限额库路径。"""
    from opscli.config import CONFIG_DIR

    return Path(CONFIG_DIR) / "mcp_quota" / "quota.sqlite3"


def _default_quota_config_path() -> Path:
    """返回用户级限额配置文件路径。"""
    from opscli.config import CONFIG_DIR

    return Path(CONFIG_DIR) / "mcp_quota" / "config.json"


def _find_quota_config_path() -> Path | None:
    """按运行时优先级查找限额配置文件。"""
    env_path = os.environ.get(ENV_QUOTA_CONFIG_PATH)
    if env_path:
        return Path(env_path).expanduser()

    for candidate in (
        _working_directory_quota_config_path(),
        _project_quota_config_path(),
        _default_quota_config_path(),
        _packaged_quota_config_path(),
    ):
        if candidate.exists():
            return candidate
    return None


def _working_directory_quota_config_path() -> Path:
    """返回当前启动工作目录下的限额配置文件路径。"""
    return Path.cwd() / "configs" / "mcp-quota.json"


def _project_quota_config_path() -> Path:
    """返回项目根目录下的限额配置文件路径。"""
    return Path(__file__).resolve().parents[2] / "configs" / "mcp-quota.json"


def _packaged_quota_config_path() -> Path:
    """返回随 Python 包分发的默认限额配置路径。"""
    return Path(__file__).resolve().parent / "configs" / "mcp-quota.json"


def _parse_sqlite_path(value: Any) -> Path | None:
    """解析配置文件中的 SQLite 路径。"""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("MCP 限额配置 sqlite_path 必须是字符串")
    return Path(value).expanduser()


def _merge_policy_config(raw_policies: Any) -> dict[str, QuotaPolicy]:
    """将配置文件策略覆盖到代码默认策略上。"""
    policies = dict(default_quota_policies())
    if raw_policies in (None, ""):
        return policies
    if not isinstance(raw_policies, dict):
        raise ValueError("MCP 限额配置 policies 必须是对象")

    for tool_name, raw_policy in raw_policies.items():
        if not isinstance(tool_name, str) or not isinstance(raw_policy, dict):
            raise ValueError("MCP 限额配置 policies 每项必须是对象")

        if raw_policy.get("enabled", True) is False:
            policies.pop(tool_name, None)
            continue

        base = policies.get(tool_name)
        service = raw_policy.get("service") or (base.service if base else tool_name.removesuffix("_run"))
        daily_limit = raw_policy.get("daily_limit", base.daily_limit if base else None)
        if daily_limit is None:
            raise ValueError(f"MCP 限额配置缺少 daily_limit: {tool_name}")
        daily_limit = int(daily_limit)
        if daily_limit <= 0:
            raise ValueError(f"MCP 限额 daily_limit 必须大于 0: {tool_name}")

        policies[tool_name] = QuotaPolicy(
            tool_name=tool_name,
            service=str(service),
            daily_limit=daily_limit,
        )
    return policies


def _load_local_quota_email() -> str | None:
    """从当前请求对应的本地凭证中恢复邮箱。"""
    from opscli.auth.storage.credential_store import CredentialStore
    from opscli.mcp.tools.helpers import _get_credential_dir

    try:
        cred_dir = _get_credential_dir()
        store = CredentialStore(base_dir=cred_dir) if cred_dir else CredentialStore()
        data = store.load()
    except Exception:
        return None

    email = data.get("email") if data else None
    if not email:
        return None
    return str(email).strip().lower()


def _beijing_day_key(moment: datetime | None = None) -> str:
    """返回北京时间自然日 key，格式 yyyyMMdd。"""
    current = moment or datetime.now(UTC)
    return current.astimezone(BEIJING_TZ).strftime("%Y%m%d")


def _seconds_until_next_beijing_day(moment: datetime | None = None) -> int:
    """计算距离下一个北京时间零点的秒数。"""
    current = (moment or datetime.now(UTC)).astimezone(BEIJING_TZ)
    next_day = datetime.combine(
        current.date() + timedelta(days=1),
        time.min,
        tzinfo=BEIJING_TZ,
    )
    return max(int((next_day - current).total_seconds()), 1)


def _hash_api_key(api_key: str) -> str:
    """按 MCP 用户表格式计算 API Key 哈希。"""
    return "sha256:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _identity_public_parts(identity: str) -> tuple[str, str, str]:
    """返回身份类型、可对照身份键和内部主键哈希。"""
    identity_type, identity_key = identity.split(":", 1) if ":" in identity else ("unknown", identity)
    identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return identity_type, identity_key, identity_hash


def _reset_at_iso(moment: datetime) -> str:
    """返回下一个北京时间零点的 ISO 时间。"""
    current = moment.astimezone(BEIJING_TZ)
    reset_at = datetime.combine(
        current.date() + timedelta(days=1),
        time.min,
        tzinfo=BEIJING_TZ,
    )
    return reset_at.isoformat()


def _updated_at_iso(moment: datetime) -> str:
    """返回当前北京时间 ISO 时间，便于排查每日记录更新时间。"""
    return moment.astimezone(BEIJING_TZ).isoformat()


def _snapshot(service: str, limit: int, calls: int, failures: int, moment: datetime) -> dict[str, Any]:
    """生成 MCP 响应中的 quota 元信息。"""
    return {
        "service": service,
        "limit": limit,
        "used": calls,
        "remaining": max(limit - calls, 0),
        "failures": failures,
        "reset_at": _reset_at_iso(moment),
    }


def _empty_snapshot(policy: QuotaPolicy) -> dict[str, Any]:
    """生成未能读取 SQLite 时的保守 quota 元信息。"""
    return _snapshot(policy.service, policy.daily_limit, 0, 0, datetime.now(UTC))


def _error_response(code: str, message: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """生成限额类 MCP 错误响应。"""
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message},
        "quota": snapshot,
    }
