---
name: ops-shopify-inventory
mcp-version: v0.0.2
description: 通过 MCP Tool 批量修改 Shopify 商品库存（无状态模式，支持 seller_sku 快捷操作）
---

# ops-shopify-inventory (MCP 无状态模式)

通过 MCP Tool 批量修改 Shopify 商品库存，生成北极星工单异步执行。
支持 listing_id 批量模式和 seller_sku 快捷模式。

---

## 强制认证门禁

```python
auth_is_authenticated(session_id="xxx")
```

---

## 完整 Tool 参考

### `shopify_update_inventory`（listing_id 模式）

批量修改商品库存，生成工单。**修改前需先调用 `shopify_list_products` 查询商品。**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `site_id` | integer | 是 | 站点 ID |
| `updates` | list[dict] | 是 | 库存修改列表 |
| `reason` | string | 否 | 修改原因（默认 ""） |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

**updates 格式**：

```python
[
    {"listing_id": 1509, "new_inventory_quantity": 100},
    {"listing_id": 1510, "new_inventory_quantity": 200}
]
```

### `shopify_update_inventory_by_sku`（seller_sku 快捷模式 — 推荐）

通过 seller_sku 修改库存，自动搜索商品并提交工单。**无需先查询 listing_id。**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sellsku` | string | 是 | 卖家自定义 SKU（如 QD74024-4） |
| `quantity` | integer | 是 | 新库存数量（绝对值） |
| `site_id` | integer | 否 | 站点 ID（不传则搜索所有站点） |
| `reason` | string | 否 | 修改原因 |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
# 用户说"帮我把平台sku QD74024-4改库存改成20"
shopify_update_inventory_by_sku(
    sellsku="QD74024-4",
    quantity=20,
    reason="仓库补货",
    session_id="xxx"
)
```

**返回示例**：
```json
{
  "success": true,
  "data": {"task_id": "TASK-002", "message": "工单创建成功"},
  "error": null
}
```

---

## 典型工作流

### 方式一：seller_sku 快捷模式（推荐用于自然语言交互）

```python
# 用户说"帮我把平台sku QD74024-4改库存改成20"
# 直接调用，无需先查询
result = shopify_update_inventory_by_sku(
    sellsku="QD74024-4",
    quantity=20,
    reason="仓库补货",
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

# 2. 提交库存修改
result = shopify_update_inventory(
    site_id=123,
    updates=[{"listing_id": 1509, "new_inventory_quantity": 100}],
    reason="仓库补货",
    session_id="xxx"
)
task_id = result["data"]["task_id"]

# 3. 查询工单状态
feedtask_status(task_id=task_id, session_id="xxx")
```

---

## 注意事项

- `*_by_sku` 模式自动完成搜索→获取 ID→提交工单，适合自然语言交互
- `shopify_update_inventory` 模式需要先查询商品获取 listing_id
- new_inventory_quantity 为绝对值（不是增量），设为 0 即库存清零
- 库存修改通过工单异步执行，返回 task_id 用于查询状态
- **如果 seller_sku 没有找到关联关系，直接返回空结果，不生成工单**，需要告知用户该 SKU 无关联
