"""Shopify 刊登 CLI 命令。

提供店铺查询、商品查询和工单操作的命令行入口。
所有命令输出统一 JSON 格式。
"""

import json
import sys
from typing import Optional

import typer

from opscli.shopify.domain.exceptions import ShopifyError
from opscli.shopify.services.manager import ShopifyManager

app = typer.Typer(help="Shopify 刊登管理")

# 子命令组
shop_app = typer.Typer(help="店铺管理")
product_app = typer.Typer(help="商品查询")
workorder_app = typer.Typer(help="工单操作")

app.add_typer(shop_app, name="shop")
app.add_typer(product_app, name="product")
app.add_typer(workorder_app, name="workorder")


def _emit(payload: dict, *, pretty: bool = True) -> None:
    """输出 JSON 结果。"""
    indent = 2 if pretty else None
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=indent))


def _error_payload(command: str, exc: Exception) -> dict:
    """构造错误输出，识别认证异常并给出友好提示。"""
    from opscli.auth.exceptions import NotAuthenticatedError

    if isinstance(exc, ShopifyError):
        return {"success": False, "command": command, "data": None, "error": exc.to_dict()}
    if isinstance(exc, NotAuthenticatedError):
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": {
                "code": "NOT_AUTHENTICATED",
                "message": str(exc),
                "hint": "请先执行 opscli auth login 完成 polaris 系统授权登录",
            },
        }
    return {"success": False, "command": command, "data": None, "error": {"code": "UNKNOWN", "message": str(exc)}}


def _check_auth() -> None:
    """执行命令前检查 polaris 登录状态，未登录则直接报错退出。"""
    from opscli.auth import AuthClient
    from opscli.auth.exceptions import NotAuthenticatedError

    client = AuthClient()
    if not client.is_authenticated():
        _emit({
            "success": False,
            "command": "shopify",
            "data": None,
            "error": {
                "code": "NOT_AUTHENTICATED",
                "message": "未登录，请先完成 polaris 授权",
                "hint": "执行 opscli auth login 完成登录后重试",
            },
        })
        raise typer.Exit(1)


# ── 店铺命令 ──────────────────────────────────────────────

@shop_app.command("list")
def shop_list() -> None:
    """列出有权限的 Shopify 店铺。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        shops = manager.list_shops()
        _emit({
            "success": True,
            "command": "shopify shop list",
            "data": [s.to_dict() for s in shops],
            "error": None,
        })
    except Exception as exc:
        _emit(_error_payload("shopify shop list", exc))
        sys.exit(1)


# ── 商品命令 ──────────────────────────────────────────────

@product_app.command("list")
def product_list(
    site_id: Optional[int] = typer.Option(None, "--site", help="站点 ID（不传则查询所有）"),
    keyword: Optional[str] = typer.Option(None, "--keyword", help="关键词搜索"),
    page: int = typer.Option(1, "--page", help="分页页码"),
    limit: int = typer.Option(20, "--limit", help="每页条数"),
) -> None:
    """列出商品。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        result = manager.list_products(site_id, page=page, limit=limit, keyword=keyword)
        _emit({"success": True, "command": "shopify product list", "data": result.get("data"), "error": None})
    except Exception as exc:
        _emit(_error_payload("shopify product list", exc))
        sys.exit(1)


# ── 工具函数 ──────────────────────────────────────────────


def _resolve_sellsku_list(
    manager: ShopifyManager,
    sellsku: str,
    site_id: int,
) -> tuple[list[dict], int]:
    """解析逗号分隔的 seller_sku 列表，返回 (商品列表, site_id)。

    每个 SKU 都会通过两步验证并缓存到 manager._product_cache。
    """
    skus = [s.strip() for s in sellsku.split(",") if s.strip()]
    if not skus:
        raise ValueError("--sellsku 不能为空")

    resolved_site_id = None
    products = []
    for sku in skus:
        product, sid = manager._resolve_product_by_sku(sku, site_id=site_id)
        products.append(product)
        if resolved_site_id is None:
            resolved_site_id = sid

    return products, resolved_site_id or site_id


def _resolve_items_json(
    manager: ShopifyManager,
    raw_updates: list[dict],
    site_id: int,
) -> tuple[list[dict], int]:
    """解析 --items JSON，支持 listing_id 和 seller_sku 两种格式。

    seller_sku 格式会自动解析为 listing_id 并缓存商品数据。
    """
    has_sellsku = any("seller_sku" in item for item in raw_updates)
    resolved_site_id = site_id
    updates = []

    for item in raw_updates:
        if "seller_sku" in item:
            # seller_sku 模式：自动解析为 listing_id
            product, sid = manager._resolve_product_by_sku(
                item["seller_sku"], site_id=site_id
            )
            lid = product.get("listing_id") or product.get("id")
            update = {k: v for k, v in item.items() if k != "seller_sku"}
            update["listing_id"] = lid
            updates.append(update)
            resolved_site_id = sid
        else:
            updates.append(item)

    # 纯 listing_id 模式需要先加载缓存
    if not has_sellsku:
        manager.list_products(site_id, limit=100)

    return updates, resolved_site_id


