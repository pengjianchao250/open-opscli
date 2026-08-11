"""第三方 API 多账号凭据 MySQL Adapter。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any

from opscli.api_credentials.config import ApiCredentialMySqlSettings
from opscli.api_credentials.crypto import ApiKeyCipher
from opscli.api_credentials.models import (
    ACCOUNT_STATUSES,
    SUPPORTED_PROVIDERS,
    ApiCredentialAccount,
)
from opscli.api_credentials.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION


class ApiCredentialRepositoryError(RuntimeError):
    """API 凭据仓储操作失败。"""


class ApiCredentialSchemaError(ApiCredentialRepositoryError):
    """API 凭据表结构不存在或版本不兼容。"""


class MySqlApiCredentialRepository:
    """在 MySQL 中管理 Provider、账号、密钥版本和运行状态。"""

    def __init__(
        self,
        *,
        settings: ApiCredentialMySqlSettings,
        cipher: ApiKeyCipher,
        connect_factory: Callable[[], Any] | None = None,
    ) -> None:
        """创建 MySQL 凭据仓储。

        Args:
            settings: 独立的凭据数据库连接配置。
            cipher: API Key 信封加密器。
            connect_factory: 测试可注入的连接工厂。
        """
        self.settings = settings
        self.cipher = cipher
        self._connect_factory = connect_factory or self._connect

    def create_schema(self) -> None:
        """创建并核对 v1 表结构。

        Returns:
            无。

        Raises:
            ApiCredentialSchemaError: 数据库已有不兼容版本。
            Exception: DDL 或数据库事务执行失败。
        """
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                cursor.execute(
                    """
                    INSERT INTO api_credential_schema_versions (module_name, schema_version)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE schema_version = schema_version
                    """,
                    ("api_credentials", SCHEMA_VERSION),
                )
                cursor.execute(
                    """
                    SELECT schema_version FROM api_credential_schema_versions
                    WHERE module_name = %s
                    """,
                    ("api_credentials",),
                )
                version = _first_value(cursor.fetchone(), "schema_version")
                if version != SCHEMA_VERSION:
                    raise ApiCredentialSchemaError(
                        f"API 凭据表结构版本不兼容：期望 {SCHEMA_VERSION}，实际 {version}"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_account(
        self,
        *,
        provider: str,
        name: str,
        api_key: str,
        priority: int = 100,
        remark: str | None = None,
        actor: str | None = None,
    ) -> ApiCredentialAccount:
        """新增账号；同名账号存在时轮换其 API Key。

        Args:
            provider: 已支持的 Provider 标识。
            name: Provider 内唯一账号名称。
            api_key: 交互输入的明文 API Key。
            priority: 账号选择优先级，数值越小越优先。
            remark: 账号用途或负责人备注。
            actor: 写入审计日志的操作人。

        Returns:
            写入后的账号和当前密钥版本。

        Raises:
            ValueError: Provider、名称、Key 或优先级非法。
            Exception: 加密或数据库事务失败。
        """
        normalized_provider = _provider(provider)
        normalized_name = _required_text(name, "name")
        secret = _required_text(api_key, "api_key")
        # 账号元数据、当前密钥切换、运行状态和审计必须同事务提交，避免出现无密钥账号。
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id FROM api_provider_accounts
                    WHERE provider = %s AND account_name = %s
                    FOR UPDATE
                    """,
                    (normalized_provider, normalized_name),
                )
                row = cursor.fetchone()
                account_id = _first_value(row, "id")
                action = "account_updated"
                new_account = account_id is None
                if account_id is None:
                    cursor.execute(
                        """
                        INSERT INTO api_provider_accounts (
                            provider, account_name, status, priority, remark, created_by
                        ) VALUES (%s, %s, 'active', %s, %s, %s)
                        """,
                        (
                            normalized_provider,
                            normalized_name,
                            _positive_int(priority, "priority"),
                            _optional_text(remark),
                            _optional_text(actor),
                        ),
                    )
                    account_id = int(cursor.lastrowid)
                    action = "account_created"
                else:
                    account_id = int(account_id)
                    cursor.execute(
                        """
                        UPDATE api_provider_accounts
                        SET priority = %s, remark = %s,
                            updated_at = CURRENT_TIMESTAMP(6)
                        WHERE id = %s
                        """,
                        (
                            _positive_int(priority, "priority"),
                            _optional_text(remark),
                            account_id,
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO api_account_runtime (account_id) VALUES (%s)
                    ON DUPLICATE KEY UPDATE account_id = account_id
                    """,
                    (account_id,),
                )
                rotated = self._rotate_key(cursor, account_id=account_id, api_key=secret)
                self._audit(
                    cursor,
                    account_id=account_id,
                    action=action if new_account else ("credential_rotated" if rotated else action),
                    actor=actor,
                    detail={"provider": normalized_provider, "name": normalized_name},
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        account = self.get_account(account_id)
        if account is None:
            raise ApiCredentialRepositoryError("API 账号写入后无法读取")
        return account

    def rotate_key(self, account_id: int, api_key: str, *, actor: str | None = None) -> ApiCredentialAccount:
        """为已有账号创建新的活动密钥版本。

        Args:
            account_id: 待轮换账号 ID。
            api_key: 新的明文 API Key。
            actor: 写入审计日志的操作人。

        Returns:
            轮换后的账号和新密钥版本。

        Raises:
            ValueError: 账号不存在或 API Key 为空。
            Exception: 加密或数据库事务失败。
        """
        secret = _required_text(api_key, "api_key")
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM api_provider_accounts WHERE id = %s FOR UPDATE",
                    (int(account_id),),
                )
                if cursor.fetchone() is None:
                    raise ValueError(f"API 账号不存在：{account_id}")
                rotated = self._rotate_key(cursor, account_id=int(account_id), api_key=secret)
                if rotated:
                    self._audit(
                        cursor,
                        account_id=int(account_id),
                        action="credential_rotated",
                        actor=actor,
                        detail=None,
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        account = self.get_account(int(account_id))
        if account is None:
            raise ApiCredentialRepositoryError("API Key 轮换后账号无法读取")
        return account

    def get_account(self, account_id: int) -> ApiCredentialAccount | None:
        """按账号 ID 读取当前活动密钥和运行状态。

        Args:
            account_id: 账号内部 ID。

        Returns:
            账号存在时返回解密后的内部模型，否则返回 ``None``。
        """
        return self._fetch_one("a.id = %s", (int(account_id),))

    def get_account_by_name(self, provider: str, name: str) -> ApiCredentialAccount | None:
        """按 Provider 和账号名称读取账号。

        Args:
            provider: Provider 标识。
            name: Provider 内账号名称。

        Returns:
            匹配账号的内部模型，不存在时返回 ``None``。
        """
        return self._fetch_one(
            "a.provider = %s AND a.account_name = %s",
            (_provider(provider), _required_text(name, "name")),
        )

    def list_accounts(self, provider: str | None = None) -> list[ApiCredentialAccount]:
        """列出账号；内部结果包含调用所需的已解密 API Key。

        Args:
            provider: 可选 Provider 过滤条件。

        Returns:
            按 Provider、优先级和名称排序的账号列表。

        Raises:
            ValueError: Provider 不受支持。
        """
        where = "1 = 1"
        params: tuple[Any, ...] = ()
        if provider is not None:
            where = "a.provider = %s"
            params = (_provider(provider),)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"{_ACCOUNT_SELECT} WHERE {where} "
                    "ORDER BY a.provider, a.priority, a.account_name, a.id",
                    params,
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        return [self._row_to_account(row) for row in rows]

    def acquire(
        self,
        provider: str,
        *,
        exclude_account_ids: Iterable[int] | None = None,
    ) -> ApiCredentialAccount | None:
        """原子领取一个可用账号，并记录最近选择时间。

        Args:
            provider: Provider 标识。
            exclude_account_ids: 当前请求已经失败、不可再次选择的账号 ID。

        Returns:
            优先级最高且最久未选择的可用账号；没有候选时返回 ``None``。

        Raises:
            ValueError: Provider 不受支持。
            Exception: MySQL 选择或状态更新时间失败。
        """
        normalized_provider = _provider(provider)
        excluded = sorted({int(value) for value in (exclude_account_ids or ())})
        exclusion_sql = ""
        params: list[Any] = [normalized_provider]
        if excluded:
            exclusion_sql = f" AND a.id NOT IN ({','.join(['%s'] * len(excluded))})"
            params.extend(excluded)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                # SKIP LOCKED 让并发 worker 短暂避开正在领取的账号；事务内立即更新时间形成 LRU 次序。
                cursor.execute(
                    f"""
                    {_ACCOUNT_SELECT}
                    WHERE a.provider = %s AND a.status = 'active'
                      AND (r.cooldown_until IS NULL OR r.cooldown_until <= UTC_TIMESTAMP(6))
                      {exclusion_sql}
                    ORDER BY a.priority, r.last_selected_at IS NOT NULL,
                             r.last_selected_at, a.id
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                    """,
                    tuple(params),
                )
                row = cursor.fetchone()
                if row is None:
                    connection.rollback()
                    return None
                account_id = int(_value(row, "account_id"))
                cursor.execute(
                    """
                    UPDATE api_account_runtime
                    SET last_selected_at = UTC_TIMESTAMP(6)
                    WHERE account_id = %s
                    """,
                    (account_id,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_account(account_id)

    def next_due_exhausted(
        self,
        provider: str,
        *,
        exclude_account_ids: Iterable[int] | None = None,
    ) -> ApiCredentialAccount | None:
        """读取额度重置时间已到、需要复查的耗尽账号。

        Args:
            provider: Provider 标识。
            exclude_account_ids: 当前请求已经检查过的账号 ID。

        Returns:
            最早到期且超过一小时复查冷却的账号，否则返回 ``None``。
        """
        excluded = sorted({int(value) for value in (exclude_account_ids or ())})
        clauses = [
            "a.provider = %s",
            "a.status = 'exhausted'",
            "r.quota_reset_at IS NOT NULL",
            "r.quota_reset_at <= UTC_TIMESTAMP(6)",
            "(r.last_verified_at IS NULL OR r.last_verified_at <= UTC_TIMESTAMP(6) - INTERVAL 1 HOUR)",
        ]
        params: list[Any] = [_provider(provider)]
        if excluded:
            clauses.append(f"a.id NOT IN ({','.join(['%s'] * len(excluded))})")
            params.extend(excluded)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"{_ACCOUNT_SELECT} WHERE {' AND '.join(clauses)} "
                    "ORDER BY r.quota_reset_at, r.last_verified_at, a.id LIMIT 1",
                    tuple(params),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return self._row_to_account(row) if row else None

    def set_status(self, account_id: int, status: str, *, actor: str | None = None) -> None:
        """显式更新账号状态并写审计日志。

        Args:
            account_id: 账号内部 ID。
            status: 目标账号状态。
            actor: 操作人。

        Returns:
            无。

        Raises:
            ValueError: 状态非法或账号不存在。
        """
        normalized = str(status or "").strip().lower()
        if normalized not in ACCOUNT_STATUSES:
            raise ValueError(f"不支持的 API 账号状态：{status}")
        self._execute_account_update(
            "UPDATE api_provider_accounts SET status = %s WHERE id = %s",
            (normalized, int(account_id)),
            account_id=int(account_id),
            audit_action=f"account_{normalized}",
            actor=actor,
        )

    def update_runtime(self, account_id: int, values: Mapping[str, Any]) -> None:
        """按白名单更新账号运行状态。

        Args:
            account_id: 账号内部 ID。
            values: 额度、时间、失败计数或 Provider 元数据更新。

        Returns:
            无。

        Raises:
            ValueError: 包含未允许的运行状态字段或非法时间。
            Exception: MySQL 更新失败。
        """
        allowed = {
            "remaining_quota",
            "current_usage",
            "quota_reset_at",
            "last_selected_at",
            "last_used_at",
            "last_verified_at",
            "cooldown_until",
            "consecutive_failures",
            "last_error_code",
            "last_error_message",
            "provider_metadata",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"不支持的运行状态字段：{', '.join(sorted(unknown))}")
        if not values:
            return
        columns: list[str] = []
        params: list[Any] = []
        # 列名只能来自固定白名单；值继续使用参数绑定，避免动态 SQL 接受外部标识符。
        for key, value in values.items():
            columns.append(f"{key} = %s")
            params.append(_runtime_value(key, value))
        params.append(int(account_id))
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE api_account_runtime SET {', '.join(columns)} WHERE account_id = %s",
                    tuple(params),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _fetch_one(self, where: str, params: tuple[Any, ...]) -> ApiCredentialAccount | None:
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"{_ACCOUNT_SELECT} WHERE {where} LIMIT 1", params)
                row = cursor.fetchone()
        finally:
            connection.close()
        return self._row_to_account(row) if row else None

    def _rotate_key(self, cursor: Any, *, account_id: int, api_key: str) -> bool:
        """在账号行锁保护下原子撤销旧版本并插入新版本。"""
        fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        cursor.execute(
            """
            SELECT id, secret_fingerprint, secret_version
            FROM api_account_credentials
            WHERE account_id = %s AND status = 'active'
            ORDER BY secret_version DESC LIMIT 1 FOR UPDATE
            """,
            (account_id,),
        )
        current = cursor.fetchone()
        current_fingerprint = _first_value(current, "secret_fingerprint")
        current_id = _first_value(current, "id")
        current_version = int(_first_value(current, "secret_version") or 0)
        if current_fingerprint == fingerprint:
            return False
        version = current_version + 1
        encrypted = self.cipher.encrypt(api_key, account_id=account_id, version=version)
        # 先加密再撤销；任一步失败都由外层事务回滚，保证始终只有一个活动版本。
        if current_id is not None:
            cursor.execute(
                """
                UPDATE api_account_credentials
                SET status = 'revoked', revoked_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (int(current_id),),
            )
        cursor.execute(
            """
            INSERT INTO api_account_credentials (
                account_id, credential_type, secret_ciphertext, secret_nonce,
                encrypted_dek, dek_nonce, secret_masked, secret_fingerprint,
                secret_version, status, rotated_from_id
            ) VALUES (%s, 'api_key', %s, %s, %s, %s, %s, %s, %s, 'active', %s)
            """,
            (
                account_id,
                encrypted.ciphertext,
                encrypted.nonce,
                encrypted.encrypted_dek,
                encrypted.dek_nonce,
                encrypted.masked,
                encrypted.fingerprint,
                version,
                current_id,
            ),
        )
        return True

    def _row_to_account(self, row: Any) -> ApiCredentialAccount:
        account_id = int(_value(row, "account_id"))
        version = int(_value(row, "secret_version"))
        api_key = self.cipher.decrypt(
            bytes(_value(row, "secret_ciphertext")),
            bytes(_value(row, "secret_nonce")),
            bytes(_value(row, "encrypted_dek")),
            bytes(_value(row, "dek_nonce")),
            account_id=account_id,
            version=version,
        )
        return ApiCredentialAccount(
            account_id=account_id,
            provider=str(_value(row, "provider")),
            name=str(_value(row, "account_name")),
            api_key=api_key,
            api_key_masked=str(_value(row, "secret_masked")),
            secret_version=version,
            status=str(_value(row, "status")),
            priority=int(_value(row, "priority")),
            remark=_optional_text(_value(row, "remark")),
            remaining_quota=_optional_int(_value(row, "remaining_quota")),
            current_usage=_optional_int(_value(row, "current_usage")),
            quota_reset_at=_iso(_value(row, "quota_reset_at")),
            last_selected_at=_iso(_value(row, "last_selected_at")),
            last_used_at=_iso(_value(row, "last_used_at")),
            last_verified_at=_iso(_value(row, "last_verified_at")),
            cooldown_until=_iso(_value(row, "cooldown_until")),
            consecutive_failures=int(_value(row, "consecutive_failures") or 0),
            last_error_code=_optional_text(_value(row, "last_error_code")),
            last_error_message=_optional_text(_value(row, "last_error_message")),
            provider_metadata=_json_object(_value(row, "provider_metadata")),
        )

    def _execute_account_update(
        self,
        sql: str,
        params: tuple[Any, ...],
        *,
        account_id: int,
        audit_action: str,
        actor: str | None,
    ) -> None:
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute(sql, params)
                if not affected:
                    cursor.execute(
                        "SELECT id FROM api_provider_accounts WHERE id = %s",
                        (account_id,),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError(f"API 账号不存在：{account_id}")
                self._audit(
                    cursor,
                    account_id=account_id,
                    action=audit_action,
                    actor=actor,
                    detail=None,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _audit(
        cursor: Any,
        *,
        account_id: int,
        action: str,
        actor: str | None,
        detail: dict[str, Any] | None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO api_credential_audit_logs (account_id, action, actor, detail)
            VALUES (%s, %s, %s, %s)
            """,
            (
                account_id,
                action,
                _optional_text(actor),
                json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail else None,
            ),
        )

    def _connect(self) -> Any:
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 PyMySQL 依赖，无法连接 API 凭据 MySQL") from exc
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


_ACCOUNT_SELECT = """
SELECT
    a.id AS account_id, a.provider, a.account_name, a.status, a.priority,
    a.remark,
    c.secret_ciphertext, c.secret_nonce, c.encrypted_dek, c.dek_nonce,
    c.secret_masked, c.secret_version,
    r.remaining_quota, r.current_usage, r.quota_reset_at,
    r.last_selected_at, r.last_used_at, r.last_verified_at,
    r.cooldown_until, r.consecutive_failures, r.last_error_code, r.last_error_message,
    r.provider_metadata
FROM api_provider_accounts a
JOIN api_account_credentials c
  ON c.account_id = a.id AND c.status = 'active'
JOIN api_account_runtime r ON r.account_id = a.id
"""


def _provider(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized not in SUPPORTED_PROVIDERS:
        raise ValueError(f"不支持的 API Provider：{value}")
    return normalized


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} 不能为空")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _positive_int(value: Any, field: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{field} 必须大于 0")
    return parsed


def _value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    raise ApiCredentialRepositoryError(f"MySQL 游标必须返回字典行，缺少字段：{key}")


def _first_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(key)
    if isinstance(row, (tuple, list)) and row:
        return row[0]
    return None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _json_object(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _runtime_value(key: str, value: Any) -> Any:
    if key == "provider_metadata":
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
    if key in {"quota_reset_at", "last_selected_at", "last_used_at", "last_verified_at", "cooldown_until"}:
        if value is None:
            return value
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    if key in {"last_error_message", "last_error_code"} and value is not None:
        return str(value)[:500]
    return value
