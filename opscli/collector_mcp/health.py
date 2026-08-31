"""统一数据采集服务脱敏健康工具。"""

from __future__ import annotations

from typing import Any

from opscli.collector_mcp.profile import CollectorServiceProfile, CollectorToolBundle
from opscli.config import __version__
from opscli.shared.collection_storage import CollectionStorageRuntime


class CollectorHealthTools:
    """绑定单个 Collector App 的 Profile、Bundle 与存储健康状态。"""

    def __init__(
        self,
        profile: CollectorServiceProfile,
        bundles: tuple[CollectorToolBundle, ...],
        storage_runtime: CollectionStorageRuntime,
    ) -> None:
        self._profile = profile
        self._bundles = bundles
        self._storage_runtime = storage_runtime

    async def collector_service_info(self) -> dict[str, Any]:
        """返回统一数据采集服务版本、Profile 与已启用模块。"""
        return {
            "success": True,
            "data": {
                "service_id": self._profile.service_id,
                "display_name": self._profile.display_name,
                "version": __version__,
                "profile": self._profile.profile_id,
                "bundles": [bundle.bundle_id for bundle in self._bundles],
                "single_worker_required": self._profile.single_worker_required
                or any(bundle.single_worker_required for bundle in self._bundles),
            },
            "error": None,
        }

    async def collector_modules_health(self) -> dict[str, Any]:
        """返回各数据采集模块及服务级脱敏健康状态。"""
        modules = [await bundle.health_check() for bundle in self._bundles]
        storage = self._storage_runtime.health()
        critical = set(self._profile.critical_bundles)
        critical_failed = any(
            item["bundle_id"] in critical
            and item.get("status") not in {"ready", "degraded"}
            for item in modules
        )
        any_degraded = any(
            item.get("status") == "degraded" for item in modules
        ) or storage.get("status") == "degraded"
        status = (
            "not_ready"
            if critical_failed
            else "degraded"
            if any_degraded
            else "ready"
        )
        return {
            "success": True,
            "data": {
                "service_id": self._profile.service_id,
                "status": status,
                "modules": modules,
                "storage": storage,
            },
            "error": None,
        }

    def register(self, mcp: Any) -> None:
        """注册 Collector 公共健康工具。"""
        mcp.tool()(self.collector_service_info)
        mcp.tool()(self.collector_modules_health)
