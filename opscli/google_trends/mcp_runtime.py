"""通用 MCP 中 Google Trends Tool 与共享数据沉淀的组合生命周期。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Callable

from opscli.google_trends.domain.exceptions import GoogleTrendsError

if TYPE_CHECKING:
    from opscli.shared.collection_storage.runtime import CollectionStorageRuntime


def _google_trends_catalog_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """让绑定方法在通用 MCP Catalog 中继续归属 google_trends 模块。"""
    setattr(fn, "__opscli_catalog_module__", "google_trends")
    return fn


class GoogleTrendsModuleNotReadyError(GoogleTrendsError):
    """Google Trends MCP Runtime 尚未完成启动。"""

    code = "GOOGLE_TRENDS_MODULE_NOT_READY"

    def __init__(self) -> None:
        super().__init__("Google Trends 采集模块尚未就绪，请检查通用 MCP 启动状态")


class GoogleTrendsMcpRuntime:
    """持有通用 MCP 内 Google Trends Tool 的实例状态。"""

    def __init__(self) -> None:
        self.collection_submitter: Callable[..., bool] | None = None
        self._ready = False
        self._lifespan_depth = 0

    def register(self, mcp: Any) -> None:
        """注册 Google Trends Tool，并让执行入口绑定当前 Runtime 实例。

        Args:
            mcp: FastMCP 注册代理。

        Returns:
            无返回值。

        Raises:
            Exception: FastMCP 拒绝工具注册时透传原始异常。
        """
        from opscli.mcp.tools.google_trends import (
            google_trends_export,
            google_trends_job_status,
            google_trends_scenarios,
            google_trends_spec_must_read,
        )

        for fn in (
            google_trends_spec_must_read,
            google_trends_scenarios,
            self.google_trends_run,
            google_trends_job_status,
            google_trends_export,
        ):
            mcp.tool()(fn)

    @asynccontextmanager
    async def lifespan(
        self,
        storage_runtime: CollectionStorageRuntime,
    ) -> AsyncIterator[None]:
        """注册 Google Trends 沉淀 Adapter，并在关闭时逆序解除注册。

        Args:
            storage_runtime: 通用 MCP 共享的采集数据沉淀 Runtime。

        Yields:
            生命周期就绪后的控制权。

        Raises:
            不向调用方抛出初始化异常；失败时保持模块未就绪，由工具返回公开错误。
        """
        # 双传输模式会嵌套进入同一 FastMCP lifespan；内层只增加引用，不重复注册来源。
        if self._lifespan_depth > 0:
            self._lifespan_depth += 1
            try:
                yield
            finally:
                self._lifespan_depth -= 1
            return

        source_registered = False
        self.collection_submitter = None
        self._ready = False
        try:
            from opscli.google_trends.collection_storage_integration import (
                GoogleTrendsCollectionReconciler,
                GoogleTrendsCollectionSubmitter,
            )
            from opscli.google_trends.collection_storage_parser import (
                GoogleTrendsCollectionParser,
            )
            from opscli.google_trends.config import load_settings

            if storage_runtime.settings.enabled:
                if storage_runtime.outbox is None:
                    raise RuntimeError("共享数据沉淀 Outbox 尚未启动")
                storage_runtime.register_source(
                    GoogleTrendsCollectionParser(),
                    GoogleTrendsCollectionReconciler(
                        output_dir=load_settings().output_dir,
                        data_environment=storage_runtime.settings.data_environment,
                        outbox=storage_runtime.outbox,
                    ),
                )
                source_registered = True
                self.collection_submitter = GoogleTrendsCollectionSubmitter(
                    storage_runtime
                )
            self._ready = True
            self._lifespan_depth = 1
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
            self._lifespan_depth = 0
            self.collection_submitter = None
            self._ready = False
            self._cleanup_storage(
                storage_runtime,
                source_registered=source_registered,
            )

    def require_ready(self) -> None:
        """拒绝在 Runtime 启动失败或停止后执行新的趋势采集。

        Returns:
            Runtime 就绪时无返回值。

        Raises:
            GoogleTrendsModuleNotReadyError: Runtime 尚未启动或初始化失败。
        """
        if not self._ready:
            raise GoogleTrendsModuleNotReadyError()

    @_google_trends_catalog_tool
    async def google_trends_run(
        self,
        scenario: str,
        params: dict[str, Any] | str | None = None,
        geo: str = "US",
        export_format: str = "xls",
        hl: str | None = None,
        tz: int | None = None,
        session_id: str | None = None,
        jwt: str | None = None,
    ) -> dict:
        """在 Runtime 就绪后执行趋势采集，并注入当前沉淀 Submitter。

        Args:
            scenario: Google Trends 场景标识。
            params: 场景参数对象或 JSON 字符串。
            geo: 地域代码。
            export_format: 导出格式。
            hl: SerpApi 界面语言。
            tz: SerpApi 时区偏移。
            session_id: 可选 OPS 会话 ID。
            jwt: 可选 OPS JWT。

        Returns:
            MCP 统一成功或失败响应。
        """
        from opscli.mcp.tools.google_trends import _google_trends_run_impl
        from opscli.mcp.tools.helpers import _err

        try:
            self.require_ready()
        except GoogleTrendsModuleNotReadyError as exc:
            return _err(exc, tool="MCP → google_trends_run(...)（Google Trends）")
        return await _google_trends_run_impl(
            scenario=scenario,
            params=params,
            geo=geo,
            export_format=export_format,
            output_dir=None,
            job_id=None,
            hl=hl,
            tz=tz,
            session_id=session_id,
            jwt=jwt,
            collection_submitter=self.collection_submitter,
        )

    @staticmethod
    def _cleanup_storage(
        storage_runtime,
        *,
        source_registered: bool,
    ) -> None:
        """仅清理本生命周期已经成功注册的来源。"""
        if source_registered:
            storage_runtime.unregister_source("google_trends")
