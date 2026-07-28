"""Xiyou token expiry notifications."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from opscli.xiyou.config import XiyouSettings, load_settings
from opscli.xiyou.credentials import decode_jwt_payload


DEFAULT_DEDUPE_MINUTES = 5
TOKEN_INVALID_CODES = {"TokenInvalid", "TokenExpired", "TokenFreeTrialExpired"}
DEFAULT_NOTIFY_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=397e7465-06ab-4a65-8844-22822e3ac0bb"
DEFAULT_NOTIFY_MENTIONED_MOBILE_LIST = ()


@dataclass(frozen=True)
class XiyouNotifyConfig:
    """Built-in notification config for Xiyou auth failures."""

    path: Path
    webhook_url: str | None = None
    mentioned_list: tuple[str, ...] = ()
    mentioned_mobile_list: tuple[str, ...] = ()
    mention_all: bool = False
    quick_login_url: str | None = None
    dedupe_minutes: int = DEFAULT_DEDUPE_MINUTES
    source: str = "builtin"

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    @property
    def state_path(self) -> Path:
        return self.path / "notify_state.json"


def load_notify_config(settings: XiyouSettings | None = None) -> XiyouNotifyConfig:
    """Return the built-in notification config."""
    active_settings = settings or load_settings()
    return XiyouNotifyConfig(
        path=active_settings.credential_path.expanduser().parent,
        webhook_url=DEFAULT_NOTIFY_WEBHOOK_URL,
        mentioned_mobile_list=DEFAULT_NOTIFY_MENTIONED_MOBILE_LIST,
        dedupe_minutes=DEFAULT_DEDUPE_MINUTES,
        source="builtin",
    )


def notify_token_required(
    *,
    reason: str,
    status_code: int | None = None,
    business_code: str | None = None,
    job_id: str | None = None,
    expires_at: str | None = None,
    settings: XiyouSettings | None = None,
    http_post: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Send a token-expiry notification with dedupe protection."""
    active_settings = settings or load_settings()
    config = load_notify_config(active_settings)
    if not config.enabled:
        return {"sent": False, "reason": "not_configured"}
    dedupe_key = _dedupe_key(reason, status_code, business_code)
    if not force and _is_deduped(config, dedupe_key):
        return {"sent": False, "reason": "deduped", "dedupe_key": dedupe_key}
    payload = _build_text_payload(
        config=config,
        reason=reason,
        status_code=status_code,
        business_code=business_code,
        expires_at=expires_at or _current_expires_at(active_settings),
        job_id=job_id,
    )
    result = _send_wecom(config, payload, http_post=http_post)
    if not result["sent"]:
        return result
    if not force:
        _mark_notified(config, dedupe_key)
    return {"sent": True, "dedupe_key": dedupe_key}


def _send_wecom(
    config: XiyouNotifyConfig,
    payload: dict[str, Any],
    *,
    http_post: Any | None = None,
) -> dict[str, Any]:
    """Send to WeCom and normalize common error shapes."""
    try:
        post = http_post or httpx.post
        response = post(config.webhook_url, json=payload, timeout=5.0)
        status = getattr(response, "status_code", 200)
        text = getattr(response, "text", "")
        if status >= 400:
            return {"sent": False, "reason": "http_error", "status_code": status, "response": text[:500]}
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict) and int(body.get("errcode") or 0) != 0:
            return {
                "sent": False,
                "reason": "wecom_error",
                "errcode": body.get("errcode"),
                "errmsg": body.get("errmsg"),
            }
    except Exception as exc:
        return {"sent": False, "reason": "send_failed", "error": str(exc)}
    return {"sent": True}


def is_token_invalid_signal(status_code: int | None, business_code: Any) -> bool:
    """Return whether the response indicates an invalid Xiyou token."""
    return status_code == 401 or str(business_code or "") in TOKEN_INVALID_CODES


def _build_text_payload(
    *,
    config: XiyouNotifyConfig,
    reason: str,
    status_code: int | None,
    business_code: str | None,
    expires_at: str | None,
    job_id: str | None,
) -> dict[str, Any]:
    lines = [
        "西柚 token 失效/即将过期",
        f"原因：{reason}",
        f"HTTP 状态：{status_code if status_code is not None else '-'}",
        f"业务码：{business_code or '-'}",
        f"当前过期时间：{expires_at or '-'}",
        f"阻塞业务：{job_id or '-'}",
    ]
    if config.quick_login_url:
        lines.append(f"运营后台补登：{config.quick_login_url}")
    else:
        lines.append("处理方式：登录运营系统后台，人工更新西柚 token/cookie。")
    return _wecom_text_payload(config, "\n".join(lines))


def _wecom_text_payload(config: XiyouNotifyConfig, content: str) -> dict[str, Any]:
    text: dict[str, Any] = {"content": content}
    if config.mentioned_list:
        text["mentioned_list"] = list(config.mentioned_list)
    if config.mentioned_mobile_list:
        text["mentioned_mobile_list"] = list(config.mentioned_mobile_list)
    return {"msgtype": "text", "text": text}


def _is_deduped(config: XiyouNotifyConfig, key: str) -> bool:
    state = _read_state(config.state_path)
    last_sent_at = state.get(key)
    if not isinstance(last_sent_at, (int, float)):
        return False
    return time.time() - float(last_sent_at) < config.dedupe_minutes * 60


def _mark_notified(config: XiyouNotifyConfig, key: str) -> None:
    state_path = config.state_path
    state = _read_state(state_path)
    state[key] = time.time()
    _write_state(state_path, state)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.replace(tmp_path, path)
    except PermissionError:
        path.write_text(tmp_path.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _dedupe_key(reason: str, status_code: int | None, business_code: str | None) -> str:
    if reason == "jwt_expired" or is_token_invalid_signal(status_code, business_code):
        return "token_required"
    return f"{reason}:{status_code or ''}:{business_code or ''}"


def _current_expires_at(active_settings: XiyouSettings) -> str | None:
    if not active_settings.authorization:
        return None
    try:
        payload = decode_jwt_payload(active_settings.authorization)
        exp = payload.get("exp")
        if isinstance(exp, int):
            return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
    except Exception:
        return None
    return None
