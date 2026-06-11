---
name: ops-shopify-delete
mcp-version: v0.0.2
description: 通过 MCP Tool 删除 Shopify 商品（无状态模式，支持 seller_sku 快捷操作）
---

# ops-shopify-delete (MCP 无状态模式)

通过 MCP Tool 删除 Shopify 商品。
支持 listing_id 批量模式和 seller_sku 快捷模式。

---

## 强制认证门禁

```python
auth_is_authenticated(session_id="xxx")
```

---

## 完整 Tool 参考

### listing_id 模式

> 操作前需先调用 `shopify_list_products` 查询商品，获取 product_ids 和 variant_ids。

#### `shopify_delete_products`

批量删除商品。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `site_id` | integer | 是 | 站点 ID |
| `variant_ids` | list[int] | 是 | 变体 ID 列表 |
| `product_ids` | list[int] | 是 | 商品 ID 列表 |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

### seller_sku 快捷模式（推荐用于自然语言交互）

> 无需先查询 listing_id，自动搜索商品并提交工单。

#### `shopify_delete_by_sku`

通过 seller_sku 删除商品。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sellsku` | string | 是 | 卖家自定义 SKU |
| `site_id` | integer | 否 | 站点 ID |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
# 用户说"帮我把平台sku QD74024-4删除"
shopify_delete_by_sku(sellsku="QD74024-4", site_id=1132, session_id="xxx")
```

---

## 典型工作流

### 方式一：seller_sku 快捷模式

```python
# 用户说"帮我把QD74024-4删除"
result = shopify_delete_by_sku(sellsku="QD74024-4", site_id=1132, session_id="xxx")
feedtask_status(task_id=result["data"]["data"]["feed_task_code"], session_id="xxx")
```

### 方式二：listing_id 批量模式

```python
# 1. 查询商品
products = shopify_list_products(site_id=8717, session_id="xxx")

# 2. 删除商品
result = shopify_delete_products(
    site_id=1132,
    product_ids=[91],
    variant_ids=[138],
    session_id="xxx"
)

# 3. 查询工单状态
feedtask_status(task_id=result["data"]["data"]["feed_task_code"], session_id="xxx")
```

---

## 注意事项

- 删除操作通过独立工单执行（operateMethod: shopifyDelete），与下架（setDraft）不同
- `*_by_sku` 模式自动完成搜索→获取 ID→提交工单，适合自然语言交互
- 所有操作通过工单异步执行，返回 task_id 用于查询状态
- **如果 seller_sku 没有找到关联关系，直接返回空结果，不生成工单**，需要告知用户该 SKU 无关联
