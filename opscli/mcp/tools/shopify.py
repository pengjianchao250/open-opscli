"""Shopify 工具模块。

将 opscli shopify 子模块的核心能力暴露为 MCP 工具：
- shopify_list_shops              — 列出有权限的店铺
- shopify_list_products           — 列出指定店铺的商品
- shopify_search_by_sku           — 通过 seller_sku 搜索商品
- shopify_update_prices           — 批量修改价格（listing_id）
- shopify_update_inventory        — 批量修改库存（listing_id）
- shopify_update_price_by_sku     — 通过 seller_sku 修改价格
- shopify_update_inventory_by_sku — 通过 seller_sku 修改库存
- shopify_publish                 — 批量上架
- shopify_unpublish               — 批量下架
- shopify_delete_products         — 批量删除（设为草稿）

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg, _shopify_manager

# SKU 未找到关联关系时的统一提示，明确告知 AI 停止操作
_SKU_NO_ASSOCIATION = (
    "seller_sku {sku} 未找到产品与 listing 的关联关系，无法执行操作。"
    "请直接告知用户该 SKU 无关联关系，不要尝试通过 listing_id 或其他方式继续操作。"
)


def _sku_not_found_response(sku: str) -> dict:
    """SKU 无关联关系时返回统一响应，阻止 AI 继续尝试其他操作。"""
    return {
        "success": False,
        "data": None,
        "error": {
            "code": "SKU_NO_ASSOCIATION",
            "message": _SKU_NO_ASSOCIATION.format(sku=sku),
            "stop": True,
        },
    }


async def shopify_list_shops(
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """获取当前用户有权限的 Shopify 店铺列表。"""
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        result = _shopify_manager(jwt=jw, session_id=sid).list_shops()
        return _ok([s.to_dict() for s in result])
    except Exception as exc:
        return _err(exc)


async def shopify_list_products(
    site_id: int,
    page: int = 1,
    limit: int = 20,
    keyword: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """获取指定店铺的商品列表。

    Args:
        site_id:  站点 ID（从 shopify_list_shops 获取）
        page:     分页页码（默认 1）
        limit:    每页条数（默认 20）
        keyword:  关键词搜索
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        result = _shopify_manager(jwt=jw, session_id=sid).list_products(
            site_id, page=page, limit=limit, keyword=keyword
        )
        return _ok(result.get("data"))
    except Exception as exc:
        return _err(exc)


