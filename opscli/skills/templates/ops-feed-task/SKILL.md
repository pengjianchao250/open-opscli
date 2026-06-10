---
name: ops-feed-task
description: 创建和查询北极星刊登系统工单，所有 Shopify 操作的工单均通过本 Skill 管理
version: v0.0.1
---

# ops-feed-task

创建和查询北极星（Polaris）刊登系统工单。所有 Shopify 操作（改价/改库存/上架/下架/删除）都通过工单系统异步执行，本 Skill 提供工单创建和状态查询能力。

> 本 Skill 通常由其他 `ops-shopify-*` Skill 自动调用，也可独立用于查询工单状态。

---

## 强制认证门禁

> **【强制】每次调用 `ops-feed-task` 前，必须先检测 polaris 系统是否已授权登录。**

```bash
opscli auth token status
# polaris Token 异常时：
opscli auth token refresh -s polaris
# 未登录时：
opscli auth login
```

---

## 何时使用本 Skill

- **查询工单状态**：检查价格/库存/上下架操作是否执行成功
- **创建通用工单**：构造自定义 payload 创建工单（高级用法）

---

## 快速参考

### 查询工单状态

```bash
# 查询工单详情
opscli feedtask status --task-id "TASK-20250427-001"
```

### 创建工单（高级）

```bash
# 使用 JSON 文件创建工单
opscli feedtask create --payload ./task-payload.json
```

---

## 完整命令参考

### `opscli feedtask status`

查询工单状态和详情。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--task-id` | 是 | 工单 ID |

```bash
opscli feedtask status --task-id "TASK-20250427-001"
```

**输出示例（JSON）**：
```json
{
  "task_id": "TASK-20250427-001",
  "status": "success",
  "message": "执行成功",
  "detail": { ... }
}
```

**工单状态说明**：

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `processing` | 执行中 |
| `success` | 执行成功 |
| `failed` | 执行失败 |

---

### `opscli feedtask create`

创建工单（通用接口，接受完整的 createCustomTask payload）。

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--payload` | 是 | JSON 文件路径，包含完整的 createCustomTask 请求体 |

> 通常不需要手动调用此命令，`ops-shopify-*` Skill 会自动构造 payload 并创建工单。

**payload 文件示例（JSON）**：
```json
{
  "feed_task_template_id": "7508",
  "operateMethod": "shopifyModifyPrice",
  "siteId": 123,
  "batchListings": [
    {
      "listingId": 1510,
      "variants": [
        {
          "variantId": 2001,
          "price": 29.99,
          "compareAtPrice": 25.0
        }
      ]
    }
  ]
}
```

```bash
opscli feedtask create --payload ./price-update.json
```

---

## 典型工作流

### 工作流 1：查询操作结果

```bash
# 1. 执行 Shopify 操作（例如改价）
opscli shopify workorder update-price \
  --site-id 123 \
  --updates '[{"listing_id": 1510, "new_price": 29.99}]'
# 返回: {"task_id": "TASK-20250427-001", ...}

# 2. 查询工单状态
opscli feedtask status --task-id "TASK-20250427-001"
```

### 工作流 2：轮询等待工单完成

```bash
# 提交工单后，轮询状态直到完成
TASK_ID="TASK-20250427-001"

# 查询状态
opscli feedtask status --task-id "$TASK_ID"
# 如返回 pending/processing，等待后再次查询
```

---

## 工单与操作类型对应关系

| 操作 | operateMethod | template_id |
|------|--------------|-------------|
| 修改价格 | `shopifyModifyPrice` | 7508 |
| 修改库存 | `shopifyModifyInventory` | 7506 |
| 上架（设活跃） | `shopifySetActive` | 4399 |
| 下架/删除（设草稿） | `shopifySetDraft` | 4401 |

---

## 注意事项

- 工单创建后会异步执行，不会立即生效
- 建议在提交工单后间隔一段时间再查询状态
- 如果工单失败，检查错误信息（detail 字段）确认原因
