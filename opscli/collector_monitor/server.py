"""Collector Monitor 独立 Uvicorn 服务入口。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from opscli.collector_monitor.storage.account_repository import AccountMonitorRepository
from opscli.collector_monitor.classifier import ClassificationPolicy
from opscli.collector_monitor.config import (
    MonitorSettings,
    load_settings,
    validate_database_paths,
    validate_settings,
)
from opscli.collector_monitor.notifier import WeComIncidentNotifier
from opscli.collector_monitor.repository import ReadOnlySellerSpriteRepository
from opscli.collector_monitor.service import CollectorMonitorService
from opscli.collector_monitor.state import MonitorStateStore


def build_service(settings: MonitorSettings) -> CollectorMonitorService:
    """根据配置组装只读监控服务。"""
    settings = validate_settings(settings)
    policy = ClassificationPolicy(
        stalled_threshold=settings.stalled_threshold,
        queue_threshold=settings.queue_threshold,
        runtime_stale_threshold=settings.runtime_stale_threshold,
        orphan_required_scans=settings.orphan_required_scans,
    )
    binding_db_path = (
        settings.account_binding_db_path
        or settings.queue_db_path.parent / "account_bindings.sqlite3"
    )
    quota_db_path = (
        settings.quota_db_path
        or settings.queue_db_path.parent.parent / "mcp_quota" / "quota.sqlite3"
    )
    validate_database_paths(binding_db_path, settings.state_db_path)
    validate_database_paths(quota_db_path, settings.state_db_path)
    return CollectorMonitorService(
        settings,
        repository=ReadOnlySellerSpriteRepository(
            settings.queue_db_path,
            policy=policy,
        ),
        state_store=MonitorStateStore(
            settings.state_db_path,
            cooldown_seconds=settings.alert_cooldown,
            protected_db_path=settings.queue_db_path,
        ),
        notifier=WeComIncidentNotifier(settings.webhook_file),
        account_repository=AccountMonitorRepository(
            queue_db_path=settings.queue_db_path,
            binding_db_path=binding_db_path,
            quota_db_path=quota_db_path,
        ),
    )


def create_application(settings: MonitorSettings | None = None) -> Any:
    """创建供 Uvicorn 或测试使用的 Starlette 应用。"""
    from opscli.collector_monitor.app import create_app

    effective = settings or load_settings()
    return create_app(build_service(effective))


def run(
    argv: Sequence[str] | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """运行服务；console entry 解析 argv，直接调用仍可显式传参。"""
    import uvicorn

    if host is None and port is None:
        parser = argparse.ArgumentParser(description="运行 Collector Monitor 只读服务")
        parser.add_argument("--host", help="监听地址")
        parser.add_argument("--port", type=int, choices=range(1, 65536), metavar="PORT")
        args = parser.parse_args(argv)
        host, port = args.host, args.port
    settings = load_settings()
    uvicorn.run(
        create_application(settings),
        host=host or settings.host,
        port=port or settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
