"""Keepa 统一数据采集服务 Bundle。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Callable

from opscli.keepa.domain.exceptions import KeepaError

if TYPE_CHECKING:
    from opscli.collector_mcp.profile import CollectorToolBundle


class KeepaModuleNotReadyError(KeepaError):
    """Keepa Collector Bundle 尚未完成启动。"""

    code = "COLLECTOR_MODULE_NOT_READY"

    def __init__(self) -> None:
        super().__init__("Keepa 采集模块尚未就绪，请先检查 Collector 模块健康状态")

    def to_dict(self) -> dict[str, str]:
        """返回不包含内部异常和路径的公开错误。"""
        return {"code": self.code, "message": str(self), "module": "keepa"}


class KeepaBundleRuntime:
    """持有单个 Keepa Bundle 的生命周期状态和沉淀依赖。"""

    def __init__(self) -> None:
        self.collection_submitter: Callable[..., bool] | None = None
        self._state: dict[str, Any] = {
            "status": "not_ready",
            "checks": {
                "api": "not_ready",
                "storage_registration": "not_checked",
            },
        }

    def register(self, mcp: Any) -> None:
        """注册 Keepa Tool，并让执行入口绑定当前 Bundle 实例。"""
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
    async def lifespan(self) -> AsyncIterator[None]:
        """注册 Keepa 沉淀 Adapter，并在关闭时逆序解除注册。"""
        storage_runtime = None
        parser_registered = False
        reconciler_registered = False
        self.collection_submitter = None
        self._set_state(
            "not_ready",
            api="not_ready",
            storage_registration="not_checked",
        )
        try:
            from opscli.collector_mcp.storage.keepa_integration import (
                KeepaCollectionReconciler,
                KeepaCollectionSubmitter,
            )
            from opscli.collector_mcp.storage.keepa_parser import (
                KeepaCollectionParser,
            )
            from opscli.collector_mcp.storage.runtime import (
                get_collection_storage_runtime,
            )
            from opscli.keepa.config import load_settings

            storage_runtime = get_collection_storage_runtime()
            storage_status = "disabled"
            if storage_runtime.settings.enabled:
                if storage_runtime.outbox is None:
                    raise RuntimeError("Collector 数据沉淀 Outbox 尚未启动")
                storage_runtime.register_parser(KeepaCollectionParser())
                parser_registered = True
                storage_runtime.register_reconciler(
                    KeepaCollectionReconciler(
                        output_dir=load_settings().output_dir,
                        data_environment=storage_runtime.settings.data_environment,
                        outbox=storage_runtime.outbox,
                    )
                )
                reconciler_registered = True
                self.collection_submitter = KeepaCollectionSubmitter(storage_runtime)
                storage_status = "ok"
            self._set_state(
                "ready",
                api="ready",
                storage_registration=storage_status,
            )
        except Exception as exc:  # noqa: BLE001
            self.collection_submitter = None
            self._cleanup_storage(
                storage_runtime,
                parser_registered=parser_registered,
                reconciler_registered=reconciler_registered,
            )
            self._set_state(
                "failed",
                api="not_ready",
                storage_registration="error",
                error_code=type(exc).__name__,
            )
            yield
            return

        try:
            yield
        finally:
            self.collection_submitter = None
            self._cleanup_storage(
                storage_runtime,
                parser_registered=parser_registered,
                reconciler_registered=reconciler_registered,
            )
            self._set_state(
                "not_ready",
                api="not_ready",
                storage_registration="stopped",
            )

    async def health_check(self) -> dict[str, Any]:
        """返回不包含账号、路径和凭证的 Keepa 模块状态。"""
        result = {
            "bundle_id": "keepa",
            "status": self._state["status"],
            "checks": dict(self._state["checks"]),
        }
        if self._state.get("error_code"):
            result["error_code"] = self._state["error_code"]
        return result

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
        """在 Bundle 就绪后执行 Keepa，并注入当前沉淀 Submitter。"""
        from opscli.mcp.tools.helpers import _err
        from opscli.mcp.tools.keepa import _keepa_run_impl

        try:
            self.require_ready()
        except KeepaModuleNotReadyError as exc:
            return _err(exc, tool="MCP → keepa_run(...)（Collector Keepa）")
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
        """拒绝在 Bundle 启动失败或停止后执行新的 Keepa 采集。"""
        if self._state.get("status") != "ready":
            raise KeepaModuleNotReadyError()

    def _set_state(
        self,
        status: str,
        *,
        error_code: str | None = None,
        **checks: str,
    ) -> None:
        self._state = {"status": status, "checks": dict(checks)}
        if error_code:
            self._state["error_code"] = error_code

    @staticmethod
    def _cleanup_storage(
        storage_runtime,
        *,
        parser_registered: bool,
        reconciler_registered: bool,
    ) -> None:
        if storage_runtime is None:
            return
        if reconciler_registered:
            storage_runtime.unregister_reconciler("keepa")
        if parser_registered:
            storage_runtime.unregister_parser("keepa")


def build_bundle() -> CollectorToolBundle:
    """构造拥有独立实例状态的 Keepa Collector Tool Bundle。"""
    from opscli.collector_mcp.profile import CollectorToolBundle

    runtime = KeepaBundleRuntime()
    return CollectorToolBundle(
        bundle_id="keepa",
        tool_prefix="keepa_",
        register=runtime.register,
        lifespan=runtime.lifespan,
        health_check=runtime.health_check,
        single_worker_required=False,
    )
