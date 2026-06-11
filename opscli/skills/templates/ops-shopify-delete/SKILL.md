---
name: ops-shopify-delete
version: v1.0.0
description: 删除 Shopify 商品（支持 seller_sku 快捷操作）
---

# ops-shopify-delete

通过 `opscli` 命令删除 Shopify 商品，支持批量操作和 seller_sku 快捷模式。

---

## 前置条件

### 1. 登录授权

```bash
opscli auth login
```

### 2. 删除模板 ID 配置

默认模板 ID 为 1783，如需修改：

```ini
# ~/.config/opscli/config.ini
[shopify_templates]
delete = 1783
```

---

## 命令参考

### 通过 seller_sku 删除（推荐）

```bash
# 单个 SKU
opscli shopify workorder delete --site 1132 --sellsku QD74024-4

# 多个 SKU（逗号分隔）
opscli shopify workorder delete --site 1132 --sellsku QD74024-4,QD54446-5
```

### 通过 listing_id 删除

```bash
opscli shopify workorder delete --site 1132 --variants '[138]' --products '[91]'
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--site` | 是 | 站点 ID |
| `--sellsku` | 否 | 卖家 SKU，多个用逗号分隔（与 --variants 二选一） |
| `--variants` | 否 | variant ID 列表 JSON |
| `--products` | 否 | product ID 列表 JSON（默认 `[]`） |

---

## 典型工作流

```bash
# 1. 确认登录
opscli auth token status

# 2. 查看商品
opscli shopify product list --site 8717

# 3. 通过 seller_sku 删除
opscli shopify workorder delete --site 1132 --sellsku QD74024-4

# 4. 查询工单状态
opscli feedtask status --task-id "返回的feed_task_code"
```
