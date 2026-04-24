---
name: ops-dataset-query
description: 通过 opscli MCP Tools 查询数据集 metadata 并执行取数
version: v0.0.1
---

# ops-dataset-query（MCP 版）

通过 opscli MCP Server 的 `query_*` Tools 完成数据集字段查询、payload 构造和远端取数。MCP 版直接返回结构化 dict，不需要写 subprocess 包装。

## 前置认证

1. 调用 `auth_is_authenticated()`。
2. 如未登录，按 `ops-auth（MCP 版）` 的 `auth_login_start()` 与 `auth_login_poll()` 流程完成授权。
3. 如查询返回认证错误，先调用 `auth_token_refresh(system="ops")`，失败后重新登录。

## 标准查询流程

1. `query_metadata(dataset="dataset_alias")`：查看数据集字段定义。
2. 根据字段类型选择维度和指标。
3. `query_build_and_run(...)`：构造 payload 并直接执行查询。

示例：

```text
query_build_and_run(
  dataset="sales_dataset",
  dimensions=["date_id", "country_code"],
  metrics=["sales:SUM:sales_sum"],
  where_conditions=["date_id|>=|\"2026-01-01\""],
  order_by=["sales_sum:desc"],
  limit=50
)
```

## 高级查询流程

- `query_build(..., dry_run=True)`：仅生成 payload。
- `query_build(..., output_path="/tmp/query.json")`：将 payload 写入文件。
- `query_run(payload_path="/tmp/query.json")`：读取文件并执行。

## 错误处理

所有 Tool 返回统一结构。失败时读取 `error.code` 和 `error.message`，不要直接访问后端 HTTP API，不要绕过 opscli 的认证、参数校验和错误映射。
