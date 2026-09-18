import inspect

from opscli.mcp.tools.google_trends import google_trends_run
from opscli.mcp.tools.keepa import keepa_run
from opscli.mcp.tools.seller_sprite import seller_sprite_run
from opscli.seller_sprite.collection_storage_integration import (
    build_seller_sprite_cache_identity,
    seller_sprite_cache_scope,
)
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services.task_queue_store import (
    ACCOUNT_ROUTE_USER_BINDING,
)


def test_public_mcp_run_tools_do_not_expose_internal_cache_mode():
    for tool in (keepa_run, google_trends_run, seller_sprite_run):
        assert "cache_mode" not in inspect.signature(tool).parameters


def test_seller_sprite_cache_scope_is_shared_across_account_routes():
    first = seller_sprite_cache_scope(
        ACCOUNT_ROUTE_USER_BINDING,
        "account-key-1",
    )
    second = seller_sprite_cache_scope(
        ACCOUNT_ROUTE_USER_BINDING,
        "account-key-2",
    )

    assert first == "shared_pool"
    assert second == "shared_pool"


def test_seller_sprite_shared_pool_uses_common_cache_scope():
    assert seller_sprite_cache_scope(None, None) == "shared_pool"


def test_equivalent_table_export_formats_share_seller_sprite_cache_key():
    xls_key, xls_scope = build_seller_sprite_cache_identity(
        SellerSpriteScenarioRequest(
            scenario="keyword-reverse",
            site="us",
            period="30D",
            params={"asin": "B0TEST"},
            export_format="xls",
        ),
        account_route=None,
        requested_account_key=None,
    )
    xlsx_key, xlsx_scope = build_seller_sprite_cache_identity(
        SellerSpriteScenarioRequest(
            scenario="keyword-reverse",
            site="US",
            period="30d",
            params={"asin": "B0TEST"},
            export_format="xlsx",
        ),
        account_route="user_binding",
        requested_account_key="account-key-1",
    )

    assert xls_key == xlsx_key
    assert xls_scope == xlsx_scope == "shared_pool"
