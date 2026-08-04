"""统一数据采集服务脱敏健康工具。"""

from __future__ import annotations

from typing import Any

from opscli.collector_mcp.profile import CollectorServiceProfile, CollectorToolBundle
from opscli.config import __version__

_PROFILE: CollectorServiceProfile | None = None
_BUNDLES: tuple[CollectorToolBundle, ...] = ()


def configure_health(
    profile: CollectorServiceProfile,
    bundles: tuple[CollectorToolBundle, ...],
) -> None:
    """绑定当前进程已冻结的 Profile 与 Bundle 清单。"""
    global _PROFILE, _BUNDLES
    _PROFILE = profile
    _BUNDLES = bundles


def _require_profile() -> CollectorServiceProfile:
    """返回已配置 Profile，缺失时拒绝输出误导状态。"""
    if _PROFILE is None:
        raise RuntimeError("Collector 健康信息尚未初始化")
    return _PROFILE


async def collector_service_info() -> dict[str, Any]:
    """返回统一数据采集服务版本、Profile 与已启用模块。"""
    profile = _require_profile()
    return {
        "success": True,
        "data": {
            "service_id": profile.service_id,
            "display_name": profile.display_name,
            "version": __version__,
            "profile": profile.profile_id,
            "bundles": [bundle.bundle_id for bundle in _BUNDLES],
            "single_worker_required": profile.single_worker_required
            or any(bundle.single_worker_required for bundle in _BUNDLES),
        },
        "error": None,
    }


async def collector_modules_health() -> dict[str, Any]:
    """返回各数据采集模块及服务级脱敏健康状态。"""
    profile = _require_profile()
    modules = [await bundle.health_check() for bundle in _BUNDLES]
    from opscli.collector_mcp.storage.runtime import get_collection_storage_runtime

    storage = get_collection_storage_runtime().health()
    critical = set(profile.critical_bundles)
    critical_failed = any(
        item["bundle_id"] in critical
        and item.get("status") not in {"ready", "degraded"}
        for item in modules
    )
    any_degraded = any(item.get("status") == "degraded" for item in modules) or storage.get(
        "status"
    ) == "degraded"
    status = "not_ready" if critical_failed else "degraded" if any_degraded else "ready"
    return {
        "success": True,
        "data": {
            "service_id": profile.service_id,
            "status": status,
            "modules": modules,
            "storage": storage,
        },
        "error": None,
    }


def register(mcp) -> None:
    """注册 Collector 公共健康工具。"""
    mcp.tool()(collector_service_info)
    mcp.tool()(collector_modules_health)
