"""Keepa Tracking 内部 API 回归测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx

from opscli.keepa.domain.exceptions import KeepaApiError, KeepaConfigError
from opscli.keepa.tracking import (
    KeepaTrackingClient,
    KeepaTrackingService,
    TrackingCreation,
    TrackingNotifyIf,
    TrackingThresholdValue,
)


def _run(coro):
    return asyncio.run(coro)


def _creation(asin: str = "B003IEUAZK") -> TrackingCreation:
    return TrackingCreation(
        asin=asin,
        ttl=0,
        expire_notify=False,
        desired_prices_in_main_currency=True,
        main_domain_id=1,
        update_interval=2,
        metadata="monitor-42",
        threshold_values=(
            TrackingThresholdValue(
                threshold_value=1999,
                domain=1,
                csv_type=0,
                is_drop=True,
            ),
        ),
        notify_if=(TrackingNotifyIf(domain=1, csv_type=0, notify_if_type=1),),
        notification_type=(False, False, False, False, False, True, False),
        individual_notification_interval=-1,
    )


@respx.mock
def test_tracking_client_posts_batch_as_json_without_putting_payload_in_query():
    route = respx.post("https://api.keepa.test/tracking").mock(
        return_value=httpx.Response(200, json={"trackings": [{"asin": "B003IEUAZK"}]})
    )

    async def scenario():
        async with KeepaTrackingClient(
            api_key="secret-keepa-key",
            base_url="https://api.keepa.test",
        ) as client:
            return await client.add([_creation().to_api_dict()], list_name="price-watch")

    result = _run(scenario())

    assert result["trackings"][0]["asin"] == "B003IEUAZK"
    request = route.calls.last.request
    assert request.url.params["key"] == "secret-keepa-key"
    assert request.url.params["type"] == "add"
    assert request.url.params["list"] == "price-watch"
    assert "tracking" not in request.url.params
    assert json.loads(request.content) == [_creation().to_api_dict()]


@respx.mock
def test_tracking_client_maps_error_without_exposing_api_key():
    respx.get("https://api.keepa.test/tracking").mock(
        return_value=httpx.Response(
            400,
            json={"error": "key secret-keepa-key is invalid"},
        )
    )

    async def scenario():
        async with KeepaTrackingClient(
            api_key="secret-keepa-key",
            base_url="https://api.keepa.test",
        ) as client:
            with pytest.raises(KeepaApiError) as excinfo:
                await client.list()
            return excinfo.value

    error = _run(scenario())

    assert "secret-keepa-key" not in str(error)
    assert "secret-keepa-key" not in (error.response_excerpt or "")
    assert "secret-keepa-key" not in str(error.response_payload)


@respx.mock
def test_tracking_client_maps_all_get_operations_to_official_parameters():
    route = respx.get("https://api.keepa.test/tracking").mock(
        return_value=httpx.Response(200, json={"tokensConsumed": 0})
    )

    async def scenario():
        async with KeepaTrackingClient(
            api_key="secret-keepa-key",
            base_url="https://api.keepa.test",
        ) as client:
            await client.get("B003IEUAZK", list_name="price-watch")
            await client.list(list_name="price-watch", asins_only=True)
            await client.list_names()
            await client.notifications(
                since=7_662_080,
                revise=True,
                read_only=True,
                include_all=False,
                list_name="price-watch",
            )
            await client.remove("B003IEUAZK", list_name="price-watch")
            await client.remove_all(list_name="price-watch")
            await client.set_webhook("https://example.com/keepa")

    _run(scenario())

    params = [dict(call.request.url.params) for call in route.calls]
    assert params == [
        {
            "key": "secret-keepa-key",
            "type": "get",
            "asin": "B003IEUAZK",
            "list": "price-watch",
        },
        {
            "key": "secret-keepa-key",
            "type": "list",
            "list": "price-watch",
            "asins-only": "1",
        },
        {"key": "secret-keepa-key", "type": "listNames"},
        {
            "key": "secret-keepa-key",
            "type": "notification",
            "since": "7662080",
            "revise": "1",
            "readOnly": "1",
            "all": "0",
            "list": "price-watch",
        },
        {
            "key": "secret-keepa-key",
            "type": "remove",
            "asin": "B003IEUAZK",
            "list": "price-watch",
        },
        {
            "key": "secret-keepa-key",
            "type": "removeAll",
            "list": "price-watch",
        },
        {
            "key": "secret-keepa-key",
            "type": "webhook",
            "url": "https://example.com/keepa",
        },
    ]


class _RecordingTrackingClient:
    """记录 Service 发往 Keepa 边界的请求。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def add(self, trackings, *, list_name=None):
        self.calls.append(("add", {"trackings": trackings, "list_name": list_name}))
        return {"trackings": trackings}

    async def get(self, asin, *, list_name=None):
        self.calls.append(("get", {"asin": asin, "list_name": list_name}))
        return {"trackings": [{"asin": asin}]}

    async def list(self, *, list_name=None, asins_only=False, page=None, per_page=None):
        self.calls.append(
            (
                "list",
                {
                    "list_name": list_name,
                    "asins_only": asins_only,
                    "page": page,
                    "per_page": per_page,
                },
            )
        )
        return {"asinList": ["B003IEUAZK"]} if asins_only else {"trackings": []}

    async def list_names(self):
        self.calls.append(("list_names", {}))
        return {"trackingListNames": ["price-watch"]}

    async def notifications(
        self,
        *,
        since,
        revise,
        read_only,
        include_all,
        list_name=None,
    ):
        self.calls.append(
            (
                "notifications",
                {
                    "since": since,
                    "revise": revise,
                    "read_only": read_only,
                    "include_all": include_all,
                    "list_name": list_name,
                },
            )
        )
        return {"notifications": []}

    async def remove(self, asin, *, list_name=None):
        self.calls.append(("remove", {"asin": asin, "list_name": list_name}))
        return {"tokensConsumed": 0}

    async def remove_all(self, *, list_name=None):
        self.calls.append(("remove_all", {"list_name": list_name}))
        return {"tokensConsumed": 0}

    async def set_webhook(self, url):
        self.calls.append(("set_webhook", {"url": url}))
        return {"tokensConsumed": 0}


