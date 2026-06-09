---
name: ops-shopify-query
mcp-version: v0.0.2
description: 通过 MCP Tool 查询 Shopify 店铺列表与商品列表（无状态模式，支持 seller_sku 搜索）
---

# ops-shopify-query (MCP 无状态模式)

通过 MCP Tool 查询 Shopify 店铺和商品数据。**服务器不保存任何用户凭证**，所有 session_id / jwt 由调用方管理。

---

## 强制认证门禁

> **【强制】每次调用 shopify_* 工具前，必须先通过 `auth_is_authenticated` 确认 session 有效。**

```python
# 1. 确认认证状态
auth_is_authenticated(session_id="xxx")

# 2. 如无效，重新 Device Flow 授权
auth_login_start()
```

---

## 快速参考

### 查看店铺列表

```python
# 获取所有有权限的 Shopify 店铺
shopify_list_shops(session_id="xxx")
```

### 查看商品列表

```python
# 获取指定店铺的商品列表
shopify_list_products(
    site_id=123,
    page=1,
    limit=20,
    session_id="xxx"
)

# 带关键词搜索
shopify_list_products(
    site_id=123,
    keyword="T-shirt",
    session_id="xxx"
)
```

### 通过 seller_sku 搜索商品

```python
# 通过卖家 SKU 精确搜索（推荐用于自然语言交互）
shopify_search_by_sku(
    sellsku="QD74024-4",
    site_id=1132,
    session_id="xxx"
)
```

---

## 完整 Tool 参考

### `shopify_list_shops`

获取当前用户有权限的 Shopify 店铺列表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 用户授权后的 Session ID |
| `jwt` | string | 否 | 已有 JWT（不传则自动换取） |

---

### `shopify_list_products`

获取指定店铺的商品列表，支持分页和关键词搜索。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `site_id` | integer | **必填** | 站点 ID |
| `page` | integer | 1 | 分页页码 |
| `limit` | integer | 20 | 每页条数 |
| `keyword` | string | None | 关键词搜索 |
| `session_id` | string | **必填** | Session ID |
| `jwt` | string | None | 已有 JWT |

---

### `shopify_search_by_sku`

通过 seller_sku 搜索商品。搜索结果会自动缓存，可直接用于后续 `*_by_sku` 工单操作。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sellsku` | string | 是 | 卖家自定义 SKU（如 QD74024-4） |
| `site_id` | integer | 否 | 站点 ID（不传则搜索所有站点） |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
# 精确搜索指定 SKU
result = shopify_search_by_sku(sellsku="QD74024-4", session_id="xxx")

# 限定站点搜索
result = shopify_search_by_sku(sellsku="QD74024-4", site_id=1132, session_id="xxx")
```

---

## 典型工作流

### 查看→搜索→修改

```python
# 1. 确认认证
auth_is_authenticated(session_id="xxx")

# 2. 查看店铺
shops = shopify_list_shops(session_id="xxx")

# 3. 通过 SKU 搜索商品
products = shopify_search_by_sku(sellsku="QD74024-4", session_id="xxx")

# 4. 直接修改（使用 *_by_sku 工具）
shopify_update_inventory_by_sku(
    sellsku="QD74024-4", quantity=20, session_id="xxx"
)
```

---

## 注意事项

- 所有查询使用 polaris 系统认证，确保 session_id 对应的 polaris 登录有效
- `shopify_search_by_sku` 使用两步验证：先查 Shopify listing 找到产品和渠道 ID，再通过 listing API 验证关联关系
- **如果 seller_sku 没有找到关联关系，直接返回空结果，不生成工单**，需要告知用户该 SKU 无关联
- `shopify_list_products` 使用 Shopify 专用 API，支持关键词模糊搜索
- 修改价格/库存时使用的 listing_id 是变体级别的