async def shopify_update_prices(
    site_id: int,
    updates: list[dict],
    reason: str = "",
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """批量修改商品价格，生成工单（listing_id 模式）。

    【重要】本工具仅用于用户明确提供了 listing_id 的场景。
    如果用户只提供了 seller_sku，必须使用 shopify_update_price_by_sku。
    当 shopify_update_price_by_sku 返回 SKU_NO_ASSOCIATION 错误时，
    禁止回退使用本工具，应直接告知用户该 SKU 无关联关系。

    默认 dry_run=True，只预览 Polaris 工单 payload；显式传 dry_run=False 才提交工单。
    修改前需先调用 shopify_list_products 查询商品，确保商品数据已加载到缓存。

    Args:
        site_id:  站点 ID
        updates:  价格修改列表，每项包含 listing_id + new_price（可选 new_sale_price）
                  例: [{"listing_id": 1510, "new_price": 29.99, "new_sale_price": 25.0}]
        reason:   修改原因
        dry_run:  是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        updates = _parse_json_arg(updates, list)
        manager = _shopify_manager(jwt=jw, session_id=sid)
        manager.list_products(site_id, limit=100)
        result = manager.update_prices(
            site_id, updates, reason=reason, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def shopify_update_inventory(
    site_id: int,
    updates: list[dict],
    reason: str = "",
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """批量修改商品库存，生成工单（listing_id 模式）。

    【重要】本工具仅用于用户明确提供了 listing_id 的场景。
    如果用户只提供了 seller_sku，必须使用 shopify_update_inventory_by_sku。
    当 shopify_update_inventory_by_sku 返回 SKU_NO_ASSOCIATION 错误时，
    禁止回退使用本工具，应直接告知用户该 SKU 无关联关系。

    默认 dry_run=True，只预览 Polaris 工单 payload；显式传 dry_run=False 才提交工单。
    修改前需先调用 shopify_list_products 查询商品，确保商品数据已加载到缓存。

    Args:
        site_id:  站点 ID
        updates:  库存修改列表，每项包含 listing_id + new_inventory_quantity
                  例: [{"listing_id": 1509, "new_inventory_quantity": 100}]
        reason:   修改原因
        dry_run:  是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        updates = _parse_json_arg(updates, list)
        manager = _shopify_manager(jwt=jw, session_id=sid)
        manager.list_products(site_id, limit=100)
        result = manager.update_inventory(
            site_id, updates, reason=reason, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def shopify_publish(
    site_id: int,
    variant_ids: list[int],
    product_ids: list[int],
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """批量上架商品（设置活跃状态，listing_id 模式）。

    【重要】如果用户只提供了 seller_sku，必须使用 shopify_publish_by_sku。
    当 *_by_sku 返回 SKU_NO_ASSOCIATION 错误时，禁止回退使用本工具。

    Args:
        site_id:     站点 ID
        variant_ids: 变体 ID 列表
        product_ids: 商品 ID 列表
        dry_run:    是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        variant_ids = _parse_json_arg(variant_ids, list)
        product_ids = _parse_json_arg(product_ids, list)
        result = _shopify_manager(jwt=jw, session_id=sid).set_active(
            site_id, product_ids, variant_ids, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def shopify_unpublish(
    site_id: int,
    variant_ids: list[int],
    product_ids: list[int],
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """批量下架商品（设置草稿状态，listing_id 模式）。

    【重要】如果用户只提供了 seller_sku，必须使用 shopify_unpublish_by_sku。
    当 *_by_sku 返回 SKU_NO_ASSOCIATION 错误时，禁止回退使用本工具。

    Args:
        site_id:     站点 ID
        variant_ids: 变体 ID 列表
        product_ids: 商品 ID 列表
        dry_run:    是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        variant_ids = _parse_json_arg(variant_ids, list)
        product_ids = _parse_json_arg(product_ids, list)
        result = _shopify_manager(jwt=jw, session_id=sid).set_draft(
            site_id, product_ids, variant_ids, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def shopify_delete_products(
    site_id: int,
    variant_ids: list[int],
    product_ids: list[int],
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """批量删除商品（listing_id 模式）。

    【重要】如果用户只提供了 seller_sku，必须使用 shopify_delete_by_sku。
    当 *_by_sku 返回 SKU_NO_ASSOCIATION 错误时，禁止回退使用本工具。

    Args:
        site_id:     站点 ID
        variant_ids: 变体 ID 列表
        product_ids: 商品 ID 列表
        dry_run:    是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        variant_ids = _parse_json_arg(variant_ids, list)
        product_ids = _parse_json_arg(product_ids, list)
        result = _shopify_manager(jwt=jw, session_id=sid).delete_products(
            site_id, product_ids, variant_ids, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ── seller_sku 快捷工具 ─────────────────────────────────────


async def shopify_search_by_sku(
    sellsku: str,
    site_id: int | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 seller_sku（卖家自定义 SKU）搜索商品。

    适用于用户只提供 seller_sku 而不知道 listing_id 的场景。
    搜索结果会自动缓存，可直接用于后续工单操作。

    Args:
        sellsku:  卖家自定义 SKU（如 QD74024-4）
        site_id:  站点 ID（可选，不传则搜索所有站点）
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        result = _shopify_manager(jwt=jw, session_id=sid).search_by_seller_sku(
            sellsku, site_id=site_id
        )
        if not result:
            return _sku_not_found_response(sellsku)
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def shopify_update_inventory_by_sku(
    sellsku: str,
    quantity: int,
    site_id: int | None = None,
    reason: str = "",
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 seller_sku 修改商品库存，自动搜索商品并生成工单。

    适用场景：用户说"帮我把平台sku QD74024-4改库存，改成20"。
    无需先查询 listing_id，只需提供 seller_sku 和目标库存数量。

    Args:
        sellsku:  卖家自定义 SKU（如 QD74024-4）
        quantity: 新库存数量（绝对值，设 0 即清零）
        site_id:  站点 ID（可选）
        reason:   操作原因
        dry_run:  是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        manager = _shopify_manager(jwt=jw, session_id=sid)
        result = manager.update_inventory_by_sku(
            sellsku, quantity, site_id=site_id, reason=reason, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        from opscli.shopify.domain.exceptions import ShopifyNotFoundError
        if isinstance(exc, ShopifyNotFoundError):
            return _sku_not_found_response(sellsku)
        return _err(exc)


async def shopify_update_price_by_sku(
    sellsku: str,
    new_price: float | None = None,
    new_sale_price: float | None = None,
    site_id: int | None = None,
    reason: str = "",
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 seller_sku 修改商品价格，自动搜索商品并生成工单。

    适用场景：用户说"帮我把平台sku QD74024-4改价，价格改成29.99"。
    至少需要传 new_price 或 new_sale_price 之一。

    Args:
        sellsku:        卖家自定义 SKU
        new_price:      新原价（可选）
        new_sale_price: 新销售价（可选）
        site_id:        站点 ID（可选）
        reason:         操作原因
        dry_run:        是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        manager = _shopify_manager(jwt=jw, session_id=sid)
        result = manager.update_price_by_sku(
            sellsku, new_price, new_sale_price=new_sale_price,
            site_id=site_id, reason=reason, dry_run=dry_run,
        )
        return _ok(result)
    except Exception as exc:
        from opscli.shopify.domain.exceptions import ShopifyNotFoundError
        if isinstance(exc, ShopifyNotFoundError):
            return _sku_not_found_response(sellsku)
        return _err(exc)


async def shopify_publish_by_sku(
    sellsku: str,
    site_id: int | None = None,
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 seller_sku 上架商品（设置活跃状态）。

    Args:
        sellsku:  卖家自定义 SKU
        site_id:  站点 ID（可选）
        dry_run:  是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        result = _shopify_manager(jwt=jw, session_id=sid).publish_by_sku(
            sellsku, site_id=site_id, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        from opscli.shopify.domain.exceptions import ShopifyNotFoundError
        if isinstance(exc, ShopifyNotFoundError):
            return _sku_not_found_response(sellsku)
        return _err(exc)


async def shopify_unpublish_by_sku(
    sellsku: str,
    site_id: int | None = None,
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 seller_sku 下架商品（设置草稿状态）。

    Args:
        sellsku:  卖家自定义 SKU
        site_id:  站点 ID（可选）
        dry_run:  是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        result = _shopify_manager(jwt=jw, session_id=sid).unpublish_by_sku(
            sellsku, site_id=site_id, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        from opscli.shopify.domain.exceptions import ShopifyNotFoundError
        if isinstance(exc, ShopifyNotFoundError):
            return _sku_not_found_response(sellsku)
        return _err(exc)


async def shopify_delete_by_sku(
    sellsku: str,
    site_id: int | None = None,
    dry_run: bool = True,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """通过 seller_sku 删除商品。

    Args:
        sellsku:  卖家自定义 SKU
        site_id:  站点 ID（可选）
        dry_run:  是否仅预览工单 payload，默认 True
    """
    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id"))
    try:
        result = _shopify_manager(jwt=jw, session_id=sid).delete_by_sku(
            sellsku, site_id=site_id, dry_run=dry_run
        )
        return _ok(result)
    except Exception as exc:
        from opscli.shopify.domain.exceptions import ShopifyNotFoundError
        if isinstance(exc, ShopifyNotFoundError):
            return _sku_not_found_response(sellsku)
        return _err(exc)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    shopify_list_shops,
    shopify_list_products,
    shopify_search_by_sku,
    shopify_update_prices,
    shopify_update_inventory,
    shopify_update_price_by_sku,
    shopify_update_inventory_by_sku,
    shopify_publish,
    shopify_unpublish,
    shopify_delete_products,
    shopify_publish_by_sku,
    shopify_unpublish_by_sku,
    shopify_delete_by_sku,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 shopify_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
