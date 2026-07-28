import pytest

from opscli.shopify.domain.exceptions import ShopifyParamsError
from opscli.shopify.services.manager import ShopifyManager
from opscli.shopify.services.payload_builder import ShopifyTaskPayloadBuilder


class FakeFeedTaskClient:
    def __init__(self) -> None:
        self.created_payloads = []

    def create(self, payload: dict) -> dict:
        self.created_payloads.append(payload)
        return {"id": "TASK-1", "payload": payload}


def make_manager(cache: dict[int, dict] | None = None) -> ShopifyManager:
    manager = object.__new__(ShopifyManager)
    manager.feedtask_client = FakeFeedTaskClient()
    manager.payload_builder = ShopifyTaskPayloadBuilder()
    manager._product_cache = cache or {}
    return manager


def test_update_prices_dry_run_returns_polaris_payload_without_submit() -> None:
    manager = make_manager(
        {
            101: {
                "listing_id": 101,
                "sku": "SKU-101",
                "price": "10.00",
                "sale_price": "9.00",
                "shopify_product_id": 9001,
            }
        }
    )

    result = manager.update_prices(
        1132,
        [{"listing_id": "101", "new_price": 12.34}],
        reason="test",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["will_submit"] is False
    assert result["direct_shopify_api"] is False
    assert result["submit_target"] == "polaris_create_custom_task"
    assert result["operate_method"] == "shopifyModifyPrice"
    assert result["payload"]["task_content"]["data_content"]["site_id"] == 1132
    assert result["payload"]["task_content"]["shopify_product_variant_id"] == [101]
    assert result["payload"]["task_content"]["shopify_product_id"] == 9001
    assert manager.feedtask_client.created_payloads == []


def test_update_prices_submit_still_uses_feedtask_client() -> None:
    manager = make_manager(
        {
            101: {
                "listing_id": 101,
                "sku": "SKU-101",
                "price": "10.00",
                "shopify_product_id": 9001,
            }
        }
    )

    result = manager.update_prices(
        1132,
        [{"listing_id": 101, "new_price": 12.34}],
        dry_run=False,
    )

    assert result["id"] == "TASK-1"
    assert len(manager.feedtask_client.created_payloads) == 1
    payload = manager.feedtask_client.created_payloads[0]
    assert payload["task_content"]["template_content"]["fields"][0]["__config__"][
        "operateMethod"
    ] == "shopifyModifyPrice"


def test_empty_variant_ids_fail_before_submit() -> None:
    manager = make_manager()

    with pytest.raises(ShopifyParamsError, match="shopify_product_variant_id"):
        manager.set_active(1132, [], [], dry_run=True)

    assert manager.feedtask_client.created_payloads == []


def test_missing_template_id_fails_before_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "opscli.shopify.services.template_registry.get_shopify_template_id",
        lambda operation: 0,
    )
    manager = make_manager()

    with pytest.raises(ShopifyParamsError, match="缺少有效模板 ID"):
        manager.set_active(1132, [9001], [101], dry_run=True)

    assert manager.feedtask_client.created_payloads == []
