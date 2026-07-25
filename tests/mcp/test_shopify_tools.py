import asyncio

from opscli.mcp.tools import shopify as shopify_tools


def run(coro):
    return asyncio.run(coro)


class DummyManager:
    def __init__(self) -> None:
        self.loaded_sites = []
        self.calls = []

    def list_products(self, site_id: int, **kwargs) -> dict:
        self.loaded_sites.append((site_id, kwargs))
        return {"data": []}

    def update_prices(
        self,
        site_id: int,
        updates: list[dict],
        *,
        reason: str = "",
        dry_run: bool = False,
    ) -> dict:
        self.calls.append(
            {
                "method": "update_prices",
                "site_id": site_id,
                "updates": updates,
                "reason": reason,
                "dry_run": dry_run,
            }
        )
        return {"dry_run": dry_run, "updates": updates}

    def set_active(
        self,
        site_id: int,
        product_ids: list[int],
        variant_ids: list[int],
        *,
        dry_run: bool = False,
    ) -> dict:
        self.calls.append(
            {
                "method": "set_active",
                "site_id": site_id,
                "product_ids": product_ids,
                "variant_ids": variant_ids,
                "dry_run": dry_run,
            }
        )
        return {"dry_run": dry_run, "variant_ids": variant_ids}


def patch_auth_and_manager(monkeypatch):
    manager = DummyManager()
    monkeypatch.setattr(shopify_tools, "_get_auth_pair", lambda *args: ("SID", "JWT"))
    monkeypatch.setattr(
        shopify_tools, "_shopify_manager", lambda jwt=None, session_id=None: manager
    )
    return manager


def test_mcp_update_prices_defaults_to_dry_run_and_parses_json_string(monkeypatch) -> None:
    manager = patch_auth_and_manager(monkeypatch)

    result = run(
        shopify_tools.shopify_update_prices(
            1132,
            '[{"listing_id": "101", "new_price": 12.34}]',
            reason="test",
        )
    )

    assert result["success"] is True
    assert result["data"]["dry_run"] is True
    assert manager.loaded_sites == [(1132, {"limit": 100})]
    assert manager.calls[0]["updates"] == [{"listing_id": "101", "new_price": 12.34}]
    assert manager.calls[0]["dry_run"] is True


def test_mcp_explicit_submit_passes_dry_run_false(monkeypatch) -> None:
    manager = patch_auth_and_manager(monkeypatch)

    result = run(
        shopify_tools.shopify_publish(
            1132,
            "[101, 102]",
            "[9001]",
            dry_run=False,
        )
    )

    assert result["success"] is True
    assert result["data"]["dry_run"] is False
    assert manager.calls[0]["variant_ids"] == [101, 102]
    assert manager.calls[0]["product_ids"] == [9001]
