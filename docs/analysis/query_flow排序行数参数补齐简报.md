# query_flow 排序/行数参数补齐 — 简报

> 日期：2026-07-27 ｜ 后端：ops.cm（张培良账号）｜ 提交：`fb98687`（合入 release `89e69a9`，已 push）

## 问题

一体化取数 `query_flow`（CLI `opscli query flow` / MCP `query_flow`）执行段最小实现只按规划合同的 `execution_ref.query_template` 直接执行，而模板里 `orderBy`/`limit` 是 None 占位、无 `offset` 键，`run_query_template` 执行前剔除 None 键 → **不下发**。后端 `SimpleQueryBuilder::build()`（`data-metrics/.../SimpleQueryBuilder.php:99`）对未传 limit 用 `$simple['limit'] ?? 20`、orderBy 用空数组 → `query_flow` **恒吃默认 limit=20、无排序**。AI 取数频繁「数据被截断：只返回 20/298 行」且无法控制行数/排序。

**定位**：后端确有 20 默认（`?? 20`），但客户端可传 `limit`/`orderBy`/`offset` 覆盖（后端 limit 无 max），根因是客户端一体化路径没把这三个参数接出来——只改客户端即可。

## 修复

给一体化路径补齐参数（默认口径 A：不设客户端默认，不传就沿用后端 20）：

| 端 | 新增 |
| --- | --- |
| CLI `opscli query flow` | `--limit`、`--order-by <字段>[:asc\|desc]`（可重复）、`--offset` |
| MCP `query_flow` | `limit`、`order_by`（`[{"field","desc":bool}]`，兼容 JSON 串）、`offset` |
| 内核 `entry.run_flow` | 同名形参，planned 时填入 query_template 再执行，改写后重挂 plan_integrity 保持自洽 |

顺带修正 `query_plan._build_query_template` 的 orderBy 文案：后端只认 `{field, desc:bool}`，此前文案写的 `direction:"DESC\|ASC"` 会被后端忽略（恒升序），已改。

## 验收（真实后端 ops.cm，请求「查询各渠道SKU的销售额 近30天」，共 298 行）

| 用例 | 结果 |
| --- | --- |
| 默认（不传 limit） | 20/298（截断复现） |
| `--limit 500` | 返回 **298 行全拿**（rowCount==totalCount） |
| `--order-by price:desc` | 前 5 = [65677, 50665, 47109, 41901, 41493]，**单调递减、排序正确** |
| MCP `query_flow(limit=100, order_by=[{field:price,desc:true}])` | success，100 行 |
| CLI `opscli query flow ... --limit 500 --order-by price:desc` | 298 行，execution_ref.query_template.limit=500、orderBy 正确注入 |
| 单测 | 43 passed（run_flow 注入+plan_integrity 自洽 / CLI 解析+非法方向报错 / MCP JSON 串兼容） |
| 回归 | query+mcp 140 passed（仅 catalog/intent 2 既有基线） |

## 用法

```bash
# 取全 + 按指标降序
opscli query flow "查询各渠道SKU的销售额 近30天" --limit 500 --order-by "price:desc"
# MCP
query_flow(request="...", limit=500, order_by=[{"field": "price", "desc": true}])
```
截断时（rowCount < totalCount）传更大的 `limit` 重查即可取全。

## 仍未内核化（与本次无关，独立后续任务）

- orderBy 服务端缺陷的**本地兜底/加量重查**（TopN 过渡方案）；
- 完整结果落盘 `result_dir`。

（均在 query_flow 返回体 `execution_notes` 如实披露。）
