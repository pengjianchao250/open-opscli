---
name: ops-shopify-price
mcp-version: v0.0.2
description: 通过 MCP Tool 批量修改 Shopify 商品价格（无状态模式，支持 seller_sku 快捷操作）
---

# ops-shopify-price (MCP 无状态模式)

通过 MCP Tool 批量修改 Shopify 商品价格，生成北极星工单异步执行。
支持 listing_id 批量模式和 seller_sku 快捷模式。

---

## 强制认证门禁

```python
auth_is_authenticated(session_id="xxx")
```

---

## 完整 Tool 参考

### `shopify_update_prices`（listing_id 模式）

批量修改商品价格，生成工单。**修改前需先调用 `shopify_list_products` 查询商品。**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `site_id` | integer | 是 | 站点 ID |
| `updates` | list[dict] | 是 | 价格修改列表 |
| `reason` | string | 否 | 修改原因（默认 ""） |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

**updates 格式**：

```python
[
    {"listing_id": 1510, "new_price": 29.99, "new_sale_price": 25.0},
    {"listing_id": 1511, "new_price": 39.99}
]
```

### `shopify_update_price_by_sku`（seller_sku 快捷模式 — 推荐）

通过 seller_sku 修改价格，自动搜索商品并提交工单。**无需先查询 listing_id。**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sellsku` | string | 是 | 卖家自定义 SKU（如 QD74024-4） |
| `new_price` | float | 是 | 新原价 |
| `new_sale_price` | float | 否 | 新促销价 |
| `site_id` | integer | 否 | 站点 ID |
| `reason` | string | 否 | 修改原因 |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
# 用户说"帮我把平台sku QD74024-4改价改成29.99"
shopify_update_price_by_sku(
    sellsku="QD74024-4",
    new_price=29.99,
    reason="竞品对标调价",
    session_id="xxx"
)

# 改价 + 促销价
shopify_update_price_by_sku(
    sellsku="QD74024-4",
    new_price=39.99,
    new_sale_price=29.99,
    session_id="xxx"
)
```

**返回示例**：
```json
{
  "success": true,
  "data": {"task_id": "TASK-001", "message": "工单创建成功"},
  "error": null
}
```

---

## 典型工作流

### 方式一：seller_sku 快捷模式（推荐用于自然语言交互）

```python
# 用户说"帮我把平台sku QD74024-4改价改成29.99"
result = shopify_update_price_by_sku(
    sellsku="QD74024-4",
    new_price=29.99,
    reason="竞品对标调价",
    session_id="xxx"
)
task_id = result["data"]["task_id"]

# 查询工单状态
feedtask_status(task_id=task_id, session_id="xxx")
```

### 方式二：listing_id 批量模式

```python
# 1. 查询商品
products = shopify_list_products(site_id=123, session_id="xxx")

# 2. 提交改价
result = shopify_update_prices(
    site_id=123,
    updates=[{"listing_id": 1510, "new_price": 29.99}],
    reason="竞品对标调价",
    session_id="xxx"
)
task_id = result["data"]["task_id"]

# 3. 查询工单状态
feedtask_status(task_id=task_id, session_id="xxx")
```

---

## 注意事项

- `*_by_sku` 模式自动完成搜索→获取 ID→提交工单，适合自然语言交互
- `shopify_update_prices` 模式需要先查询商品获取 listing_id
- 价格修改通过工单异步执行，返回 task_id 用于查询状态
- listing_id 是变体级别，从 shopify_list_products 的 variants 中获取
- **如果 seller_sku 没有找到关联关系，直接返回空结果，不生成工单**，需要告知用户该 SKU 无关联
