---
name: ops-shopify-price
description: 批量修改 Shopify 商品价格，通过北极星刊登系统生成工单执行
version: v0.0.1
---

# ops-shopify-price

批量修改 Shopify 商品价格，通过北极星（Polaris）刊登系统生成工单执行。所有操作通过 `opscli shopify` 子命令完成。

---

## 强制认证门禁

> **【强制】每次调用 `ops-shopify-price` 前，必须先检测 polaris 系统是否已授权登录。**

```bash
opscli auth token status
# polaris Token 异常时：
opscli auth token refresh -s polaris
# 未登录时：
opscli auth login
```

---

## 前置依赖

**修改价格前必须先通过 `ops-shopify-query` 查询商品数据**：

1. 使用 `opscli shopify shop list` 获取 site_id
2. 使用 `opscli shopify product list --site-id <id>` 获取商品的 listing_id 和当前价格
3. 确认要修改的变体 listing_id 和目标价格后，执行修改

> **重要**：系统会自动在修改前加载商品数据到缓存，但建议先手动查询确认商品信息。

---

## 何时使用本 Skill

- **批量改价**：一次性修改多个商品/变体的价格
- **促销定价**：设置原价和促销价
- **价格调整**：根据策略调整商品定价

---

## 快速参考

### 修改商品价格

```bash
# 修改单个商品价格
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[{"listing_id": 1510, "new_price": 29.99}]'

# 修改价格并设置促销价
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[{"listing_id": 1510, "new_price": 29.99, "new_sale_price": 25.0}]'

# 批量修改多个商品价格
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[{"listing_id": 1510, "new_price": 29.99}, {"listing_id": 1511, "new_price": 39.99}]' \
  --reason "季度促销调价"

# 修改价格并附带原因
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[{"listing_id": 1510, "new_price": 35.99}]' \
  --reason "竞品对标调价"
```

---

## 完整命令参考

### `opscli shopify workorder update-price`

批量修改商品价格，生成北极星工单。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--site-id` | 是 | 站点 ID |
| `--updates` | 是 | JSON 数组，每项包含 listing_id + new_price（可选 new_sale_price） |
| `--reason` | 否 | 修改原因 |

**updates 格式**：

```json
[
  {
    "listing_id": 1510,
    "new_price": 29.99,
    "new_sale_price": 25.0
  },
  {
    "listing_id": 1511,
    "new_price": 39.99
  }
]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `listing_id` | 是 | 变体级别的 listing_id |
| `new_price` | 是 | 新原价 |
| `new_sale_price` | 否 | 新促销价 |

**输出示例（JSON）**：
```json
{
  "success": true,
  "task_id": "TASK-20250427-001",
  "message": "工单创建成功"
}
```

---

## 典型工作流

### 工作流 1：单商品改价

```bash
# 1. 确认认证
opscli auth token status

# 2. 查询店铺和商品（ops-shopify-query）
opscli shopify shop list
opscli shopify product list --site-id 123

# 3. 修改价格
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[{"listing_id": 1510, "new_price": 29.99}]'

# 4. 查询工单状态（ops-feed-task）
opscli feedtask status --task-id TASK-20250427-001
```

### 工作流 2：批量促销改价

```bash
# 1. 查询商品列表
opscli shopify product list --site-id 123 --limit 100

# 2. 批量修改价格
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[
    {"listing_id": 1510, "new_price": 29.99, "new_sale_price": 25.0},
    {"listing_id": 1511, "new_price": 39.99, "new_sale_price": 35.0},
    {"listing_id": 1512, "new_price": 19.99, "new_sale_price": 15.0}
  ]' \
  --reason "618 促销活动"
```

---

## 注意事项

- 价格修改通过北极星工单系统异步执行，提交后返回 task_id
- 使用 `opscli feedtask status --task-id <id>` 查询工单执行状态
- listing_id 是变体级别（非父商品级别），请从 product list 的 variants 中获取
- 建议附带修改原因（--reason），便于审计追溯
