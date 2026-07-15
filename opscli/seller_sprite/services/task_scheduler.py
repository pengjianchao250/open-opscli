"""卖家精灵单账号任务调度器。"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services.api_manager import SellerSpriteApiManager, _build_job_id
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore
from opscli.seller_sprite.services.task_status import error_to_dict


QUEUE_SCOPE = "seller_sprite"
DEFAULT_WORKER_KEY = "default"
_SCHEDULERS: dict[tuple[int, str], "SellerSpriteTaskScheduler"] = {}
logger = logging.getLogger(__name__)


class SellerSpriteTaskScheduler:
    """负责单账号 FIFO 排队和后台消费。"""

    def __init__(
        self,
        *,
        store: SellerSpriteTaskQueueStore | None = None,
        settings: SellerSpriteSettings | None = None,
        account_provider=None,
        manager_factory: Callable[..., SellerSpriteApiManager] | None = None,
        auto_start: bool = True,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        self.settings = settings or load_settings()
        self.account_provider = account_provider
        self.store = store or SellerSpriteTaskQueueStore()
        self.auto_start = auto_start
        self.poll_interval_seconds = poll_interval_seconds
        self.manager_factory = manager_factory or self._default_manager_factory
        self._runtime_auth: dict[str, tuple[str, str | None]] = {}
        self._runner_task: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()
        self._stop_requested = False

    async def enqueue(
        self,
        request: SellerSpriteScenarioRequest,
        *,
        credential_scope: str | None = None,
        session_id: str | None = None,
        jwt: str | None = None,
        expected_user_email: str | None = None,
    ) -> dict[str, Any]:
        """携带非敏感凭证作用域入队，并按需启动后台调度循环。"""
        normalized = self._normalize_request(request)
        root_dir = self._build_root_dir(normalized)
        status = self.store.enqueue(
            request=normalized,
            queue_scope=QUEUE_SCOPE,
            root_dir=root_dir,
            credential_scope=credential_scope,
            runtime_auth_required=bool(session_id or jwt),
            expected_user_email=expected_user_email,
        )
        if session_id:
            # 显式凭证仅按 job_id 短暂保存在内存中，禁止写入 SQLite 或跨任务复用。
            self._runtime_auth[str(normalized.job_id)] = (session_id, jwt)
        if self.auto_start:
            await self.start()
        return status

    async def start(self) -> None:
        """启动后台调度循环，并恢复残留运行中任务。"""
        async with self._start_lock:
            if self._runner_task and not self._runner_task.done():
                return
            self._stop_requested = False
            self.store.reset_running_tasks()
            # 后台 worker 生命周期跨越多个 MCP 请求，必须从空上下文创建，禁止继承首个用户身份。
            self._runner_task = contextvars.Context().run(asyncio.create_task, self._run_loop())

    async def close(self) -> None:
        """停止后台调度循环。"""
        self._stop_requested = True
        if self._runner_task is None:
            return
        await self._runner_task
        self._runner_task = None

    def job_status(self, job_id: str) -> dict[str, Any]:
        """返回任务当前状态。"""
        status = self.store.get_status(job_id)
        result_path = status.get("result_path")
        if status["state"] != "succeeded" or not result_path:
            return status
        path = Path(str(result_path))
        if not path.exists():
            return status
        payload = json.loads(path.read_text(encoding="utf-8"))
        merged = dict(status)
        merged.update(payload)
        merged.setdefault("state", status["state"])
        merged.setdefault("stage", status["stage"])
        merged.setdefault("position", None)
        return merged

    async def _run_loop(self) -> None:
        while True:
            if self._stop_requested:
                return
            try:
                await self._consume_once()
            except Exception:
                # 调度循环自身异常不能让后台 worker 退出，否则后续 queued 会长期无人消费。
                logger.exception("卖家精灵任务调度循环异常，短暂等待后继续消费")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _consume_once(self) -> None:
        self._prune_runtime_auth()
        claimed = self.store.claim_next(
            queue_scope=QUEUE_SCOPE,
            worker_key=DEFAULT_WORKER_KEY,
            assigned_account=self._assigned_account_name(),
        )
        if claimed is None:
            await asyncio.sleep(self.poll_interval_seconds)
            return
        job_id = str(claimed["job_id"])
        try:
            await self._run_one(job_id)
        except Exception:
            # 单条任务的审计收尾异常不能拖垮整个后台 worker，记录后继续消费后续任务。
            logger.exception("卖家精灵任务调度执行异常，继续消费后续任务：job_id=%s", job_id)

    async def _run_one(self, job_id: str) -> None:
        has_mcp_run = False
        try:
            request = self.store.get_request(job_id)
            context = self.store.get_task_context(job_id)
            runtime_auth = self._runtime_auth.pop(job_id, None)
            expected_user_email = context.get("expected_user_email")
            has_mcp_run = self._has_mcp_run(
                job_id,
                fail_closed=bool(expected_user_email),
            )
            if not expected_user_email and has_mcp_run:
                expected_user_email = str(self.store.get_mcp_run(job_id)["user_email"])
            session_id, jwt = _resolve_task_auth(
                context,
                runtime_auth=runtime_auth,
                require_auth=bool(expected_user_email or has_mcp_run),
                expected_user_email=expected_user_email,
            )
            manager = self.manager_factory(
                settings=self.settings,
                account_provider=self.account_provider,
                jwt=jwt,
                session_id=session_id,
            )
            if has_mcp_run:
                self.store.mark_mcp_run_running(job_id)
            result = await manager.run(request)
            export_payload = self._build_mcp_export_payload(request, result)
            self.store.finish_task(
                job_id=job_id,
                result_path=result.result_path,
                row_count=result.row_count,
                export_payload=result.export.to_dict() if result.export else None,
            )
            if has_mcp_run:
                self.store.finish_mcp_run_success(job_id, result.row_count, export_payload)
        except Exception as exc:
            error_payload = error_to_dict(exc)
            self.store.fail_task(job_id=job_id, error_payload=error_payload)
            if has_mcp_run:
                self.store.finish_mcp_run_failed(job_id, error_payload)
        finally:
            self._runtime_auth.pop(job_id, None)

    def _default_manager_factory(self, **kwargs) -> SellerSpriteApiManager:
        return SellerSpriteApiManager(**kwargs)

    def _prune_runtime_auth(self) -> None:
        """清理已被其他进程终止的排队任务凭证，避免敏感信息滞留内存。"""
        for job_id in list(self._runtime_auth):
            try:
                state = str(self.store.get_status(job_id)["state"])
            except Exception:
                continue
            if state in {"succeeded", "failed", "cancelled"}:
                self._runtime_auth.pop(job_id, None)

    def _assigned_account_name(self) -> str:
        """返回队列记录里的账号标识，不在领取任务前触发账号接口。"""
        return self.settings.account_name or DEFAULT_WORKER_KEY

    def _normalize_request(self, request: SellerSpriteScenarioRequest) -> SellerSpriteScenarioRequest:
        site = (request.site or self.settings.default_site).upper()
        period = request.period or self.settings.default_period
        job_id = request.job_id or _build_job_id(request, site, period)
        return replace(request, site=site, period=period, job_id=job_id)

    def _build_root_dir(self, request: SellerSpriteScenarioRequest) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / str(request.job_id)

    def _has_mcp_run(self, job_id: str, *, fail_closed: bool = False) -> bool:
        """探测任务是否存在 MCP 调用记录。"""
        try:
            self.store.get_mcp_run(job_id)
            return True
        except ValueError:
            return False
        except Exception:
            if fail_closed:
                raise
            # 兼容没有 MCP 身份标记的本地旧任务；新 MCP 任务会携带提交者并严格失败关闭。
            logger.warning("探测 MCP 调用记录失败，按普通旧任务继续执行：job_id=%s", job_id, exc_info=True)
            return False

    def _build_mcp_export_payload(
        self,
        request: SellerSpriteScenarioRequest,
        result: Any,
    ) -> dict[str, Any]:
        """构造 MCP 成功态所需的导出信息。"""
        if result.export:
            return result.export.to_dict()
        return {
            "format": request.export_format,
            "filename": Path(result.result_path).name,
        }


def get_task_scheduler(
    *,
    settings: SellerSpriteSettings | None = None,
    account_provider=None,
) -> SellerSpriteTaskScheduler:
    """按事件循环和队列库路径复用任务调度器实例。"""
    current_settings = settings or load_settings()
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        # Sync CLI commands do not run inside an event loop, but they still need
        # a stable scheduler instance to read queued task status/export metadata.
        loop_key = -threading.get_ident()
    store_key = str(SellerSpriteTaskQueueStore().db_path.resolve())
    key = (loop_key, store_key)
    scheduler = _SCHEDULERS.get(key)
    if scheduler is None:
        scheduler = SellerSpriteTaskScheduler(
            settings=current_settings,
            account_provider=account_provider,
        )
        _SCHEDULERS[key] = scheduler
    return scheduler


def _resolve_task_auth(
    context: dict[str, Any],
    *,
    runtime_auth: tuple[str, str | None] | None = None,
    require_auth: bool = False,
    expected_user_email: str | None = None,
) -> tuple[str | None, str | None]:
    """优先使用逐任务内存凭证，否则从统一 CredentialStore 读取并严格失败关闭。"""
    if runtime_auth:
        return runtime_auth
    if context.get("runtime_auth_required"):
        raise SellerSpriteConfigError("显式任务凭证已随服务重启丢失，请重新提交卖家精灵任务")
    credential_scope = context.get("credential_scope")
    if credential_scope:
        from opscli.mcp.credential_cache import get_credential_cache

        base_dir = None if credential_scope == "default" else Path(str(credential_scope))
        cache = get_credential_cache(base_dir=base_dir)
        session_id = cache.get_session_id()
        if not session_id:
            raise SellerSpriteConfigError("卖家精灵任务凭证作用域未登录，请重新完成 OPS 授权后提交任务")
        actual_user_email = cache.get_email()
        if (
            expected_user_email
            and str(actual_user_email or "").strip().lower()
            != expected_user_email.strip().lower()
        ):
            raise SellerSpriteConfigError("卖家精灵任务凭证用户与提交用户不一致，请重新完成 OPS 授权后提交任务")
        return session_id, cache.get_jwt("ops")
    # 兼容升级前已经排队的旧任务；旧字段会在任务结束时清空。
    session_id = context.get("session_id")
    if not session_id and require_auth:
        raise SellerSpriteConfigError("卖家精灵任务缺少 OPS 授权，禁止回退服务器默认账号")
    return str(session_id) if session_id else None, context.get("jwt")
