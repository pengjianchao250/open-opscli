"""后台预取任务读取显式配置的服务凭证作用域。"""

from __future__ import annotations

from pathlib import Path

from opscli.shared.prefetch_schedule.config import PrefetchScheduleSettings


def load_prefetch_service_auth(
    settings: PrefetchScheduleSettings,
    *,
    required: bool,
) -> tuple[str | None, str | None]:
    """读取服务 CredentialStore 中的 OPS Session/JWT，不接受计划内凭证。"""
    scope = settings.service_credential_scope
    expected_email = settings.service_user_email
    if not scope:
        if required:
            raise ValueError(
                "预取任务缺少 OPSCLI_PREFETCH_SERVICE_CREDENTIAL_SCOPE 配置"
            )
        return None, None
    if not expected_email:
        raise ValueError("预取任务缺少 OPSCLI_PREFETCH_SERVICE_USER_EMAIL 配置")

    from opscli.mcp.credential_cache import get_credential_cache

    if scope == "default":
        base_dir = None
    else:
        base_dir = Path(scope).expanduser()
        if not base_dir.is_absolute():
            raise ValueError("预取服务凭证作用域必须是 default 或绝对目录")
        base_dir = base_dir.resolve()
    cache = get_credential_cache(base_dir=base_dir)
    session_id = cache.get_session_id()
    actual_email = str(cache.get_email() or "").strip().lower()
    if not session_id:
        raise ValueError("预取服务凭证作用域尚未完成 OPS 登录")
    if actual_email != expected_email:
        raise ValueError("预取服务凭证用户与配置邮箱不一致")
    return session_id, cache.get_jwt("ops")
