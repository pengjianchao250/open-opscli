"""通用 MCP 的预取计划管理工具和来源执行器。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from opscli.mcp.service_credentials import load_prefetch_service_auth
from opscli.shared.prefetch_schedule import (
    PrefetchRunClaim,
    PrefetchScheduleRepository,
    PrefetchSchedulerRuntime,
    load_prefetch_settings,
    next_daily_run,
    normalize_schedule_request,
    normalize_timezone_and_time,
)


def _prefetch_catalog_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """将绑定方法统一归入 prefetch_schedule 工具模块。"""
    setattr(fn, "__opscli_catalog_module__", "prefetch_schedule")
    return fn


class PrefetchMcpRuntime:
    """组合预取计划管理工具及通用 MCP 负责的来源执行器。"""

    def __init__(self, storage_runtime: Any, keepa_runtime: Any, google_runtime: Any) -> None:
        self.storage_runtime = storage_runtime
        self.keepa_runtime = keepa_runtime
        self.google_runtime = google_runtime
        self.settings = load_prefetch_settings()
        mysql_settings = getattr(storage_runtime.settings, "mysql", None)
        self.repository = (
            PrefetchScheduleRepository(settings=mysql_settings)
            if storage_runtime.settings.enabled and mysql_settings is not None
            else None
        )
        self.scheduler = (
            PrefetchSchedulerRuntime(
                runtime_id="mcp",
                settings=self.settings,
                repository=self.repository,
                executors={
                    "keepa": self._execute_keepa,
                    "google_trends": self._execute_google_trends,
                },
            )
            if self.repository is not None
            else None
        )
        self._lifespan_depth = 0

    def register(self, mcp: Any) -> None:
        """注册计划创建、查询、修改、删除、立即运行和历史工具。"""
        for fn in (
            self.prefetch_schedule_create,
            self.prefetch_schedule_list,
            self.prefetch_schedule_update,
            self.prefetch_schedule_delete,
            self.prefetch_schedule_run_now,
            self.prefetch_schedule_runs,
        ):
            mcp.tool()(fn)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """在来源 Runtime 就绪后启动并停止通用预取调度器。"""
        if self._lifespan_depth > 0:
            self._lifespan_depth += 1
            try:
                yield
            finally:
                self._lifespan_depth -= 1
            return
        if self.scheduler is not None:
            await self.scheduler.start()
        self._lifespan_depth = 1
        try:
            yield
        finally:
            self._lifespan_depth = 0
            if self.scheduler is not None:
                await self.scheduler.close()

    @_prefetch_catalog_tool
    async def prefetch_schedule_create(
        self,
        name: str,
        source_system: str,
        scenario: str,
        params: dict[str, Any] | str | None = None,
        site: str = "US",
        period: str = "30d",
        page_size: int = 100,
        export_format: str = "json",
        run_time: str = "06:00",
        timezone_name: str = "Asia/Shanghai",
        enabled: bool = True,
    ) -> dict:
        """手动创建每日预取计划；site 对 Google Trends 表示 geo。"""
        from opscli.mcp.tools.helpers import _err, _ok, _parse_json_arg

        try:
            repository = self._require_repository()
            owner = self._require_owner()
            schedule_name = str(name or "").strip()
            if not schedule_name or len(schedule_name) > 191:
                raise ValueError("计划名称不能为空且最多 191 个字符")
            parsed_params = _parse_json_arg(params, dict) or {}
            source, scenario_id, request = normalize_schedule_request(
                source_system=source_system,
                scenario=scenario,
                params=parsed_params,
                site=site,
                period=period,
                page_size=page_size,
                export_format=export_format,
            )
            normalized_time, normalized_zone = normalize_timezone_and_time(
                run_time,
                timezone_name,
            )
            schedule = await self._to_thread(
                repository.create_schedule,
                schedule_name=schedule_name,
                source_system=source,
                scenario=scenario_id,
                request=request,
                run_time=normalized_time,
                timezone_name=normalized_zone,
                enabled=enabled,
                next_run_at=next_daily_run(normalized_time, normalized_zone),
                created_by=owner,
            )
            schedule["execution_runtime"] = _execution_runtime(source)
            return _ok(schedule)
        except ValueError as exc:
            return _err(
                exc,
                tool="MCP → prefetch_schedule_create(...)",
                auto_feedback=False,
            )
        except Exception as exc:
            return _err(exc, tool="MCP → prefetch_schedule_create(...)")

    @_prefetch_catalog_tool
    async def prefetch_schedule_list(
        self,
        source_system: str | None = None,
        enabled: bool | None = None,
        limit: int = 100,
    ) -> dict:
        """列出当前用户手动创建的预取计划。"""
        from opscli.mcp.tools.helpers import _err, _ok

        try:
            source = (
                str(source_system).strip().lower().replace("-", "_")
                if source_system
                else None
            )
            schedules = await self._to_thread(
                self._require_repository().list_schedules,
                created_by=self._require_owner(),
                source_system=source,
                enabled=enabled,
                limit=limit,
            )
            for schedule in schedules:
                schedule["execution_runtime"] = _execution_runtime(
                    str(schedule["source_system"])
                )
            return _ok(
                {
                    "schedules": schedules,
                    "scheduler": (
                        self.scheduler.health()
                        if self.scheduler is not None
                        else {"status": "unavailable"}
                    ),
                }
            )
        except ValueError as exc:
            return _err(exc, tool="MCP → prefetch_schedule_list(...)", auto_feedback=False)
        except Exception as exc:
            return _err(exc, tool="MCP → prefetch_schedule_list(...)")

    @_prefetch_catalog_tool
    async def prefetch_schedule_update(
        self,
        schedule_id: int,
        name: str | None = None,
        params: dict[str, Any] | str | None = None,
        site: str | None = None,
        period: str | None = None,
        page_size: int | None = None,
        export_format: str | None = None,
        run_time: str | None = None,
        timezone_name: str | None = None,
        enabled: bool | None = None,
    ) -> dict:
        """修改当前用户计划的业务参数、每日时间或启用状态。"""
        from opscli.mcp.tools.helpers import _err, _ok, _parse_json_arg

        try:
            repository = self._require_repository()
            owner = self._require_owner()
            current = await self._to_thread(
                repository.get_schedule,
                schedule_id=schedule_id,
                created_by=owner,
            )
            current_request = dict(current["request"])
            parsed_params = (
                _parse_json_arg(params, dict)
                if params is not None
                else current_request.get("params") or {}
            )
            source = str(current["source_system"])
            current_site = current_request.get("geo", current_request.get("site", "US"))
            _, _, request = normalize_schedule_request(
                source_system=source,
                scenario=str(current["scenario"]),
                params=parsed_params,
                site=site if site is not None else str(current_site),
                period=(
                    period
                    if period is not None
                    else str(current_request.get("period") or "30d")
                ),
                page_size=(
                    page_size
                    if page_size is not None
                    else int(current_request.get("page_size") or 100)
                ),
                export_format=(
                    export_format
                    if export_format is not None
                    else str(current_request.get("export_format") or "json")
                ),
            )
            normalized_time, normalized_zone = normalize_timezone_and_time(
                run_time if run_time is not None else str(current["run_time"]),
                (
                    timezone_name
                    if timezone_name is not None
                    else str(current["timezone"])
                ),
            )
            values: dict[str, Any] = {"request_json": request}
            if name is not None:
                schedule_name = str(name).strip()
                if not schedule_name or len(schedule_name) > 191:
                    raise ValueError("计划名称不能为空且最多 191 个字符")
                values["schedule_name"] = schedule_name
            if run_time is not None or timezone_name is not None:
                values.update(
                    {
                        "run_time": normalized_time,
                        "timezone": normalized_zone,
                        "next_run_at": next_daily_run(normalized_time, normalized_zone),
                    }
                )
            if enabled is not None:
                values["enabled"] = int(enabled)
                if enabled and not bool(current["enabled"]):
                    values["next_run_at"] = next_daily_run(
                        normalized_time,
                        normalized_zone,
                    )
            schedule = await self._to_thread(
                repository.update_schedule,
                schedule_id=schedule_id,
                created_by=owner,
                values=values,
            )
            schedule["execution_runtime"] = _execution_runtime(source)
            return _ok(schedule)
        except ValueError as exc:
            return _err(
                exc,
                tool="MCP → prefetch_schedule_update(...)",
                auto_feedback=False,
            )
        except Exception as exc:
            return _err(exc, tool="MCP → prefetch_schedule_update(...)")

    @_prefetch_catalog_tool
    async def prefetch_schedule_delete(self, schedule_id: int) -> dict:
        """删除当前用户的预取计划及其运行历史。"""
        from opscli.mcp.tools.helpers import _err, _ok

        try:
            await self._to_thread(
                self._require_repository().delete_schedule,
                schedule_id=schedule_id,
                created_by=self._require_owner(),
            )
            return _ok({"schedule_id": int(schedule_id), "deleted": True})
        except ValueError as exc:
            return _err(exc, tool="MCP → prefetch_schedule_delete(...)", auto_feedback=False)
        except Exception as exc:
            return _err(exc, tool="MCP → prefetch_schedule_delete(...)")

    @_prefetch_catalog_tool
    async def prefetch_schedule_run_now(self, schedule_id: int) -> dict:
        """为当前用户计划追加一条立即执行任务，不改变每日时间。"""
        from opscli.mcp.tools.helpers import _err, _ok

        try:
            run = await self._to_thread(
                self._require_repository().queue_run_now,
                schedule_id=schedule_id,
                created_by=self._require_owner(),
            )
            return _ok(run)
        except ValueError as exc:
            return _err(exc, tool="MCP → prefetch_schedule_run_now(...)", auto_feedback=False)
        except Exception as exc:
            return _err(exc, tool="MCP → prefetch_schedule_run_now(...)")

    @_prefetch_catalog_tool
    async def prefetch_schedule_runs(
        self,
        schedule_id: int | None = None,
        limit: int = 50,
    ) -> dict:
        """读取当前用户预取计划的最近执行状态和来源任务 ID。"""
        from opscli.mcp.tools.helpers import _err, _ok

        try:
            runs = await self._to_thread(
                self._require_repository().list_runs,
                created_by=self._require_owner(),
                schedule_id=schedule_id,
                limit=limit,
            )
            return _ok({"runs": runs})
        except ValueError as exc:
            return _err(exc, tool="MCP → prefetch_schedule_runs(...)", auto_feedback=False)
        except Exception as exc:
            return _err(exc, tool="MCP → prefetch_schedule_runs(...)")

    async def _execute_keepa(self, claim: PrefetchRunClaim) -> dict[str, Any]:
        """强制 live 执行 Keepa，并将成功结果继续送入共享沉淀。"""
        from opscli.keepa.config import load_settings
        from opscli.mcp.tools.keepa import _keepa_run_impl

        session_id = jwt = None
        if not load_settings().api_key:
            session_id, jwt = load_prefetch_service_auth(self.settings, required=True)
        request = claim.request
        return await _keepa_run_impl(
            scenario=claim.scenario,
            params=request.get("params") or {},
            site=str(request.get("site") or "US"),
            export_format=str(request.get("export_format") or "json"),
            job_id=claim.job_id,
            session_id=session_id,
            jwt=jwt,
            collection_submitter=self.keepa_runtime.collection_submitter,
            cache_repository=self.keepa_runtime.cache_repository,
            cache_environment=self.keepa_runtime.cache_environment,
            cache_mode="live",
        )

    async def _execute_google_trends(
        self,
        claim: PrefetchRunClaim,
    ) -> dict[str, Any]:
        """强制 live 执行 Google Trends；服务凭证仅用于可选上传。"""
        from opscli.mcp.tools.google_trends import _google_trends_run_impl

        session_id, jwt = load_prefetch_service_auth(self.settings, required=False)
        request = claim.request
        return await _google_trends_run_impl(
            scenario=claim.scenario,
            params=request.get("params") or {},
            geo=str(request.get("geo") or "US"),
            export_format=str(request.get("export_format") or "json"),
            job_id=claim.job_id,
            session_id=session_id,
            jwt=jwt,
            collection_submitter=self.google_runtime.collection_submitter,
            cache_repository=self.google_runtime.cache_repository,
            cache_environment=self.google_runtime.cache_environment,
            cache_mode="live",
        )

    def _require_repository(self) -> PrefetchScheduleRepository:
        """拒绝在共享采集 MySQL 未启用时读写计划。"""
        if self.repository is None:
            raise ValueError("预取计划依赖共享采集 MySQL，请先启用采集数据沉淀")
        return self.repository

    @staticmethod
    def _require_owner() -> str:
        """读取已验证用户邮箱，作为计划所有权和审计字段。"""
        from opscli.mcp.tools.helpers import _get_authenticated_user_email

        owner = str(_get_authenticated_user_email() or "").strip().lower()
        if not owner:
            raise ValueError("当前 MCP 用户邮箱缺失，无法管理预取计划")
        return owner

    @staticmethod
    async def _to_thread(function: Callable[..., Any], **kwargs: Any) -> Any:
        """在线程中执行同步 MySQL 仓储调用，避免阻塞 MCP 事件循环。"""
        import asyncio

        return await asyncio.to_thread(function, **kwargs)


def _execution_runtime(source_system: str) -> str:
    return "collector" if source_system == "seller_sprite" else "mcp"
