---
name: ops-keepa
description: Use when the user asks to query or export Keepa data through the public `opscli keepa` CLI or the remote Keepa MCP flow, especially product lookup, product search, product finder, category lookup, seller lookup, best sellers, deals, or lightning deals.
---

# ops-keepa

用于把 Keepa 自然语言需求映射成正式 `opscli keepa ...` 命令，并沿着“本地 CLI -> 远端 MCP 配置 -> 远端 `keepa_*` tool”这条公开链路完成查询和导出。

当前对用户公开的正式 CLI 入口是 `opscli keepa ...`。
该入口默认通过本机 CLI 登录态获取远端 MCP 配置，再调用远端 `keepa_*` tool；普通用户不需要直接接触 API Key、远端 URL 或内部调试目录。
正式 CLI 依赖本机已完成 OPS 授权；若本机未登录或登录态过期，先完成 `opscli auth login` 再继续。

## 快速规则

1. 正式命令面默认只讲 `opscli keepa ...`，不要向用户暴露内部调试命令、本地落盘目录或调试入口。
2. 先识别场景，再构造 `scenario + site + params`；不确定时先看 `opscli keepa scenarios`。
3. 默认 `site=US`，默认导出 `xls`；公开 CLI 支持 `xls/xlsx/json`，其中 `xls/xlsx` 最终都会生成用户可读的 `.xlsx`。
4. `params` 必须是 JSON 对象字符串；不要把数组、裸字符串或半结构化文本直接塞给 `--params`。
5. `product` 至少提供 `asin/asins` 或 `code/codes` 之一，不能同时传两类标识。
6. `product-search`、`category-search` 缺少关键词时先补关键词；`seller` 缺少 seller id、`category-lookup` 缺少 category id、`bestsellers` 缺少 `category` 或 `productGroup` 时先澄清。
7. 不向用户暴露 Keepa token 余额、账号来源、`params.json`、`raw.json`、本地导出路径等内部信息；MCP 每日调用额度按本 Skill 的回复规则展示。
8. 如果当前宿主是远端 MCP 直连而不是 CLI 代理，继续看 [SKILL_MCP.md](SKILL_MCP.md)。
9. 若远端 MCP 直连时提示 `无 session_id：请完成授权登录，或传入有效的 session_id` 等授权类错误，先执行 `auth_mcp_login`；不要先把问题归因为 Keepa 场景、参数或导出格式。

## 导出格式选择

| 任务目的 | 推荐格式 | 执行规则 |
| --- | --- | --- |
| 单个任务，用户要打开、下载或留档 | `xls` | 显式传 `--export-format xls`；最终文件为 `.xlsx` |
| 多个任务，Skill/Agent 要汇总、计算或生成报告 | `json` | 每个任务显式传 `--export-format json`，完成后再合并分析 |
| 用户明确指定格式 | 用户指定格式 | 不用默认推荐覆盖用户选择 |

JSON 与格式化后的 XLSX 共用表头、字段转换、列顺序和附加 Sheet 数据。读取时：

1. 校验 `schema_version="1.0"`，再按 `sheets` 中 `Sheet1`、`Sheet2` 的顺序读取。
2. 把每个 `SheetN` 当作一个 XLSX 工作表，不要把它误解为 Keepa API 的分页；真实表名读取 `name`。
3. 按 `columns[index]` 解释 `rows[*][index]`，不要先把行数组猜成对象；`row_count` 用于校验实际行数。
4. 多任务分析时保留 `job_id + SheetN + name` 的来源关系，合并前按列名对齐；不要只读取 `Sheet1` 而遗漏价格历史、Offer、变体或 search insights 等附加表。
5. 不要把内部 `raw.json`、`result.json` 或服务端路径作为用户导出文件返回；原始字段核对仍以内部 `raw.json` 为准。

示例：

```powershell
# 单任务给用户查看
opscli keepa run product --site US --params '{"asin":"B0088PUEPK"}' --export-format xls

# 多任务或后续分析报告
opscli keepa run product-search --site US --params '{"keyword":"flashlight"}' --export-format json
```

## 链路区分

- 本地 CLI 代理链路：默认指 `opscli keepa ...`。这条链路依赖本机 `opscli auth login` 已完成，必要时由 CLI 显式透传本机 OPS `session_id`。
- 远端 MCP 直连链路：指宿主拿远端 MCP `api_key` 直接连接 `keepa_*` tools。该链路下不要在仅拿到 `api_key` 后立刻执行 `keepa_run`；应先完成 `auth_mcp_login`，让当前 MCP 用户的远端凭证中存在可复用的 OPS `session_id`。

## 正式链路

