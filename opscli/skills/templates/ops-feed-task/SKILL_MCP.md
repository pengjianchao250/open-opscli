---
name: ops-feed-task
mcp-version: v0.0.1
description: 通过 MCP Tool 创建和查询北极星刊登系统工单（无状态模式）
---

# ops-feed-task (MCP 无状态模式)

通过 MCP Tool 创建和查询北极星（Polaris）刊登系统工单。所有 Shopify 操作通过工单异步执行，本 Skill 提供工单状态查询能力。

---

## 强制认证门禁

```python
auth_is_authenticated(session_id="xxx")
```

---

## 完整 Tool 参考

### `feedtask_create`

创建工单（通用接口，接受完整的 createCustomTask payload）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payload` | dict | 是 | 完整的 createCustomTask 请求体 |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
feedtask_create(
    payload={
        "feed_task_template_id": "7508",
        "operateMethod": "shopifyModifyPrice",
        "siteId": 123,
        "batchListings": [...]
    },
    session_id="xxx"
)
```

> 通常不需要手动调用此工具，`shopify_update_prices` 等工具会自动创建工单。

---

### `feedtask_status`

查询工单状态/详情。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 工单 ID |
| `session_id` | string | 是 | Session ID |
| `jwt` | string | 否 | 已有 JWT |

```python
feedtask_status(task_id="TASK-20250427-001", session_id="xxx")
```

**返回示例**：
```json
{
  "success": true,
  "data": {
    "task_id": "TASK-20250427-001",
    "status": "success",
    "message": "执行成功",
    "detail": {}
  },
  "error": null
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

## 典型工作流

### 查询操作结果

```python
# 1. 执行 Shopify 操作（例如改价）
result = shopify_update_prices(
    site_id=123,
    updates=[{"listing_id": 1510, "new_price": 29.99}],
    session_id="xxx"
)
task_id = result["data"]["task_id"]

# 2. 查询工单状态
status = feedtask_status(task_id=task_id, session_id="xxx")

# 3. 根据状态决定后续操作
if status["data"]["status"] == "success":
    print("操作成功")
elif status["data"]["status"] in ("pending", "processing"):
    print("工单执行中，请稍后查询")
```

---

## 工单与操作类型对应关系

| 操作 | operateMethod | template_id |
|------|--------------|-------------|
| 修改价格 | `shopifyModifyPrice` | 7508 |
| 修改库存 | `shopifyModifyInventory` | 7506 |
| 上架（设活跃） | `shopifySetActive` | 4399 |
| 下架/删除（设草稿） | `shopifySetDraft` | 4401 |
