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
3. 默认 `site=US`，默认导出 `xls`；公开 CLI 下 `xls/xlsx` 最终都会生成用户可读的 `.xlsx`。
4. `params` 必须是 JSON 对象字符串；不要把数组、裸字符串或半结构化文本直接塞给 `--params`。
5. `product` 至少提供 `asin/asins` 或 `code/codes` 之一，不能同时传两类标识。
6. `product-search`、`category-search` 缺少关键词时先补关键词；`seller` 缺少 seller id、`category-lookup` 缺少 category id、`bestsellers` 缺少 `category` 或 `productGroup` 时先澄清。
7. 不向用户暴露 Keepa token 余额、账号来源、`params.json`、`raw.json`、本地导出路径等内部信息。
8. 如果当前宿主是远端 MCP 直连而不是 CLI 代理，继续看 [SKILL_MCP.md](SKILL_MCP.md)。
9. 若远端 MCP 直连时提示 `无 session_id：请完成授权登录，或传入有效的 session_id` 等授权类错误，先执行 `auth_mcp_login`；不要先把问题归因为 Keepa 场景、参数或导出格式。

## 链路区分

- 本地 CLI 代理链路：默认指 `opscli keepa ...`。这条链路依赖本机 `opscli auth login` 已完成，必要时由 CLI 显式透传本机 OPS `session_id`。
- 远端 MCP 直连链路：指宿主拿远端 MCP `api_key` 直接连接 `keepa_*` tools。该链路下不要在仅拿到 `api_key` 后立刻执行 `keepa_run`；应先完成 `auth_mcp_login`，让当前 MCP 用户的远端凭证中存在可复用的 OPS `session_id`。

## 正式链路

- 本地 CLI 代理链路：`opscli keepa ...`
- 远端 MCP tools：`keepa_scenarios`、`keepa_run`、`keepa_job_status`、`keepa_export`
- 常见前置：确认本机 `opscli auth login` 已完成且登录态仍有效

说明：

- 正式 CLI 会自动拉取远端 MCP HTTP 配置并转发，不需要用户手写远端地址。
- Keepa 额度和账号由后端统一管理；若后端没有 OPS 登录态，也可能使用服务器侧集成账号或 `OPSCLI_KEEPA_API_KEY` 兜底，但这不属于普通用户需要操作的内容。

## 命令面

1. 查看场景

```powershell
opscli keepa scenarios
```

2. 执行场景

```powershell
opscli keepa run <scenario> --site US --params '{"asin":"B0088PUEPK"}'
```

可用参数：

- `scenario`：场景 ID，如 `product`、`product-search`
- `--site`：站点，默认 `US`
- `--params`：JSON 对象字符串
- `--job-id`：自定义任务 ID
- `--export-format`：`xls` / `xlsx`
- `--reserve-tokens`：预留 token 阈值
- `--force`：忽略 token 预检查提醒继续执行
- `--wait`：token 不足时等待一次 refill 后再执行

3. 查任务结果

```powershell
opscli keepa job-status <job_id>
```

4. 查导出文件

```powershell
opscli keepa export <job_id>
```

## 最小工作流

1. 用自然语言判断场景；拿不准时先跑 `opscli keepa scenarios`
2. 只补当前场景缺失的必填参数
3. 组织 `scenario + site + params`，执行 `opscli keepa run ...`
4. 如果用户要续查任务或只要导出文件，再用 `job-status` / `export`

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
- 如果 `row_count=0`，明确告诉用户无匹配结果，并提醒核对站点、ASIN、关键词或筛选条件
- 用户问“字段准不准”时，只说明 XLSX 是在 Keepa 原始响应基础上做中文表头和可读化处理；口径以 Keepa 原始响应和官方文档为准
- 不要主动打印 token 消耗、剩余额度、服务器本地路径、内部原始 JSON
