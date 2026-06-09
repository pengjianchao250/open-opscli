---
name: ops-shopify-status
mcp-version: v0.0.2
description: 通过 MCP Tool 批量上架、下架 Shopify 商品（无状态模式，支持 seller_sku 快捷操作）
---

# ops-shopify-status (MCP 无状态模式)

通过 MCP Tool 批量管理 Shopify 商品状态（上架、下架）。
支持 listing_id 批量模式和 seller_sku 快捷模式。

> **说明**：删除操作已迁移到独立的 `ops-shopify-delete` Skill，本 Skill 仅负责上架和下架。

---

## 强制认证门禁

```python
auth_is_authenticated(session_id="xxx")
```

---

## 完整 Tool 参考

### listing_id 模式

> 操作前需先调用 `shopify_list_products` 查询商品数据，获取 product_ids 和 variant_ids。

#### `shopify_publish`

批量上架商品（设置活跃状态）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `site_id` | integer | 是 | 站点 ID |
| `variant_ids` | list[int] | 是 | 变体 ID 列表 |
| `product_ids` | list[int] | 是 | 商品 ID 列表 |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

#### `shopify_unpublish`

批量下架商品（设置草稿状态）。参数同 publish。

### seller_sku 快捷模式（推荐用于自然语言交互）

> 无需先查询 listing_id，自动搜索商品并提交工单。

#### `shopify_publish_by_sku`

通过 seller_sku 上架商品。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sellsku` | string | 是 | 卖家自定义 SKU |
| `site_id` | integer | 否 | 站点 ID |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
# 用户说"帮我把平台sku QD74024-4上架"
shopify_publish_by_sku(sellsku="QD74024-4", session_id="xxx")
```

#### `shopify_unpublish_by_sku`

通过 seller_sku 下架商品。参数同 publish_by_sku。

```python
# 用户说"帮我把平台sku QD74024-4下架"
shopify_unpublish_by_sku(sellsku="QD74024-4", session_id="xxx")
```

---

## 典型工作流

### 方式一：seller_sku 快捷模式

```python
# 用户说"帮我把QD74024-4上架"
result = shopify_publish_by_sku(sellsku="QD74024-4", session_id="xxx")
feedtask_status(task_id=result["data"]["task_id"], session_id="xxx")
```

### 方式二：listing_id 批量模式

```python
# 1. 查询商品
products = shopify_list_products(site_id=123, session_id="xxx")

# 2. 上架商品
result = shopify_publish(
    site_id=123,
    product_ids=[100, 101],
    variant_ids=[1510, 1511],
    session_id="xxx"
)

# 3. 查询工单状态
feedtask_status(task_id=result["data"]["task_id"], session_id="xxx")
```

---

## 注意事项

- 删除操作已迁移到独立的 `ops-shopify-delete` Skill
- `*_by_sku` 模式自动完成搜索→获取 ID→提交工单，适合自然语言交互
- listing_id 模式的 product_ids 和 variant_ids 需从商品查询结果获取
- 所有操作通过工单异步执行，返回 task_id 用于查询状态
- **如果 seller_sku 没有找到关联关系，直接返回空结果，不生成工单**，需要告知用户该 SKU 无关联