def test_tracking_service_serializes_valid_creation_and_normalizes_asin():
    client = _RecordingTrackingClient()
    service = KeepaTrackingService(client)

    result = _run(service.add([_creation("b003ieuazk")], list_name="price-watch"))

    assert result["trackings"][0]["asin"] == "B003IEUAZK"
    assert client.calls == [
        (
            "add",
            {
                "trackings": [_creation().to_api_dict()],
                "list_name": "price-watch",
            },
        )
    ]


def test_tracking_service_accepts_official_creation_object_mapping():
    client = _RecordingTrackingClient()
    service = KeepaTrackingService(client)
    creation = _creation().to_api_dict()

    _run(service.add([creation]))

    assert client.calls == [("add", {"trackings": [creation], "list_name": None})]


def test_tracking_service_maps_null_notification_type_to_config_error():
    service = KeepaTrackingService(_RecordingTrackingClient())

    with pytest.raises(KeepaConfigError, match="notificationType"):
        _run(
            service.add(
                [
                    {
                        "asin": "B003IEUAZK",
                        "mainDomainId": 1,
                        "notificationType": None,
                    }
                ]
            )
        )


@pytest.mark.parametrize(
    ("creation", "message"),
    [
        (TrackingCreation(asin="bad", main_domain_id=1), "ASIN"),
        (TrackingCreation(asin="B003IEUAZK", main_domain_id=7), "mainDomainId"),
        (
            TrackingCreation(
                asin="B003IEUAZK",
                main_domain_id=1,
                update_interval=25,
            ),
            "updateInterval",
        ),
        (
            TrackingCreation(
                asin="B003IEUAZK",
                main_domain_id=1,
                notification_type=(True,),
            ),
            "notificationType",
        ),
        (
            TrackingCreation(
                asin="B003IEUAZK",
                main_domain_id=1,
                metadata="x" * 501,
            ),
            "metaData",
        ),
    ],
)
def test_tracking_service_rejects_invalid_creation_objects(creation, message):
    service = KeepaTrackingService(_RecordingTrackingClient())

    with pytest.raises(KeepaConfigError, match=message):
        _run(service.add([creation]))


def test_tracking_service_rejects_more_than_three_thousand_additions():
    service = KeepaTrackingService(_RecordingTrackingClient())

    with pytest.raises(KeepaConfigError, match="3,000"):
        _run(service.add([_creation()] * 3001))


def test_tracking_service_preview_notifications_is_read_only_by_default():
    client = _RecordingTrackingClient()
    service = KeepaTrackingService(client)

    _run(
        service.preview_notifications(
            since=7_662_080,
            revise=True,
            include_all=False,
            list_name="price-watch",
        )
    )

    assert client.calls == [
        (
            "notifications",
            {
                "since": 7_662_080,
                "revise": True,
                "read_only": True,
                "include_all": False,
                "list_name": "price-watch",
            },
        )
    ]


def test_tracking_service_requires_confirmation_for_notification_consumption():
    client = _RecordingTrackingClient()
    service = KeepaTrackingService(client)

    with pytest.raises(KeepaConfigError, match="confirm=True"):
        _run(service.consume_notifications(since=7_662_080))

    _run(service.consume_notifications(since=7_662_080, confirm=True))

    assert client.calls[-1][1]["read_only"] is False


def test_tracking_service_requires_confirmation_for_remove_all_and_webhook():
    client = _RecordingTrackingClient()
    service = KeepaTrackingService(client)

    with pytest.raises(KeepaConfigError, match="confirm=True"):
        _run(service.remove_all(list_name="price-watch"))
    with pytest.raises(KeepaConfigError, match="confirm=True"):
        _run(service.set_webhook("https://example.com/keepa"))

    _run(service.remove_all(list_name="price-watch", confirm=True))
    _run(service.set_webhook("https://example.com/keepa", confirm=True))

    assert client.calls == [
        ("remove_all", {"list_name": "price-watch"}),
        ("set_webhook", {"url": "https://example.com/keepa"}),
    ]


def test_tracking_service_rejects_unsafe_webhook_url_after_confirmation():
    service = KeepaTrackingService(_RecordingTrackingClient())

    with pytest.raises(KeepaConfigError, match="HTTPS"):
        _run(service.set_webhook("http://127.0.0.1/keepa", confirm=True))
    with pytest.raises(KeepaConfigError, match="用户名或密码"):
        _run(service.set_webhook("https://user:pass@example.com/keepa", confirm=True))


def test_tracking_service_validates_list_query_boundaries():
    service = KeepaTrackingService(_RecordingTrackingClient())

    with pytest.raises(KeepaConfigError, match="perPage"):
        _run(service.list(per_page=100_001))
    with pytest.raises(KeepaConfigError, match="asins_only"):
        _run(service.list(asins_only=True, page=0))
    with pytest.raises(KeepaConfigError, match="64"):
        _run(service.list(list_name="x" * 65))


def test_tracking_is_not_registered_as_mcp_tool():
    from opscli.mcp.tools import keepa as keepa_tools

    assert all("tracking" not in function.__name__.lower() for function in keepa_tools._ALL_TOOLS)
    assert not hasattr(keepa_tools, "keepa_tracking_add")
