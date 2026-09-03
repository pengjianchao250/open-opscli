"""Tests for the Collector SellerSprite prefetch executor."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from opscli.collector_mcp import prefetch as prefetch_module
from opscli.collector_mcp.prefetch import CollectorPrefetchRuntime
from opscli.mcp.tools.seller_sprite import _build_request
from opscli.seller_sprite.collection_storage_integration import (
    build_seller_sprite_cache_identity,
)
from opscli.shared.prefetch_schedule.models import PrefetchRunClaim


def test_seller_sprite_prefetch_uses_same_cache_fingerprint_as_mcp(monkeypatch):
    """Equivalent prefetch and MCP requests must share a cache identity."""

    class Scheduler:
        settings = SimpleNamespace(task_timeout_seconds=1)

        def __init__(self):
            self.request = None

        def job_status(self, _job_id):
            raise ValueError("not queued")

        async def enqueue(self, request, **kwargs):
            self.request = request
            assert kwargs == {
                "credential_scope": "default",
                "expected_user_email": "service@example.com",
            }
            return {"job_id": request.job_id, "state": "succeeded"}

    scheduler = Scheduler()
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: scheduler,
    )
    monkeypatch.setattr(
        prefetch_module,
        "load_prefetch_service_auth",
        lambda _settings, required: ("session", None),
    )

    storage = SimpleNamespace(
        settings=SimpleNamespace(enabled=False, mysql=None),
    )
    runtime = CollectorPrefetchRuntime(storage, seller_sprite_enabled=True)
    runtime.settings = SimpleNamespace(
        service_credential_scope="default",
        service_user_email="service@example.com",
    )
    claim = PrefetchRunClaim(
        run_id=1,
        schedule_id=1,
        source_system="seller_sprite",
        scenario="keyword-reverse",
        request={
            "params": {"asin": "B0TEST"},
            "site": "US",
            "period": "30d",
            "page_size": 100,
            "export_format": "xls",
        },
        trigger_type="manual",
        scheduled_for=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )

    result = asyncio.run(runtime._execute_seller_sprite(claim))

    assert result["success"] is True
    assert scheduler.request is not None
    mcp_request = _build_request(
        scenario="keyword-reverse",
        params={"asin": "B0TEST"},
        site="US",
        period="30d",
        page_size=100,
        export_format="xls",
        page_prepare=None,
        task_interval_seconds=None,
        cooldown_seconds=None,
        output_dir=None,
        job_id=None,
    )
    prefetch_identity = build_seller_sprite_cache_identity(
        scheduler.request,
        account_route="shared_pool",
        requested_account_key=None,
    )
    mcp_identity = build_seller_sprite_cache_identity(
        mcp_request,
        account_route="shared_pool",
        requested_account_key=None,
    )
    assert scheduler.request.mode == "browser-route"
    assert prefetch_identity == mcp_identity
