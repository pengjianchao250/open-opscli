---
name: ops-shopify-inventory
description: 批量修改 Shopify 商品库存，通过北极星刊登系统生成工单执行
version: v0.0.1
---

# ops-shopify-inventory

批量修改 Shopify 商品库存，通过北极星（Polaris）刊登系统生成工单执行。所有操作通过 `opscli shopify` 子命令完成。

---

## 强制认证门禁

> **【强制】每次调用 `ops-shopify-inventory` 前，必须先检测 polaris 系统是否已授权登录。**

```bash
opscli auth token status
# polaris Token 异常时：
opscli auth token refresh -s polaris
# 未登录时：
opscli auth login
```

---

## 前置依赖

**修改库存前必须先通过 `ops-shopify-query` 查询商品数据**：

1. 使用 `opscli shopify shop list` 获取 site_id
2. 使用 `opscli shopify product list --site-id <id>` 获取商品的 listing_id 和当前库存
3. 确认要修改的变体 listing_id 和目标库存后，执行修改

---

## 何时使用本 Skill

- **批量补库存**：一次性修改多个商品的库存数量
- **库存调整**：根据实际情况增减库存
- **库存清零**：将特定商品库存设为 0

---

## 快速参考

### 修改商品库存

```bash
# 修改单个商品库存
opscli shopify workorder update-stock \
  --site-id 123 \
  --updates '[{"listing_id": 1509, "new_inventory_quantity": 100}]'

# 批量修改多个商品库存
opscli shopify workorder update-stock \
  --site-id 123 \
  --updates '[
    {"listing_id": 1509, "new_inventory_quantity": 100},
    {"listing_id": 1510, "new_inventory_quantity": 200},
    {"listing_id": 1511, "new_inventory_quantity": 50}
  ]' \
  --reason "仓库补货"

# 库存清零
opscli shopify workorder update-stock \
  --site-id 123 \
  --updates '[{"listing_id": 1509, "new_inventory_quantity": 0}]' \
  --reason "断货清零"
```

---

## 完整命令参考

### `opscli shopify workorder update-stock`

批量修改商品库存，生成北极星工单。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--site-id` | 是 | 站点 ID |
| `--updates` | 是 | JSON 数组，每项包含 listing_id + new_inventory_quantity |
| `--reason` | 否 | 修改原因 |

**updates 格式**：

```json
[
  {
    "listing_id": 1509,
    "new_inventory_quantity": 100
  },
  {
    "listing_id": 1510,
    "new_inventory_quantity": 200
  }
]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `listing_id` | 是 | 变体级别的 listing_id |
| `new_inventory_quantity` | 是 | 新库存数量（整数） |

**输出示例（JSON）**：
```json
{
  "success": true,
  "task_id": "TASK-20250427-002",
  "message": "工单创建成功"
}
```

---

## 典型工作流

### 工作流 1：单商品补库存

```bash
# 1. 确认认证
opscli auth token status

# 2. 查询商品信息（ops-shopify-query）
opscli shopify product list --site-id 123

# 3. 修改库存
opscli shopify workorder update-stock \
  --site-id 123 \
  --updates '[{"listing_id": 1509, "new_inventory_quantity": 100}]'

# 4. 查询工单状态（ops-feed-task）
opscli feedtask status --task-id TASK-20250427-002
```

### 工作流 2：批量补货

```bash
# 1. 查询所有商品
opscli shopify product list --site-id 123 --limit 100

# 2. 批量修改库存
opscli shopify workorder update-stock \
  --site-id 123 \
  --updates '[
    {"listing_id": 1509, "new_inventory_quantity": 100},
    {"listing_id": 1510, "new_inventory_quantity": 200}
  ]' \
  --reason "仓库批量补货"
```

---

## 注意事项

- 库存修改通过北极星工单系统异步执行，提交后返回 task_id
- 使用 `opscli feedtask status --task-id <id>` 查询工单执行状态
- listing_id 是变体级别（非父商品级别），请从 product list 的 variants 中获取
- new_inventory_quantity 为绝对值（不是增量），设为 0 即库存清零
