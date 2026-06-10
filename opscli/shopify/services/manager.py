"""Shopify 刊登业务编排层。

核心职责：
1. 查询：获取店铺/商品数据，转为领域模型
2. 构造工单 payload：根据操作类型自动填充商品信息
3. 委托 feedtask 提交工单
"""

from __future__ import annotations

from opscli.auth import AuthClient
from opscli.feedtask.transport.client import FeedTaskClient
from opscli.shopify.domain.exceptions import ShopifyNotFoundError, ShopifyParamsError
from opscli.shopify.domain.models import Shop, ShopifyProduct, ShopifyVariant
from opscli.shopify.services.payload_builder import ShopifyTaskPayloadBuilder
from opscli.shopify.services.template_registry import OPERATION_REGISTRY
from opscli.shopify.transport.client import ShopifyClient


class ShopifyManager:
    """Shopify 刊登业务编排层。"""

    # 保留旧属性，兼容外部可能直接读取 ShopifyManager.OPERATION_MAP 的代码。
    OPERATION_MAP: dict[str, dict] = {
        name: config.to_legacy_dict()
        for name, config in OPERATION_REGISTRY.items()
    }

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.shopify_client = ShopifyClient(
            auth_client=auth_client, jwt=jwt, session_id=session_id
        )
        # 工单提交复用 feedtask 的 transport 层
        self.feedtask_client = FeedTaskClient(
            auth_client=auth_client, jwt=jwt, session_id=session_id
        )
        self.payload_builder = ShopifyTaskPayloadBuilder()
        # 内存缓存：查询结果暂存，供工单构造时引用
        self._product_cache: dict[int, dict] = {}

    # ── 查询 ──────────────────────────────────────────────────

    def list_shops(self, platform: int | None = None) -> list[Shop]:
        """获取当前用户有权限的店铺列表。

        getSourceChannels API 只返回 channel_id（value）和店铺名（label），
        不返回内部 site_id。需要额外查一个产品来获取 site_id 映射。

        Args:
            platform: 平台标识，不传则从配置文件读取
        """
        raw_list = self.shopify_client.list_shops(platform=platform)

        # 预查询每个渠道的一个产品，获取 site_id（belong_site_id）映射
        site_id_map: dict[int, int] = {}
        for item in raw_list:
            channel_id = item.get("value") or item.get("channel_id", 0)
            if not channel_id:
                continue
            try:
                resp = self.shopify_client.list_products(
                    site_id=channel_id, limit=1, view_type="child"
                )
                products = []
                data = resp.get("data")
                if isinstance(data, dict):
                    products = data.get("data") or data.get("list") or data.get("items") or []
                elif isinstance(data, list):
                    products = data
                if products:
                    # 产品数据中的 site_id 才是内部站点 ID
                    site_id_map[channel_id] = products[0].get("site_id", 0)
            except Exception:
                pass

        return [self._parse_shop(item, site_id_map) for item in raw_list]

    def list_products(
        self,
        site_id: int | None = None,
        *,
        page: int = 1,
        limit: int = 20,
        keyword: str | None = None,
    ) -> dict:
        """获取商品列表，并缓存到内存供后续工单构造使用。

        Args:
            site_id: 站点 ID，不传则查询所有
            page: 分页页码
            limit: 每页条数
            keyword: 关键词搜索

        Returns:
            原始响应（含分页信息）
        """
        response = self.shopify_client.list_products(
            site_id, page=page, limit=limit, keyword=keyword
        )
        # 缓存商品数据（items 可能在 data.data、data.list 或 data 中，取决于后端返回结构）
        items = []
        data = response.get("data")
        if isinstance(data, dict):
            items = data.get("data") or data.get("list") or data.get("items") or []
        elif isinstance(data, list):
            items = data

        for item in items:
            listing_id = item.get("listing_id") or item.get("id")
            if listing_id is not None:
                self._product_cache[int(listing_id)] = item

        return response

    # ── seller_sku 快捷操作（搜索 + 工单一步完成）──────────

    def search_by_seller_sku(
        self,
        sellsku: str,
        site_id: int | None = None,
    ) -> list[dict]:
        """通过 seller_sku 搜索商品（两步验证）。

        两步流程：
        1. 通过 Shopify listing API 查找 seller_sku 对应的产品，获取 channel_id
        2. 通过 listing API (/api/listing/list) 验证 seller_sku 存在关联关系，获取 site_id

        Args:
            sellsku:  卖家自定义 SKU（如 QD74024-4）
            site_id:  站点 ID（可选，用于过滤站点）

        Returns:
            匹配的 Shopify 商品列表（含 Shopify 专有字段 + site_id）
        """
        # ── 第一步：通过 Shopify listing API 查找产品和渠道 ID ──
        # 不传 site_id（Shopify API 的 site_id 实际是 channel_id），
        # 搜索所有渠道找到 seller_sku 对应的产品
        shopify_response = self.shopify_client.list_products(
            site_id=None, limit=100, abnormal_state=1, view_type="child"
        )
        shopify_items = []
        shopify_data = shopify_response.get("data")
        if isinstance(shopify_data, dict):
            shopify_items = shopify_data.get("data") or shopify_data.get("list") or shopify_data.get("items") or []
        elif isinstance(shopify_data, list):
            shopify_items = shopify_data

        if not shopify_items:
            return []

        # 按 seller_sku 精确匹配，获取产品数据和 channel_id
        matched_shopify = []
        for item in shopify_items:
            item_sku = item.get("seller_sku") or item.get("sell_sku", "")
            if item_sku == sellsku:
                matched_shopify.append(item)

        if not matched_shopify:
            return []

        # 从 Shopify 数据获取 channel_id（用于第二步 listing API 查询）
        first_shopify = matched_shopify[0]
        channel_id = first_shopify.get("channel_id")
        if not channel_id:
            return []

        # ── 第二步：通过 listing API 验证关联关系，获取 site_id ──
        assoc_response = self.shopify_client.search_listings(
            sellsku=sellsku, channel_id=int(channel_id)
        )
        assoc_items = []
        assoc_data = assoc_response.get("data")
        if isinstance(assoc_data, dict):
            assoc_items = assoc_data.get("list") or assoc_data.get("items") or assoc_data.get("data") or []
        elif isinstance(assoc_data, list):
            assoc_items = assoc_data

        if not assoc_items:
            return []

        # 关联验证通过，从 listing 数据获取内部 site_id（belong_site_id）
        # 注意：listing API 返回 belong_site_id 才是工单所需的内部站点 ID
        # channel_id（如 8717）不能用于工单提交，需要 belong_site_id（如 1132）
        first_assoc = assoc_items[0]
        resolved_site_id = first_assoc.get("belong_site_id") or first_assoc.get("site_id")

        # 缓存 Shopify 变体级别的数据（供 _build_batch_listings 使用）
        for item in matched_shopify:
            item["site_id"] = resolved_site_id
            # 后端期望 listing_id 字段，Shopify API 返回的是 id，需要映射
            if "listing_id" not in item:
                item["listing_id"] = item.get("id")
            lid = item.get("listing_id") or item.get("id")
            if lid is not None:
                self._product_cache[int(lid)] = item

        return matched_shopify

    def _resolve_product_by_sku(
        self,
        sellsku: str,
        site_id: int | None = None,
    ) -> tuple[dict, int]:
        """通过 seller_sku 解析商品，返回 (商品数据, site_id)。

        Args:
            sellsku:  卖家自定义 SKU
            site_id:  站点 ID（可选）

        Returns:
            (商品数据 dict, site_id int)

        Raises:
            ShopifyNotFoundError: 未找到匹配商品或无关联关系
            ShopifyParamsError:   商品缺少必要信息
        """
        items = self.search_by_seller_sku(sellsku, site_id=site_id)
        if not items:
            raise ShopifyNotFoundError(
                f"seller_sku {sellsku} 未找到产品与 listing 的关联关系，无法发起工单"
            )

        first = items[0]
        # 始终优先使用 listing 关联解析出的 site_id（内部站点 ID）
        # 用户传入的 site_id 可能是 channel_id（如 8717），不能用于工单提交
        resolved_site_id = first.get("site_id") or site_id

        if not resolved_site_id:
            raise ShopifyParamsError(f"商品 {sellsku} 缺少 site_id 信息")

        return first, int(resolved_site_id)

    def update_inventory_by_sku(
        self,
        sellsku: str,
        quantity: int,
        site_id: int | None = None,
        reason: str = "",
        dry_run: bool = False,
    ) -> dict:
        """通过 seller_sku 修改库存。

        自动搜索商品获取 listing_id，然后提交工单。
        适合 AI Agent 一步到位的场景。

        Args:
            sellsku:  卖家自定义 SKU
            quantity: 新库存数量（绝对值）
            site_id:  站点 ID（可选，不传则从 listing 数据获取）
            reason:   操作原因

        Returns:
            工单创建结果

        Raises:
            ShopifyNotFoundError: 未找到匹配商品
            ShopifyParamsError:   商品缺少 site_id 信息
        """
        product, resolved_site_id = self._resolve_product_by_sku(sellsku, site_id=site_id)
        listing_id = product.get("listing_id") or product.get("id")

        updates = [{"listing_id": listing_id, "new_inventory_quantity": quantity}]
        return self.update_inventory(
            resolved_site_id, updates, reason=reason, dry_run=dry_run
        )

    def update_price_by_sku(
        self,
        sellsku: str,
        new_price: float | None = None,
        new_sale_price: float | None = None,
        site_id: int | None = None,
        reason: str = "",
        dry_run: bool = False,
    ) -> dict:
        """通过 seller_sku 修改价格。

        自动搜索商品获取 listing_id，然后提交工单。
        至少需要传 new_price 或 new_sale_price 之一。

        Args:
            sellsku:        卖家自定义 SKU
            new_price:      新原价（可选）
            new_sale_price: 新销售价（可选）
            site_id:        站点 ID（可选）
            reason:         操作原因

        Returns:
            工单创建结果

        Raises:
            ShopifyNotFoundError: 未找到匹配商品
            ShopifyParamsError:   商品缺少 site_id 信息
            ValueError:          new_price 和 new_sale_price 都未传
        """
        if new_price is None and new_sale_price is None:
            raise ValueError("至少需要传 new_price 或 new_sale_price 之一")

        product, resolved_site_id = self._resolve_product_by_sku(sellsku, site_id=site_id)
        listing_id = product.get("listing_id") or product.get("id")

        update_item: dict = {"listing_id": listing_id}
        if new_price is not None:
            update_item["new_price"] = new_price
        if new_sale_price is not None:
            update_item["new_sale_price"] = new_sale_price

        return self.update_prices(
            resolved_site_id, [update_item], reason=reason, dry_run=dry_run
        )

    def publish_by_sku(
        self,
        sellsku: str,
        site_id: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """通过 seller_sku 上架商品。

        Args:
            sellsku:  卖家自定义 SKU
            site_id:  站点 ID（可选）

        Returns:
            工单创建结果
        """
        product, resolved_site_id = self._resolve_product_by_sku(sellsku, site_id=site_id)
        listing_id = product.get("listing_id") or product.get("id")
        product_id = product.get("shopify_product_id") or product.get("product_id")

        return self.set_active(
            resolved_site_id,
            [product_id] if product_id else [],
            [listing_id],
            dry_run=dry_run,
        )

    def unpublish_by_sku(
        self,
        sellsku: str,
        site_id: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """通过 seller_sku 下架商品。

        Args:
            sellsku:  卖家自定义 SKU
            site_id:  站点 ID（可选）

        Returns:
            工单创建结果
        """
        product, resolved_site_id = self._resolve_product_by_sku(sellsku, site_id=site_id)
        listing_id = product.get("listing_id") or product.get("id")
        product_id = product.get("shopify_product_id") or product.get("product_id")

        return self.set_draft(
            resolved_site_id,
            [product_id] if product_id else [],
            [listing_id],
            dry_run=dry_run,
        )

    def delete_by_sku(
        self,
        sellsku: str,
        site_id: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """通过 seller_sku 删除商品。

        Args:
            sellsku:  卖家自定义 SKU
            site_id:  站点 ID（可选）

        Returns:
            工单创建结果
        """
        product, resolved_site_id = self._resolve_product_by_sku(sellsku, site_id=site_id)
        listing_id = product.get("listing_id") or product.get("id")
        product_id = product.get("shopify_product_id") or product.get("product_id")

        return self.delete_products(
            resolved_site_id,
            [product_id] if product_id else [],
            [listing_id],
            dry_run=dry_run,
        )

    # ── 工单操作（构造 payload + 委托 feedtask 提交）──────────

    def update_prices(
        self,
        site_id: int,
        updates: list[dict],
        reason: str = "",
        dry_run: bool = False,
    ) -> dict:
        """批量修改价格。

        Args:
            site_id: 站点 ID
            updates: 列表，每项包含 listing_id + new_price（可选 new_sale_price）
                     例: [{"listing_id": 1510, "new_price": 29.99, "new_sale_price": 25.0}]
            reason:  操作原因
        """
        batch_listings, variant_ids, product_id = self._build_batch_listings(
            updates,
            extra_fields_fn=lambda item, raw: {
                "new_price": item.get("new_price", raw.get("price")),
                "new_sale_price": item.get("new_sale_price", raw.get("sale_price")),
            },
        )
        payload = self._build_task_payload(
            operation="price_update",
            site_id=site_id,
            data_content={"batch_listings": batch_listings, "reson": reason, "site_id": site_id},
            variant_ids=variant_ids,
            product_id=product_id,
        )
        return self._preview_or_submit(
            operation="price_update",
            site_id=site_id,
            payload=payload,
            dry_run=dry_run,
        )

    def update_inventory(
        self,
        site_id: int,
        updates: list[dict],
        reason: str = "",
        dry_run: bool = False,
    ) -> dict:
        """批量修改库存。

        Args:
            site_id: 站点 ID
            updates: 列表，每项包含 listing_id + new_inventory_quantity
                     例: [{"listing_id": 1509, "new_inventory_quantity": 100}]
            reason:  操作原因
        """
        batch_listings, variant_ids, product_id = self._build_batch_listings(
            updates,
            extra_fields_fn=lambda item, raw: {
                "new_inventory_quantity": item["new_inventory_quantity"],
                "select_overseas_inventory": item.get(
                    "select_overseas_inventory", [raw.get("sku", "")]
                ),
            },
        )
        payload = self._build_task_payload(
            operation="inventory_set",
            site_id=site_id,
            data_content={"batch_listings": batch_listings, "reson": reason, "site_id": site_id},
            variant_ids=variant_ids,
            product_id=product_id,
        )
        return self._preview_or_submit(
            operation="inventory_set",
            site_id=site_id,
            payload=payload,
            dry_run=dry_run,
        )

    def set_active(
        self,
        site_id: int,
        product_ids: list[int],
        variant_ids: list[int],
        dry_run: bool = False,
    ) -> dict:
        """批量上架（设置活跃）。"""
        payload = self._build_task_payload(
            operation="set_active",
            site_id=site_id,
            data_content={"total": len(variant_ids), "site_id": site_id},
            variant_ids=variant_ids,
            product_id=product_ids[0] if product_ids else None,
        )
        return self._preview_or_submit(
            operation="set_active",
            site_id=site_id,
            payload=payload,
            dry_run=dry_run,
        )

    def set_draft(
        self,
        site_id: int,
        product_ids: list[int],
        variant_ids: list[int],
        dry_run: bool = False,
    ) -> dict:
        """批量下架（设置草稿）。"""
        payload = self._build_task_payload(
            operation="set_draft",
            site_id=site_id,
            data_content={"total": len(variant_ids), "site_id": site_id},
            variant_ids=variant_ids,
            product_id=product_ids[0] if product_ids else None,
        )
        return self._preview_or_submit(
            operation="set_draft",
            site_id=site_id,
            payload=payload,
            dry_run=dry_run,
        )

    def delete_products(
        self,
        site_id: int,
        product_ids: list[int],
        variant_ids: list[int],
        dry_run: bool = False,
    ) -> dict:
        """批量删除商品。"""
        payload = self._build_task_payload(
            operation="delete",
            site_id=site_id,
            data_content={"total": len(variant_ids), "site_id": site_id},
            variant_ids=variant_ids,
            product_id=product_ids[0] if product_ids else None,
        )
        return self._preview_or_submit(
            operation="delete",
            site_id=site_id,
            payload=payload,
            dry_run=dry_run,
        )

    # ── 内部方法 ──────────────────────────────────────────────

    def _build_batch_listings(
        self,
        updates: list[dict],
        *,
        extra_fields_fn,
    ) -> tuple[list[dict], list[int], int | None]:
        """从缓存获取商品原始数据，合并额外字段。

        Args:
            updates: 操作条目列表
            extra_fields_fn: 回调函数，接收 (item, raw_product) 返回额外字段

        Returns:
            (batch_listings, variant_ids, product_id)
        """
        batch_listings: list[dict] = []
        variant_ids: list[int] = []
        product_id: int | None = None

        if not updates:
            raise ShopifyParamsError("updates 不能为空")

        for item in updates:
            raw_listing_id = item.get("listing_id")
            if not raw_listing_id:
                raise ShopifyParamsError("updates 每项都必须包含 listing_id")
            try:
                listing_id = int(raw_listing_id)
            except (TypeError, ValueError) as exc:
                raise ShopifyParamsError(f"listing_id 非法: {raw_listing_id}") from exc

            raw = self._product_cache.get(listing_id)
            if not raw:
                raise ShopifyNotFoundError(
                    f"商品 {listing_id} 未查询过，请先调用 list_products"
                )
            # 复制原始数据，合并 AI 填入的变化字段
            listing_data = dict(raw)
            listing_data.update(extra_fields_fn(item, raw))
            batch_listings.append(listing_data)
            variant_ids.append(listing_id)
            if product_id is None:
                product_id = raw.get("shopify_product_id") or raw.get("internal_product_id") or raw.get("product_id")

        return batch_listings, variant_ids, product_id

    def _build_task_payload(
        self,
        operation: str,
        site_id: int,
        data_content: dict,
        variant_ids: list[int],
        product_id: int | str | None,
    ) -> dict:
        """构造完整的 createCustomTask 请求体。"""
        return self.payload_builder.build(
            operation=operation,
            site_id=site_id,
            data_content=data_content,
            variant_ids=variant_ids,
            product_id=product_id,
        )

    def _preview_or_submit(
        self,
        *,
        operation: str,
        site_id: int,
        payload: dict,
        dry_run: bool,
    ) -> dict:
        if dry_run:
            return self.payload_builder.preview(
                operation=operation,
                site_id=site_id,
                payload=payload,
            )
        return self.feedtask_client.create(payload)

    @staticmethod
    def _parse_shop(raw: dict, site_id_map: dict | None = None) -> Shop:
        """解析店铺数据。

        适配两种 API 返回格式：
        1. getSourceChannels 返回 {"value": channel_id, "label": "店铺名", "belong_site_id": 站点ID}
        2. 其他接口可能返回完整字段

        注意字段区分：
        - channel_id（value）：渠道 ID，如 8717，用于 Shopify listing API 查询
        - belong_site_id：内部站点 ID，如 1132，用于工单提交
        """
        channel_id = raw.get("channel_id") or raw.get("value", 0)
        # site_id 优先从 site_id_map（产品数据解析）获取
        resolved_site_id = 0
        if site_id_map and channel_id in site_id_map:
            resolved_site_id = site_id_map[channel_id]
        elif raw.get("belong_site_id"):
            resolved_site_id = raw["belong_site_id"]
        elif raw.get("site_id"):
            resolved_site_id = raw["site_id"]

        return Shop(
            channel_id=channel_id,
            channel_name=raw.get("channel_name") or raw.get("label", ""),
            platform=raw.get("platform", "shopify"),
            site_id=resolved_site_id,
            status=raw.get("status", ""),
            currency=raw.get("currency", "USD"),
            url=raw.get("url"),
        )

    @staticmethod
    def _parse_product(raw: dict) -> ShopifyProduct:
        """解析商品数据。"""
        return ShopifyProduct(
            listing_id=raw.get("listing_id") or raw.get("id", 0),
            channel_id=raw.get("channel_id", 0),
            channel_name=raw.get("channel_name", ""),
            name=raw.get("name", ""),
            sku=raw.get("sku"),
        )
