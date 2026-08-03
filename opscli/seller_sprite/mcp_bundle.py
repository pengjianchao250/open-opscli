"""卖家精灵统一数据采集服务 Bundle。"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import Any

from opscli.seller_sprite.domain.exceptions import SellerSpriteError

_MODULE_STATE: dict[str, Any] = {
    "status": "not_ready",
    "checks": {
        "queue": "not_checked",
        "scheduler": "not_started",
    },
}
_PUBLIC_RUNTIME_FIELDS = (
    "lifecycle_state",
    "heartbeat_at",
    "generic_workers_alive",
    "listing_worker_alive",
    "generic_available_capacity",
    "listing_available_capacity",
    "available_capacity",
    "standby_capacity",
    "last_claim_at",
    "last_progress_at",
    "heartbeat_fresh",
)


class SellerSpriteModuleNotReadyError(SellerSpriteError):
    """Collector Bundle 未完成启动，业务工具暂不可用。"""

    code = "COLLECTOR_MODULE_NOT_READY"

    def __init__(self) -> None:
        super().__init__("卖家精灵采集模块尚未就绪，请先检查 Collector 模块健康状态")

    def to_dict(self) -> dict[str, str]:
        """返回不包含底层异常和文件路径的公开错误。"""
        return {
            "code": self.code,
            "message": str(self),
            "module": "seller_sprite",
        }


def register(mcp) -> None:
    """显式注册卖家精灵公开 MCP Tool。"""
    from opscli.mcp.tools.seller_sprite import _ALL_TOOLS

    for fn in _ALL_TOOLS:
        mcp.tool()(fn)


def _set_module_state(
    status: str,
    *,
    error_code: str | None = None,
    error_class: str | None = None,
    **checks: str,
) -> None:
    """更新仅包含脱敏检查项的模块状态。"""
    _MODULE_STATE.clear()
    _MODULE_STATE.update({"status": status, "checks": dict(checks)})
    if error_code:
        _MODULE_STATE["error_code"] = error_code
    if error_class:
        _MODULE_STATE["error_class"] = error_class


def _startup_error_fields(exc: Exception) -> tuple[str, str]:
    """把启动异常归类为稳定且不泄露路径的公开字段。"""
    current: BaseException | None = exc
    while current is not None:
        if (
            isinstance(current, sqlite3.OperationalError)
            and "unable to open database file" in str(current).lower()
        ):
            return "QUEUE_DATABASE_UNAVAILABLE", type(current).__name__
        current = current.__cause__ or current.__context__
    return "COLLECTOR_MODULE_STARTUP_FAILED", type(exc).__name__


def require_ready() -> None:
    """确认 SellerSprite Bundle 已就绪。

    Raises:
        SellerSpriteModuleNotReadyError: Bundle 未完成启动或启动失败。
    """
    if _MODULE_STATE.get("status") != "ready":
        raise SellerSpriteModuleNotReadyError()


@asynccontextmanager
async def lifespan():
    """启动队列调度器，并在服务关闭时释放浏览器和后台任务。"""
    scheduler = None
    _set_module_state("not_ready", queue="not_checked", scheduler="not_started")
    try:
        from opscli.seller_sprite.services import get_task_scheduler

        scheduler = get_task_scheduler()
        # 由调度器按租约恢复过期任务，避免服务启动时抢占其他实例的运行任务。
        await scheduler.start()
        _set_module_state("ready", queue="ok", scheduler="running")
    except Exception as exc:
        error_code, error_class = _startup_error_fields(exc)
        _set_module_state(
            "failed",
            queue="error",
            scheduler="not_started",
            error_code=error_code,
            error_class=error_class,
        )
        if scheduler is not None:
            try:
                await scheduler.close()
            except Exception:
                pass
        # Collector 必须继续提供健康面，业务入口由 require_ready() 拒绝。
        yield
        return

    try:
        yield
    finally:
        _set_module_state("not_ready", queue="ok", scheduler="stopping")
        await scheduler.close()
        _set_module_state("not_ready", queue="ok", scheduler="stopped")


async def health_check() -> dict[str, Any]:
    """返回不包含账号、路径和任务参数的实时模块健康状态。"""
    if _MODULE_STATE["status"] not in {"ready", "degraded"}:
        result = {
            "bundle_id": "seller_sprite",
            "status": _MODULE_STATE["status"],
            "checks": dict(_MODULE_STATE["checks"]),
        }
        for field in ("error_code", "error_class"):
            if field in _MODULE_STATE:
                result[field] = _MODULE_STATE[field]
        return result

    from opscli.seller_sprite.services import get_task_scheduler

    scheduler = get_task_scheduler()
    runtime_health = getattr(scheduler, "runtime_health", None)
    if not callable(runtime_health):
        return {
            "bundle_id": "seller_sprite",
            "status": _MODULE_STATE["status"],
            "checks": dict(_MODULE_STATE["checks"]),
        }

    try:
        health = runtime_health()
    except Exception:
        return {
            "bundle_id": "seller_sprite",
            "status": "degraded",
            "checks": {"queue": "error", "scheduler": "health_check_failed"},
            "runtime": {},
        }
    runtime = health.get("runtime")
    public_runtime = (
        {
            field: runtime[field]
            for field in _PUBLIC_RUNTIME_FIELDS
            if field in runtime
        }
        if isinstance(runtime, dict)
        else {}
    )
    return {
        "bundle_id": "seller_sprite",
        "status": str(health.get("status") or "not_ready"),
        "checks": {
            "queue": str((health.get("checks") or {}).get("queue") or "error"),
            "scheduler": str(
                (health.get("checks") or {}).get("scheduler") or "not_started"
            ),
        },
        "runtime": public_runtime,
    }


def build_bundle():
    """构造卖家精灵 Collector Tool Bundle。"""
    from opscli.collector_mcp.profile import CollectorToolBundle

    return CollectorToolBundle(
        bundle_id="seller_sprite",
        tool_prefix="seller_sprite_",
        register=register,
        lifespan=lifespan,
        health_check=health_check,
        single_worker_required=True,
    )
