"""通用 MCP 中 Keepa Tool 与共享数据沉淀的组合生命周期。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Callable

from opscli.keepa.domain.exceptions import KeepaError

if TYPE_CHECKING:
    from opscli.shared.collection_storage.runtime import CollectionStorageRuntime


def _keepa_catalog_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """让绑定方法在通用 MCP Catalog 中继续归属 keepa 模块。"""
    setattr(fn, "__opscli_catalog_module__", "keepa")
    from opscli.keepa.api.scenarios import telemetry_dimensions

    setattr(fn, "__opscli_telemetry_dimension_resolver__", telemetry_dimensions)
    return fn


class KeepaModuleNotReadyError(KeepaError):
    """Keepa MCP Runtime 尚未完成启动。"""

    code = "KEEPA_MODULE_NOT_READY"

    def __init__(self) -> None:
        super().__init__("Keepa 采集模块尚未就绪，请检查通用 MCP 启动状态")

    def to_dict(self) -> dict[str, str]:
        """返回不包含内部异常和路径的公开错误。"""
        return {"code": self.code, "message": str(self), "module": "keepa"}


class KeepaMcpRuntime:
    """持有通用 MCP 内单个 Keepa Tool 集合的实例状态。"""

    def __init__(self) -> None:
        self.collection_submitter: Callable[..., bool] | None = None
        self._ready = False

    def register(self, mcp: Any) -> None:
        """注册 Keepa Tool，并让执行入口绑定当前 Runtime 实例。"""
        from opscli.mcp.tools.keepa import (
            keepa_export,
            keepa_job_status,
            keepa_quota_status,
            keepa_scenarios,
            keepa_spec_must_read,
        )

        for fn in (
            keepa_spec_must_read,
            keepa_scenarios,
            keepa_quota_status,
            self.keepa_run,
            keepa_job_status,
            keepa_export,
        ):
            mcp.tool()(fn)

    @asynccontextmanager
    async def lifespan(
        self,
        storage_runtime: CollectionStorageRuntime,
    ) -> AsyncIterator[None]:
        """注册 Keepa 沉淀 Adapter，并在关闭时逆序解除注册。"""
        source_registered = False
        self.collection_submitter = None
        self._ready = False
        try:
            from opscli.keepa.collection_storage_integration import (
                KeepaCollectionReconciler,
                KeepaCollectionSubmitter,
            )
            from opscli.keepa.collection_storage_parser import (
                KeepaCollectionParser,
            )
            from opscli.keepa.config import load_settings

            if storage_runtime.settings.enabled:
                if storage_runtime.outbox is None:
                    raise RuntimeError("共享数据沉淀 Outbox 尚未启动")
                storage_runtime.register_source(
                    KeepaCollectionParser(),
                    KeepaCollectionReconciler(
                        output_dir=load_settings().output_dir,
                        data_environment=storage_runtime.settings.data_environment,
                        outbox=storage_runtime.outbox,
                    )
                )
                source_registered = True
                self.collection_submitter = KeepaCollectionSubmitter(storage_runtime)
            self._ready = True
        except Exception:  # noqa: BLE001
            self.collection_submitter = None
            self._cleanup_storage(
                storage_runtime,
                source_registered=source_registered,
            )
            yield
            return

        try:
            yield
        finally:
            self.collection_submitter = None
            self._ready = False
            self._cleanup_storage(
                storage_runtime,
                source_registered=source_registered,
            )

    @_keepa_catalog_tool
    async def keepa_run(
        self,
        scenario: str,
        params: dict[str, Any] | str | None = None,
        site: str = "US",
        export_format: str = "xls",
        job_id: str | None = None,
        reserve_tokens: int | None = None,
        force: bool = False,
        wait: bool = False,
        session_id: str | None = None,
        jwt: str | None = None,
    ) -> dict:
        """在 Runtime 就绪后执行 Keepa，并注入当前沉淀 Submitter。"""
        from opscli.mcp.tools.helpers import _err
        from opscli.mcp.tools.keepa import _keepa_run_impl

        try:
            self.require_ready()
        except KeepaModuleNotReadyError as exc:
            return _err(exc, tool="MCP → keepa_run(...)（Keepa）")
        return await _keepa_run_impl(
            scenario=scenario,
            params=params,
            site=site,
            export_format=export_format,
            output_dir=None,
            job_id=job_id,
            reserve_tokens=reserve_tokens,
            force=force,
            wait=wait,
            session_id=session_id,
            jwt=jwt,
            collection_submitter=self.collection_submitter,
        )

    def require_ready(self) -> None:
        """拒绝在 Runtime 启动失败或停止后执行新的 Keepa 采集。"""
        if not self._ready:
            raise KeepaModuleNotReadyError()

    @staticmethod
    def _cleanup_storage(
        storage_runtime,
        *,
        source_registered: bool,
    ) -> None:
        if source_registered:
            storage_runtime.unregister_source("keepa")
