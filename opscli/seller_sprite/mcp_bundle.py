"""卖家精灵统一数据采集服务 Bundle。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

_MODULE_STATE: dict[str, Any] = {
    "status": "not_ready",
    "checks": {
        "queue": "not_checked",
        "scheduler": "not_started",
    },
}


def register(mcp) -> None:
    """显式注册卖家精灵公开 MCP Tool。"""
    from opscli.mcp.tools.seller_sprite import _ALL_TOOLS

    for fn in _ALL_TOOLS:
        mcp.tool()(fn)


def _set_module_state(status: str, **checks: str) -> None:
    """更新仅包含脱敏检查项的模块状态。"""
    _MODULE_STATE["status"] = status
    _MODULE_STATE["checks"] = dict(checks)


@asynccontextmanager
async def lifespan():
    """启动队列调度器，并在服务关闭时释放浏览器和后台任务。"""
    scheduler = None
    try:
        from opscli.seller_sprite.services import get_task_scheduler

        scheduler = get_task_scheduler()
        # 由调度器按租约恢复过期任务，避免服务启动时抢占其他实例的运行任务。
        await scheduler.start()
        _set_module_state("ready", queue="ok", scheduler="running")
    except Exception:
        _set_module_state("failed", queue="error", scheduler="not_started")
        if scheduler is not None:
            await scheduler.close()
        raise

    try:
        yield
    finally:
        _set_module_state("not_ready", queue="ok", scheduler="stopping")
        await scheduler.close()
        _set_module_state("not_ready", queue="ok", scheduler="stopped")


async def health_check() -> dict[str, Any]:
    """返回不包含账号、路径和任务参数的模块健康状态。"""
    return {
        "bundle_id": "seller_sprite",
        "status": _MODULE_STATE["status"],
        "checks": dict(_MODULE_STATE["checks"]),
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
