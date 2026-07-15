"""卖家精灵账号登录与故障事件的脱敏日志和 SQLite 审计。"""

from __future__ import annotations

import logging
import re
from typing import Any

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.services.account_pool import (
    mask_seller_sprite_username,
    seller_sprite_account_key,
)
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore


MAX_ERROR_SUMMARY_LENGTH = 500
logger = logging.getLogger(__name__)


class SellerSpriteAccountEventRecorder:
    """以固定白名单字段记录账号登录与故障事件。"""

    def __init__(self, *, store: SellerSpriteTaskQueueStore) -> None:
        self.store = store

    def record_login_failure(
        self,
        *,
        account: SellerSpriteAccount,
        job_id: str,
        worker_key: str,
        assignment_generation: int,
        execution_mode: str,
        login_stage: str,
        error: Exception,
        duration_ms: int,
        failover_count: int,
        next_action: str,
    ) -> None:
        """记录一次首次登录、重登或备用接替登录失败。"""
        event_type = "account_relogin_failed" if login_stage == "relogin" else "account_login_failed"
        event = {
            "event_type": event_type,
            "account_key": seller_sprite_account_key(account),
            "account_name": account.name,
            "masked_username": mask_seller_sprite_username(account.username),
            "job_id": job_id,
            "worker_key": worker_key,
            "assignment_generation": assignment_generation,
            "execution_mode": execution_mode,
            "login_stage": login_stage,
            "error_code": _error_code(error),
            "error_summary": _sanitize_error_summary(error, account),
            "replacement_account_key": None,
            "duration_ms": max(0, int(duration_ms)),
            "failover_count": max(0, int(failover_count)),
            "next_action": next_action,
            "metadata": {"reason": login_stage},
        }
        # 运行日志先于 SQLite 审计写入，确保数据库不可用时仍保留排障线索。
        logger.warning("卖家精灵账号登录失败", extra={"seller_sprite_event": dict(event)})
        try:
            self.store.record_account_event(**event)
        except Exception as audit_error:
            # 审计属于诊断旁路，失败时不得覆盖调用方正在处理的账号登录错误。
            audit_event = {
                "event_type": "account_audit_persistence_failed",
                "job_id": job_id,
                "worker_key": worker_key,
                "assignment_generation": assignment_generation,
                "error_code": type(audit_error).__name__,
                "error_summary": _sanitize_generic_summary(audit_error),
            }
            logger.error(
                "卖家精灵账号审计写入失败",
                extra={"seller_sprite_event": audit_event},
            )

    def record_account_fetch_failure(
        self,
        *,
        error: Exception,
        next_action: str,
    ) -> None:
        """记录账号接口刷新失败，保留脱敏运行日志和 SQLite 审计。"""
        event = {
            "event_type": "account_fetch_failed",
            "account_key": None,
            "account_name": None,
            "masked_username": None,
            "job_id": None,
            "worker_key": None,
            "assignment_generation": None,
            "execution_mode": None,
            "login_stage": "account_fetch",
            "error_code": _error_code(error),
            "error_summary": _sanitize_generic_summary(error),
            "replacement_account_key": None,
            "duration_ms": None,
            "failover_count": None,
            "next_action": next_action,
            "metadata": {"reason": "account_fetch"},
        }
        logger.warning("卖家精灵账号接口刷新失败", extra={"seller_sprite_event": dict(event)})
        try:
            self.store.record_account_event(**event)
        except Exception as audit_error:
            logger.error(
                "卖家精灵账号接口失败事件写入 SQLite 失败",
                extra={
                    "seller_sprite_event": {
                        "event_type": "account_audit_persistence_failed",
                        "error_code": _error_code(audit_error),
                        "error_summary": _sanitize_generic_summary(audit_error),
                    }
                },
            )

    def record_session_state_change(
        self,
        *,
        account: SellerSpriteAccount,
        previous_state: str,
        state: str,
        reason: str,
        session_age_seconds: int,
        idle_seconds: int,
        task_count: int,
        is_busy: bool,
        error_code: str | None = None,
    ) -> None:
        """记录一次 browser-route 会话状态变化及其脱敏生命周期指标。"""
        metadata = {
            "previous_state": previous_state,
            "state": state,
            "reason": reason,
            "session_age_seconds": max(0, int(session_age_seconds)),
            "idle_seconds": max(0, int(idle_seconds)),
            "task_count": max(0, int(task_count)),
            "is_busy": bool(is_busy),
        }
        event = {
            "event_type": "account_session_state_changed",
            "account_key": seller_sprite_account_key(account),
            "account_name": account.name,
            "masked_username": mask_seller_sprite_username(account.username),
            "job_id": None,
            "worker_key": None,
            "assignment_generation": None,
            "execution_mode": "browser-route",
            "login_stage": "session_lifecycle",
            "error_code": error_code,
            "error_summary": None,
            "replacement_account_key": None,
            "duration_ms": None,
            "failover_count": None,
            "next_action": reason,
            "metadata": metadata,
        }
        logger.info("卖家精灵 browser 会话状态变化", extra={"seller_sprite_event": dict(event)})
        try:
            self.store.record_account_event(**event)
        except Exception as audit_error:
            # 生命周期审计是诊断旁路，关闭或轮换流程不能因 SQLite 写入失败而中断。
            logger.error(
                "卖家精灵 browser 会话状态审计写入失败",
                extra={
                    "seller_sprite_event": {
                        "event_type": "account_audit_persistence_failed",
                        "account_key": seller_sprite_account_key(account),
                        "error_code": _error_code(audit_error),
                        "error_summary": _sanitize_generic_summary(audit_error),
                    }
                },
            )


def _error_code(error: Exception) -> str:
    """优先使用业务错误码，否则使用异常类型名。"""
    code = getattr(error, "code", None)
    return str(code or type(error).__name__)


def _sanitize_error_summary(error: Exception, account: SellerSpriteAccount) -> str:
    """移除账号明文和常见凭证键值后返回限长错误摘要。"""
    summary = str(error)
    for secret in (account.password, account.username):
        if secret:
            summary = summary.replace(secret, "***")
    return _sanitize_generic_summary(summary)


def _sanitize_generic_summary(error: Exception | str) -> str:
    """清理常见密码、Cookie、Token 和授权头键值。"""
    summary = str(error).replace("\r", " ").replace("\n", " ")
    credential_keys = (
        r"password|passwd|pwd|token|access_token|refresh_token|session_token|"
        r"cookie|authorization"
    )
    summary = re.sub(
        rf"(?i)([\"']?(?:{credential_keys})[\"']?\s*:\s*)[\"'][^\"']*[\"']",
        lambda match: f'{match.group(1)}"***"',
        summary,
    )
    summary = re.sub(
        rf"(?i)\b({credential_keys})\s*[:=]\s*[^\s,;}}\]]+",
        lambda match: f"{match.group(1)}=***",
        summary,
    )
    summary = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer ***", summary)
    return summary[:MAX_ERROR_SUMMARY_LENGTH]