- 本地 CLI 代理链路：`opscli keepa ...`
- 远端 MCP tools：`keepa_scenarios`、`keepa_quota_status`、`keepa_run`、`keepa_job_status`、`keepa_export`
- 常见前置：确认本机 `opscli auth login` 已完成且登录态仍有效

说明：

- 正式 CLI 会自动拉取远端 MCP HTTP 配置并转发，不需要用户手写远端地址。
- Keepa 额度和账号由后端统一管理；若后端没有 OPS 登录态，也可能使用服务器侧集成账号或 `OPSCLI_KEEPA_API_KEY` 兜底，但这不属于普通用户需要操作的内容。

## 命令面

1. 查看场景

```powershell
opscli keepa scenarios
```

2. 查询每日额度

```powershell
opscli keepa quota-status
```

该命令只读取当前用户的 MCP 每日调用额度，不消耗调用次数，也不展示 Keepa 账号级 token 余额。

3. 执行场景

```powershell
opscli keepa run <scenario> --site US --params '{"asin":"B0088PUEPK"}'
```

可用参数：

- `scenario`：场景 ID，如 `product`、`product-search`
- `--site`：站点，默认 `US`
- `--params`：JSON 对象字符串
- `--job-id`：自定义任务 ID
- `--export-format`：`xls` / `xlsx` / `json`
- `--reserve-tokens`：预留 token 阈值
- `--force`：忽略 token 预检查提醒继续执行
- `--wait`：token 不足时等待一次 refill 后再执行

4. 查任务结果

```powershell
opscli keepa job-status <job_id>
```

5. 查导出文件

```powershell
opscli keepa export <job_id>
```

## 最小工作流

1. 用自然语言判断场景；拿不准时先跑 `opscli keepa scenarios`
2. 只补当前场景缺失的必填参数
3. 组织 `scenario + site + params`，执行 `opscli keepa run ...`
4. 用户执行前想确认今天还能查几次时，使用 `opscli keepa quota-status`
5. 如果用户要续查任务或只要导出文件，再用 `job-status` / `export`

## 场景速查

| 用户意图 | scenario | 必填参数 | 常用可选参数 |
| --- | --- | --- | --- |
| 查商品详情、查 ASIN、查价格历史 | `product` | `asin/asins` 或 `code/codes` | `stats`, `history`, `offers`, `buybox`, `rating`, `days`, `update` |
| 关键词搜商品 | `product-search` | `keyword` 或 `term` | `page`, `stats`, `history`, `update`, `asins_only` |
| 按条件筛商品 | `product-finder` | `selection` 或至少 1 个筛选字段 | `stats` |
| 查类目关键词 | `category-search` | `keyword` 或 `term` | `parents` |
| 查类目详情 | `category-lookup` | `category/categories` | `parents` |
| 查卖家/店铺 | `seller` | `seller/sellers` | `storefront`, `update` |
| 查头部卖家 | `top-seller` | 无 | 无 |
| 查热销榜 | `bestsellers` | `category` 或 `productGroup` | 无 |
| 查折扣商品 | `deals` | 无固定必填，建议给 `selection` | `selection` |
| 查秒杀 | `lightning-deals` | 无 | `asin` |

## 常用示例

商品详情：

```powershell
opscli keepa run product --site US --params '{"asin":"B0088PUEPK","stats":30,"history":true}'
```

关键词搜索：

```powershell
opscli keepa run product-search --site US --params '{"keyword":"flashlight","page":0}'
```

只导出 ASIN 列表：

```powershell
opscli keepa run product-search --site US --params '{"keyword":"flashlight","asins_only":true}'
```

查卖家：

```powershell
opscli keepa run seller --site US --params '{"seller":"A2L77EE7U53NWQ","storefront":true}'
```

查热销榜：

```powershell
opscli keepa run bestsellers --site US --params '{"category":"172282"}'
```

## 回复规则

- 成功时只保留：场景、站点、查询对象、`job_id`、`row_count`、导出文件
- 若 `keepa_run` 响应顶层存在 `quota`，在最终回复末尾补一句：
  - `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
- `keepa_scenarios`、`keepa_quota_status`、`keepa_job_status`、`keepa_export` 不消耗额度；只有 `keepa_run` 消耗次数。
- `job_status` 和 `export` 默认不重复提示额度，避免轮询阶段重复刷屏。
- 如果 `row_count=0`，明确告诉用户无匹配结果，并提醒核对站点、ASIN、关键词或筛选条件
- 用户问“字段准不准”时，说明 XLSX/JSON 都是在 Keepa 原始响应基础上做同源中文表头和可读化处理；口径以 Keepa 原始响应和官方文档为准
- 不要主动打印 Keepa token 消耗、token 余额、服务器本地路径或内部原始 JSON
