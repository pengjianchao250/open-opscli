---
name: ops-shopify-status
description: 批量上架、下架、删除 Shopify 商品，通过北极星刊登系统生成工单执行
version: v0.0.1
---

# ops-shopify-status

批量管理 Shopify 商品状态（上架、下架、删除），通过北极星（Polaris）刊登系统生成工单执行。所有操作通过 `opscli shopify` 子命令完成。

> **说明**：本系统中的"删除"操作实际上是将商品设置为草稿状态（与下架相同），不会真正删除商品数据。

---

## 强制认证门禁

> **【强制】每次调用 `ops-shopify-status` 前，必须先检测 polaris 系统是否已授权登录。**

```bash
opscli auth token status
# polaris Token 异常时：
opscli auth token refresh -s polaris
# 未登录时：
opscli auth login
```

---

## 前置依赖

**操作前必须先通过 `ops-shopify-query` 查询商品数据**：

1. 使用 `opscli shopify shop list` 获取 site_id
2. 使用 `opscli shopify product list --site-id <id>` 获取 product_ids 和 variant_ids
3. 确认要操作的商品 ID 后，执行上架/下架/删除

---

## 何时使用本 Skill

- **批量上架**：将草稿/非活跃商品设为活跃状态（上架到 Shopify）
- **批量下架**：将活跃商品设为草稿状态（从 Shopify 下架）
- **批量删除**：将商品设为草稿状态（与下架相同，非真正删除）

---

## 快速参考

### 上架商品

```bash
# 上架单个商品
opscli shopify workorder publish \
  --site-id 123 \
  --product-ids '[100]' \
  --variant-ids '[1510]'

# 批量上架
opscli shopify workorder publish \
  --site-id 123 \
  --product-ids '[100, 101, 102]' \
  --variant-ids '[1510, 1511, 1512]'
```

### 下架商品

```bash
# 下架单个商品
opscli shopify workorder unpublish \
  --site-id 123 \
  --product-ids '[100]' \
  --variant-ids '[1510]'

# 批量下架
opscli shopify workorder unpublish \
  --site-id 123 \
  --product-ids '[100, 101]' \
  --variant-ids '[1510, 1511]'
```

### 删除商品

```bash
# 删除（设为草稿，等同于下架）
opscli shopify workorder delete \
  --site-id 123 \
  --product-ids '[100]' \
  --variant-ids '[1510]'
```

---

## 完整命令参考

### `opscli shopify workorder publish`

批量上架商品（设置活跃状态）。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--site-id` | 是 | 站点 ID |
| `--product-ids` | 是 | 商品 ID 列表（JSON 数组） |
| `--variant-ids` | 是 | 变体 ID 列表（JSON 数组） |

```bash
opscli shopify workorder publish \
  --site-id 123 \
  --product-ids '[100, 101]' \
  --variant-ids '[1510, 1511]'
```

---

### `opscli shopify workorder unpublish`

批量下架商品（设置草稿状态）。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--site-id` | 是 | 站点 ID |
| `--product-ids` | 是 | 商品 ID 列表（JSON 数组） |
| `--variant-ids` | 是 | 变体 ID 列表（JSON 数组） |

```bash
opscli shopify workorder unpublish \
  --site-id 123 \
  --product-ids '[100]' \
  --variant-ids '[1510]'
```

---

### `opscli shopify workorder delete`

批量删除商品（设置为草稿状态，与下架相同）。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--site-id` | 是 | 站点 ID |
| `--product-ids` | 是 | 商品 ID 列表（JSON 数组） |
| `--variant-ids` | 是 | 变体 ID 列表（JSON 数组） |

```bash
opscli shopify workorder delete \
  --site-id 123 \
  --product-ids '[100]' \
  --variant-ids '[1510]'
```

---

## 典型工作流

### 工作流 1：新品上架

```bash
# 1. 确认认证
opscli auth token status

# 2. 查询商品信息（ops-shopify-query）
opscli shopify product list --site-id 123 --keyword "new-product"

# 3. 上架商品
opscli shopify workorder publish \
  --site-id 123 \
  --product-ids '[100, 101]' \
  --variant-ids '[1510, 1511]'

# 4. 查询工单状态（ops-feed-task）
opscli feedtask status --task-id TASK-20250427-003
```

### 工作流 2：季节性下架

```bash
# 1. 查询需要下架的商品
opscli shopify product list --site-id 123 --keyword "winter"

# 2. 批量下架
opscli shopify workorder unpublish \
  --site-id 123 \
  --product-ids '[200, 201, 202]' \
  --variant-ids '[1600, 1601, 1602]'
```

---

## 注意事项

- 所有操作通过北极星工单系统异步执行，提交后返回 task_id
- **删除 = 下架**：本系统中删除操作实际上是将商品设为草稿状态，不会物理删除
- product_ids 和 variant_ids 是商品/变体的 ID（不同于 listing_id）
- 上架/下架需要同时传入 product_ids 和 variant_ids