# ── 工单命令 ──────────────────────────────────────────────

@workorder_app.command("update-price")
def update_price(
    site_id: int = typer.Option(..., "--site", help="站点 ID"),
    items_file: str = typer.Option("", "--items", help="JSON 文件路径，支持 listing_id 或 seller_sku"),
    sellsku: str = typer.Option("", "--sellsku", help="卖家 SKU，多个用逗号分隔（与 --items 二选一）"),
    new_price: Optional[float] = typer.Option(None, "--price", help="新原价（配合 --sellsku 使用）"),
    new_sale_price: Optional[float] = typer.Option(None, "--sale-price", help="新销售价（配合 --sellsku 使用）"),
    reason: str = typer.Option("", "--reason", help="操作原因"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览 Polaris 工单 payload，不提交"),
) -> None:
    """批量修改商品价格。支持 --items JSON 文件或 --sellsku 快捷模式。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        if sellsku:
            # 快捷模式：逗号分隔的 seller_sku，统一价格
            if new_price is None and new_sale_price is None:
                _emit(_error_payload("shopify workorder update-price", ValueError("--sellsku 模式需要 --price 或 --sale-price 参数")))
                raise typer.Exit(1)
            products, resolved_site_id = _resolve_sellsku_list(manager, sellsku, site_id)
            updates = []
            for product in products:
                lid = product.get("listing_id") or product.get("id")
                u: dict = {"listing_id": lid}
                if new_price is not None:
                    u["new_price"] = new_price
                if new_sale_price is not None:
                    u["new_sale_price"] = new_sale_price
                updates.append(u)
            result = manager.update_prices(
                resolved_site_id, updates, reason=reason, dry_run=dry_run
            )
        elif items_file:
            # JSON 文件模式：支持 listing_id 和 seller_sku 两种格式
            with open(items_file, encoding="utf-8") as f:
                raw_updates = json.load(f)
            updates, resolved_site_id = _resolve_items_json(manager, raw_updates, site_id)
            result = manager.update_prices(
                resolved_site_id, updates, reason=reason, dry_run=dry_run
            )
        else:
            _emit(_error_payload("shopify workorder update-price", ValueError("需要 --items 或 --sellsku 参数")))
            raise typer.Exit(1)
        _emit({"success": True, "command": "shopify workorder update-price", "data": result, "error": None})
    except SystemExit:
        raise
    except Exception as exc:
        _emit(_error_payload("shopify workorder update-price", exc))
        sys.exit(1)


@workorder_app.command("update-stock")
def update_stock(
    site_id: int = typer.Option(..., "--site", help="站点 ID"),
    items_file: str = typer.Option("", "--items", help="JSON 文件路径，支持 listing_id 或 seller_sku"),
    sellsku: str = typer.Option("", "--sellsku", help="卖家 SKU，多个用逗号分隔（与 --items 二选一）"),
    quantity: Optional[int] = typer.Option(None, "--quantity", help="新库存数量（配合 --sellsku 使用）"),
    reason: str = typer.Option("", "--reason", help="操作原因"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览 Polaris 工单 payload，不提交"),
) -> None:
    """批量修改商品库存。支持 --items JSON 文件或 --sellsku 快捷模式。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        if sellsku:
            # 快捷模式：逗号分隔的 seller_sku，统一库存
            if quantity is None:
                _emit(_error_payload("shopify workorder update-stock", ValueError("--sellsku 模式需要 --quantity 参数")))
                raise typer.Exit(1)
            products, resolved_site_id = _resolve_sellsku_list(manager, sellsku, site_id)
            updates = [
                {
                    "listing_id": p.get("listing_id") or p.get("id"),
                    "new_inventory_quantity": quantity,
                }
                for p in products
            ]
            result = manager.update_inventory(
                resolved_site_id, updates, reason=reason, dry_run=dry_run
            )
        elif items_file:
            # JSON 文件模式：支持 listing_id 和 seller_sku 两种格式
            with open(items_file, encoding="utf-8") as f:
                raw_updates = json.load(f)
            updates, resolved_site_id = _resolve_items_json(manager, raw_updates, site_id)
            result = manager.update_inventory(
                resolved_site_id, updates, reason=reason, dry_run=dry_run
            )
        else:
            _emit(_error_payload("shopify workorder update-stock", ValueError("需要 --items 或 --sellsku 参数")))
            raise typer.Exit(1)
        _emit({"success": True, "command": "shopify workorder update-stock", "data": result, "error": None})
    except SystemExit:
        raise
    except Exception as exc:
        _emit(_error_payload("shopify workorder update-stock", exc))
        sys.exit(1)


@workorder_app.command("publish")
def publish(
    site_id: int = typer.Option(..., "--site", help="站点 ID"),
    sellsku: str = typer.Option("", "--sellsku", help="卖家 SKU，多个用逗号分隔（与 --variants 二选一）"),
    variants: str = typer.Option("", "--variants", help="variant ID 列表 JSON，如 [1510,1511]"),
    products: str = typer.Option("[]", "--products", help="product ID 列表 JSON，如 [737]"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览 Polaris 工单 payload，不提交"),
) -> None:
    """批量上架商品（设置活跃状态）。支持 --sellsku 快捷模式。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        if sellsku:
            prods, resolved_site_id = _resolve_sellsku_list(manager, sellsku, site_id)
            variant_ids = [p.get("listing_id") or p.get("id") for p in prods]
            product_ids = list({
                p.get("shopify_product_id") or p.get("product_id")
                for p in prods
                if p.get("shopify_product_id") or p.get("product_id")
            })
            result = manager.set_active(
                resolved_site_id, product_ids, variant_ids, dry_run=dry_run
            )
        else:
            if not variants:
                _emit(_error_payload("shopify workorder publish", ValueError("需要 --sellsku 或 --variants 参数")))
                raise typer.Exit(1)
            variant_ids = json.loads(variants)
            product_ids = json.loads(products)
            result = manager.set_active(
                site_id, product_ids, variant_ids, dry_run=dry_run
            )
        _emit({"success": True, "command": "shopify workorder publish", "data": result, "error": None})
    except SystemExit:
        raise
    except Exception as exc:
        _emit(_error_payload("shopify workorder publish", exc))
        sys.exit(1)


@workorder_app.command("unpublish")
def unpublish(
    site_id: int = typer.Option(..., "--site", help="站点 ID"),
    sellsku: str = typer.Option("", "--sellsku", help="卖家 SKU，多个用逗号分隔（与 --variants 二选一）"),
    variants: str = typer.Option("", "--variants", help="variant ID 列表 JSON"),
    products: str = typer.Option("[]", "--products", help="product ID 列表 JSON"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览 Polaris 工单 payload，不提交"),
) -> None:
    """批量下架商品（设置草稿状态）。支持 --sellsku 快捷模式。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        if sellsku:
            prods, resolved_site_id = _resolve_sellsku_list(manager, sellsku, site_id)
            variant_ids = [p.get("listing_id") or p.get("id") for p in prods]
            product_ids = list({
                p.get("shopify_product_id") or p.get("product_id")
                for p in prods
                if p.get("shopify_product_id") or p.get("product_id")
            })
            result = manager.set_draft(
                resolved_site_id, product_ids, variant_ids, dry_run=dry_run
            )
        else:
            if not variants:
                _emit(_error_payload("shopify workorder unpublish", ValueError("需要 --sellsku 或 --variants 参数")))
                raise typer.Exit(1)
            variant_ids = json.loads(variants)
            product_ids = json.loads(products)
            result = manager.set_draft(
                site_id, product_ids, variant_ids, dry_run=dry_run
            )
        _emit({"success": True, "command": "shopify workorder unpublish", "data": result, "error": None})
    except SystemExit:
        raise
    except Exception as exc:
        _emit(_error_payload("shopify workorder unpublish", exc))
        sys.exit(1)


@workorder_app.command("delete")
def delete(
    site_id: int = typer.Option(..., "--site", help="站点 ID"),
    sellsku: str = typer.Option("", "--sellsku", help="卖家 SKU，多个用逗号分隔（与 --variants 二选一）"),
    variants: str = typer.Option("", "--variants", help="variant ID 列表 JSON"),
    products: str = typer.Option("[]", "--products", help="product ID 列表 JSON"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览 Polaris 工单 payload，不提交"),
) -> None:
    """批量删除商品。支持 --sellsku 快捷模式。"""
    _check_auth()
    manager = ShopifyManager()
    try:
        if sellsku:
            prods, resolved_site_id = _resolve_sellsku_list(manager, sellsku, site_id)
            variant_ids = [p.get("listing_id") or p.get("id") for p in prods]
            product_ids = list({
                p.get("shopify_product_id") or p.get("product_id")
                for p in prods
                if p.get("shopify_product_id") or p.get("product_id")
            })
            result = manager.delete_products(
                resolved_site_id, product_ids, variant_ids, dry_run=dry_run
            )
        else:
            if not variants:
                _emit(_error_payload("shopify workorder delete", ValueError("需要 --sellsku 或 --variants 参数")))
                raise typer.Exit(1)
            variant_ids = json.loads(variants)
            product_ids = json.loads(products)
            result = manager.delete_products(
                site_id, product_ids, variant_ids, dry_run=dry_run
            )
        _emit({"success": True, "command": "shopify workorder delete", "data": result, "error": None})
    except SystemExit:
        raise
    except Exception as exc:
        _emit(_error_payload("shopify workorder delete", exc))
        sys.exit(1)
