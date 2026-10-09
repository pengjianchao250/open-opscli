"""MySQL implementation of the MCP quota store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

from opscli.mcp.quota import (
    BEIJING_TZ,
    QuotaPolicy,
    QuotaUnavailableError,
    _identity_public_parts,
    _snapshot,
)
from opscli.shared.collection_storage.config import MySqlSettings


SCHEMA_VERSION = 1


class MySqlQuotaStore:
    """Persist quota policy and counters in MySQL with row-level locking."""

    def __init__(
        self,
        *,
        settings: MySqlSettings,
        connect_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._connect_factory = connect_factory or self._connect

    async def get_policy(self, tool_name: str) -> QuotaPolicy | None:
        try:
            connection = self._connect_factory()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT tool_name, service, daily_limit, enabled, timezone
                        FROM mcp_quota_policy
                        WHERE tool_name = %s
                        """,
                        (tool_name,),
                    )
                    row = cursor.fetchone()
            finally:
                connection.close()
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

        if row is None or int(row.get("enabled") or 0) == 0:
            return None
        return _policy(row)

    async def reserve(
        self,
        policy: QuotaPolicy,
        identity: str,
    ) -> tuple[bool, dict[str, Any]]:
        now = datetime.now(UTC)

        def operation(cursor: Any) -> tuple[bool, dict[str, Any]]:
            identity_type, identity_key, identity_hash = _identity_public_parts(identity)
            effective_limit = self._effective_daily_limit(
                cursor,
                policy,
                identity_type,
                identity_key,
            )
            calls, failures = self._lock_daily_record(
                cursor,
                policy=policy,
                identity_type=identity_type,
                identity_key=identity_key,
                identity_hash=identity_hash,
                effective_limit=effective_limit,
                now=now,
            )
            if calls >= effective_limit:
                return False, _snapshot(
                    policy.service,
                    effective_limit,
                    calls,
                    failures,
                    now,
                )
            calls += 1
            self._update_daily_record(
                cursor,
                policy=policy,
                identity_key=identity_key,
                identity_hash=identity_hash,
                calls=calls,
                failures=failures,
                effective_limit=effective_limit,
                now=now,
            )
            return True, _snapshot(
                policy.service,
                effective_limit,
                calls,
                failures,
                now,
            )

        return self._transaction(operation)

    async def refund_failure(
        self,
        policy: QuotaPolicy,
        identity: str,
    ) -> dict[str, Any]:
        return self._refund(policy, identity, record_failure=True)

    async def refund_cached_call(
        self,
        policy: QuotaPolicy,
        identity: str,
    ) -> dict[str, Any]:
        return self._refund(policy, identity, record_failure=False)

    async def snapshot(
        self,
        policy: QuotaPolicy,
        identity: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)

        def operation(cursor: Any) -> dict[str, Any]:
            identity_type, identity_key, identity_hash = _identity_public_parts(identity)
            effective_limit = self._effective_daily_limit(
                cursor,
                policy,
                identity_type,
                identity_key,
            )
            calls, failures = self._lock_daily_record(
                cursor,
                policy=policy,
                identity_type=identity_type,
                identity_key=identity_key,
                identity_hash=identity_hash,
                effective_limit=effective_limit,
                now=now,
            )
            return _snapshot(
                policy.service,
                effective_limit,
                calls,
                failures,
                now,
            )

        return self._transaction(operation)

    async def upsert_bonus_daily_limit(
        self,
        service: str,
        email: str,
        bonus_daily_limit: int,
    ) -> None:
        if bonus_daily_limit < 0:
            raise ValueError("bonus_daily_limit cannot be negative")
        try:
            connection = self._connect_factory()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO mcp_quota_bonus_daily (
                            service, email, bonus_daily_limit
                        )
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            bonus_daily_limit = VALUES(bonus_daily_limit)
                        """,
                        (
                            service.strip(),
                            email.strip().lower(),
                            int(bonus_daily_limit),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    def check_schema(self) -> None:
        try:
            connection = self._connect_factory()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT schema_version FROM mcp_quota_schema_versions
                        WHERE module_name = %s
                        """,
                        ("mcp_quota",),
                    )
                    row = cursor.fetchone()
            finally:
                connection.close()
        except Exception as exc:
            raise QuotaUnavailableError("MySQL quota schema is unavailable") from exc
        version = int(row.get("schema_version") or 0) if row else 0
        if version != SCHEMA_VERSION:
            raise QuotaUnavailableError(
                f"MySQL quota schema version mismatch: expected {SCHEMA_VERSION}, got {version}"
            )

    def _refund(
        self,
        policy: QuotaPolicy,
        identity: str,
        *,
        record_failure: bool,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)

        def operation(cursor: Any) -> dict[str, Any]:
            identity_type, identity_key, identity_hash = _identity_public_parts(identity)
            effective_limit = self._effective_daily_limit(
                cursor,
                policy,
                identity_type,
                identity_key,
            )
            calls, failures = self._lock_daily_record(
                cursor,
                policy=policy,
                identity_type=identity_type,
                identity_key=identity_key,
                identity_hash=identity_hash,
                effective_limit=effective_limit,
                now=now,
            )
            calls = max(calls - 1, 0)
            if record_failure:
                failures += 1
            self._update_daily_record(
                cursor,
                policy=policy,
                identity_key=identity_key,
                identity_hash=identity_hash,
                calls=calls,
                failures=failures,
                effective_limit=effective_limit,
                now=now,
            )
            return _snapshot(
                policy.service,
                effective_limit,
                calls,
                failures,
                now,
            )

        return self._transaction(operation)

    def _transaction(self, operation: Callable[[Any], Any]) -> Any:
        try:
            connection = self._connect_factory()
            try:
                with connection.cursor() as cursor:
                    result = operation(cursor)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        except QuotaUnavailableError:
            raise
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

    def _lock_daily_record(
        self,
        cursor: Any,
        *,
        policy: QuotaPolicy,
        identity_type: str,
        identity_key: str,
        identity_hash: str,
        effective_limit: int,
        now: datetime,
    ) -> tuple[int, int]:
        quota_day = now.astimezone(BEIJING_TZ).date()
        cursor.execute(
            """
            INSERT INTO mcp_quota_daily (
                service, quota_day, identity_hash, identity_type, identity_key,
                calls, failures, limit_count, reset_at
            )
            VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s)
            ON DUPLICATE KEY UPDATE
                identity_type = VALUES(identity_type),
                identity_key = VALUES(identity_key)
            """,
            (
                policy.service,
                quota_day,
                identity_hash,
                identity_type,
                identity_key,
                effective_limit,
                _mysql_reset_at(now),
            ),
        )
        cursor.execute(
            """
            SELECT calls, failures
            FROM mcp_quota_daily
            WHERE service = %s AND quota_day = %s AND identity_hash = %s
            FOR UPDATE
            """,
            (policy.service, quota_day, identity_hash),
        )
        row = cursor.fetchone()
        if row is None:
            raise QuotaUnavailableError("MySQL quota daily record was not readable after upsert")
        return int(row.get("calls") or 0), int(row.get("failures") or 0)

    @staticmethod
    def _update_daily_record(
        cursor: Any,
        *,
        policy: QuotaPolicy,
        identity_key: str,
        identity_hash: str,
        calls: int,
        failures: int,
        effective_limit: int,
        now: datetime,
    ) -> None:
        cursor.execute(
            """
            UPDATE mcp_quota_daily
            SET identity_key = %s,
                calls = %s,
                failures = %s,
                limit_count = %s,
                reset_at = %s
            WHERE service = %s AND quota_day = %s AND identity_hash = %s
            """,
            (
                identity_key,
                calls,
                failures,
                effective_limit,
                _mysql_reset_at(now),
                policy.service,
                now.astimezone(BEIJING_TZ).date(),
                identity_hash,
            ),
        )

    @staticmethod
    def _effective_daily_limit(
        cursor: Any,
        policy: QuotaPolicy,
        identity_type: str,
        identity_key: str,
    ) -> int:
        if identity_type != "email":
            return policy.daily_limit
        cursor.execute(
            """
            SELECT bonus_daily_limit
            FROM mcp_quota_bonus_daily
            WHERE service = %s AND email = %s
            """,
            (policy.service, identity_key.strip().lower()),
        )
        row = cursor.fetchone()
        return policy.daily_limit + int(row.get("bonus_daily_limit") or 0) if row else policy.daily_limit

    def _connect(self) -> Any:
        if not self.settings.configured:
            raise QuotaUnavailableError("MySQL quota connection settings are incomplete")
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise QuotaUnavailableError("PyMySQL is required for MySQL quota storage") from exc
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            connect_timeout=self.settings.connect_timeout_seconds,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            ssl_ca=self.settings.ssl_ca or None,
            ssl_verify_cert=bool(self.settings.ssl_ca),
            ssl_verify_identity=bool(self.settings.ssl_ca),
        )


def _policy(row: dict[str, Any]) -> QuotaPolicy:
    tool_name = str(row.get("tool_name") or "").strip()
    service = str(row.get("service") or "").strip()
    timezone_name = str(row.get("timezone") or "").strip() or "Asia/Shanghai"
    try:
        daily_limit = int(row.get("daily_limit"))
    except (TypeError, ValueError) as exc:
        raise QuotaUnavailableError(f"Invalid quota daily_limit for {tool_name}") from exc
    if not tool_name or not service or daily_limit <= 0:
        raise QuotaUnavailableError(f"Invalid MySQL quota policy for {tool_name or '<empty>'}")
    return QuotaPolicy(
        tool_name=tool_name,
        service=service,
        daily_limit=daily_limit,
        timezone=timezone_name,
    )


def _mysql_reset_at(moment: datetime) -> datetime:
    current = moment.astimezone(BEIJING_TZ)
    reset_at = datetime.combine(
        current.date() + timedelta(days=1),
        time.min,
        tzinfo=BEIJING_TZ,
    )
    return reset_at.astimezone(UTC).replace(tzinfo=None)
