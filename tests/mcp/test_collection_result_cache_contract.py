import inspect

from opscli.mcp.tools.google_trends import google_trends_run
from opscli.mcp.tools.keepa import keepa_run
from opscli.mcp.tools.seller_sprite import seller_sprite_run
from opscli.seller_sprite.collection_storage_integration import (
    seller_sprite_cache_scope,
)
from opscli.seller_sprite.services.task_queue_store import (
    ACCOUNT_ROUTE_USER_BINDING,
)


def test_public_mcp_run_tools_do_not_expose_internal_cache_mode():
    for tool in (keepa_run, google_trends_run, seller_sprite_run):
        assert "cache_mode" not in inspect.signature(tool).parameters


def test_seller_sprite_dedicated_cache_scope_is_account_isolated():
    first = seller_sprite_cache_scope(
        ACCOUNT_ROUTE_USER_BINDING,
        "account-key-1",
    )
    second = seller_sprite_cache_scope(
        ACCOUNT_ROUTE_USER_BINDING,
        "account-key-2",
    )

    assert first.startswith("dedicated:")
    assert second.startswith("dedicated:")
    assert first != second
    assert "account-key" not in first


def test_seller_sprite_shared_pool_uses_common_cache_scope():
    assert seller_sprite_cache_scope(None, None) == "shared_pool"
