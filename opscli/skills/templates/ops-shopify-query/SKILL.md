---
name: ops-shopify-query
description: 查询 Shopify 店铺列表与商品列表，为后续价格/库存/上下架操作提供数据基础
version: v0.0.1
---

# ops-shopify-query

查询 Shopify 店铺列表与商品列表，所有操作通过 `opscli shopify` 子命令执行。

> 本 Skill 是所有 `ops-shopify-*` Skill 的前置依赖，提供店铺和商品数据查询能力。

---

## 强制认证门禁

> **【强制】每次调用 `ops-shopify-query` 前，必须先检测 polaris 系统是否已授权登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若 polaris 系统 Token 异常，执行 `opscli auth token refresh -s polaris`
- 刷新失败或未登录，执行 `opscli auth login`
- 只有认证状态确认正常后，才允许继续查询

**标准前置流程：**

```bash
# 1. 检查登录状态
opscli auth token status

# 2. 如 polaris Token 过期，刷新
opscli auth token refresh -s polaris

# 3. 如未登录，先登录
opscli auth login
```

---

## 何时使用本 Skill

- **查看店铺**：获取当前用户有权限的 Shopify 店铺列表
- **浏览商品**：查看指定店铺的商品列表，支持分页和关键词搜索
- **获取商品 ID**：为后续价格修改、库存修改、上架/下架操作提供必要的 site_id、listing_id、variant_id

---

## 快速参考

### 查看店铺列表

```bash
# 列出所有有权限的 Shopify 店铺
opscli shopify shop list
```

**输出字段**：

| 字段 | 说明 |
|------|------|
| `site_id` | 站点 ID（后续操作的关键参数） |
| `channel_name` | 店铺名称 |
| `platform` | 平台标识（1 = Shopify） |
| `status` | 店铺状态 |
| `currency` | 货币单位 |

### 查看商品列表

```bash
# 查看指定店铺的商品（分页）
opscli shopify product list --site-id 123

# 指定页码和每页条数
opscli shopify product list --site-id 123 --page 1 --limit 50

# 关键词搜索
opscli shopify product list --site-id 123 --keyword "T-shirt"
```

**输出字段**：

| 字段 | 说明 |
|------|------|
| `listing_id` | 商品/变体 ID（修改价格/库存的关键参数） |
| `name` | 商品名称 |
| `sku` | SKU |
| `price` | 原价 |
| `sale_price` | 促销价 |
| `inventory_quantity` | 库存数量 |
| `channel_name` | 所属店铺 |

---

## 完整命令参考

### `opscli shopify shop list`

列出当前用户有权限的所有 Shopify 店铺。

```bash
opscli shopify shop list
```

**输出示例（JSON）**：
```json
[
  {
    "site_id": 123,
    "channel_name": "My Store US",
    "platform": 1,
    "status": 1,
    "currency": "USD"
  },
  {
    "site_id": 456,
    "channel_name": "My Store UK",
    "platform": 1,
    "status": 1,
    "currency": "GBP"
  }
]
```

---

### `opscli shopify product list`

查看指定店铺的商品列表，支持分页和关键词搜索。

**参数**：

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--site-id` | 是 | — | 站点 ID（从 shop list 获取） |
| `--page` | 否 | 1 | 分页页码 |
| `--limit` | 否 | 20 | 每页条数（最大 100） |
| `--keyword` | 否 | — | 关键词搜索 |

```bash
# 基础查询
opscli shopify product list --site-id 123

# 分页查询
opscli shopify product list --site-id 123 --page 2 --limit 50

# 搜索商品
opscli shopify product list --site-id 123 --keyword "shirt"
```

**输出示例（JSON）**：
```json
{
  "data": [
    {
      "listing_id": 1510,
      "name": "Classic T-Shirt",
      "sku": "TSHIRT-001",
      "channel_name": "My Store US",
      "variants": [
        {
          "listing_id": 1511,
          "sku": "TSHIRT-001-RED-S",
          "seller_sku": "SKU-RED-S",
          "price": 29.99,
          "sale_price": 25.0,
          "inventory_quantity": 100
        }
      ]
    }
  ],
  "total": 150,
  "page": 1,
  "limit": 20
}
```

---

## 典型工作流

### 工作流 1：查看所有店铺并浏览商品

```bash
# 1. 确认认证状态
opscli auth token status

# 2. 查看所有店铺
opscli shopify shop list

# 3. 选择一个店铺，查看商品
opscli shopify product list --site-id 123

# 4. 翻页浏览
opscli shopify product list --site-id 123 --page 2 --limit 50
```

### 工作流 2：搜索特定商品

```bash
# 1. 确认认证状态
opscli auth token status

# 2. 查看店铺列表
opscli shopify shop list

# 3. 在指定店铺搜索商品
opscli shopify product list --site-id 123 --keyword "T-shirt"
```

### 工作流 3：为后续操作收集参数

```bash
# 1. 查看店铺 → 获取 site_id
opscli shopify shop list

# 2. 查看商品 → 获取 listing_id
opscli shopify product list --site-id 123

# 3. 使用收集到的参数执行后续操作（交给其他 Skill）
# - ops-shopify-price: 修改价格
# - ops-shopify-inventory: 修改库存
# - ops-shopify-status: 上架/下架/删除
```

---

## 注意事项

- 所有查询使用 polaris 系统认证，确保 `opscli auth token status` 中 polaris 状态正常
- 商品列表默认返回父商品维度（`view_type=parent`），变体信息嵌套在 variants 数组中
- 修改价格/库存时使用的 `listing_id` 是变体级别的 listing_id，不是父商品的
- 建议先调用 `shop list` 确认 site_id，再调用 `product list` 查看商品
