---
name: ops-amazon-product-data
description: Use when the user asks for Amazon 商品页、ASIN、报价、Offer Listing、Buy Box、搜索结果、关键词商品、评论字段、商品原始字段、竞品页面数据、或需要把 Amazon 商品数据导出为 Excel 模板/回归样例；适用于单个或少量 ASIN/关键词的结构化商品数据采集与报告。
---

# ops-amazon-product-data

## Overview

用于获取 Amazon 商品结构化数据，并把结果整理为可复用的 Excel / JSON / Markdown 记录。对用户统一称为“Amazon 商品数据接口”或“商品数据采集接口”，不要暴露底层第三方服务商、内部 endpoint 或认证细节。

## 适用场景

用户提到以下任一需求时使用：

- 查 Amazon ASIN 商品页信息、价格、评分、图片、变体、BSR、技术规格。
- 查某个 ASIN 的卖家报价、Buy Box、库存、配送、Offer Listing。
- 按关键词获取 Amazon 搜索结果、广告位、排名、价格、评分。
- 询问 Amazon 商品评论字段、评论 ID、作者、日期、是否 verified purchase。
- 需要导出 Excel 模板、字段模板、raw 字段全量表、回归样例。
- 需要把商品数据保存为本地记录，方便后续复盘或 Skill 示例。

不适用：

- 大批量持续抓取或站点压测。
- 需要页面源码 HTML 的任务。
- 要求绕过平台限制、规避风控或高并发采集。

## 对用户的表达规则

- 对外使用通用说法：`Amazon 商品数据接口`、`商品数据采集接口`、`Amazon 商品数据工具`。
- 不在用户回复中主动出现第三方服务商名称、内部 URL、内部 endpoint、认证令牌、token 文件路径。
- 不要求用户传认证令牌；凭证由本地或服务端配置托管。
- 如果工具返回本地路径，只在需要用户打开本机文件时展示相对路径或经过确认的本地路径。
- 不展示 raw HTML；若用户要求源码类内容，说明当前只支持结构化 JSON 商品数据。

## 运行路径选择

默认优先使用正式 CLI 路径。只有在用户明确要求 MCP、当前宿主只能调用 MCP Tool、或 CLI 首次正式调用不可用时，才切换到 MCP 直连路径。

| 环境 / 约束 | 路径 | 说明 |
|---|---|---|
| 当前在 `opscli` 项目或本地可执行正式命令，且用户未指定 MCP | CLI 优先 | 使用 `opscli auth` 和 `opscli scrape-do`；这是最贴近真实交付的路径 |
| 用户明确要求 MCP，或当前宿主只能调用 MCP Tool | MCP 直连 | 使用 `auth_*` 与 `scrape_do_*` MCP tools |
| CLI 首次正式调用失败 | 切换 MCP 直连 | 若失败属于 `opscli` 命令失败，按项目规则提交 `ops-feedback` 后继续 |

不要在两条路径之间来回切换。选定路径后保持一致，除非当前路径不可用。

## CLI 授权与执行流程

CLI 路径先使用 `ops-auth` 的 CLI 模式确认本地登录态，再调用正式商品数据命令。

1. 检查登录态：`opscli auth token status`。
2. 如果未登录或 Token 无效，执行：`opscli auth login`。
3. 查看支持场景：`opscli scrape-do scenarios`。
4. 执行采集：`opscli scrape-do run <scenario> --site <site> --params '<json>'`。
5. 如需复核任务状态：`opscli scrape-do job-status <job_id>`。
6. 如需读取导出信息：`opscli scrape-do export <job_id>`。

CLI 内部会使用本地登录态向 OPS 获取远端 MCP 配置/API Key，然后调用远端 MCP 服务。不要要求用户提供 API Key，不要手动拼接远端 MCP URL，也不要在回复中展示 API Key、远端 URL、token 或内部 endpoint。

示例：

```bash
opscli auth token status
opscli scrape-do scenarios
opscli scrape-do run amazon-pdp --site US --params '{"asin":"B0C7BKZ883"}'
opscli scrape-do job-status <job_id>
opscli scrape-do export <job_id>
```

## MCP 授权与执行流程

MCP 直连路径先使用 `ops-auth` 的 MCP 模式确认登录态，再调用商品数据 MCP tools。

1. 检查登录态：`auth_is_authenticated()`。
2. 如果未登录，执行：`auth_mcp_login()`。
3. 首次使用当前 MCP 能力时，调用 `scrape_do_spec_must_read()`。
4. 调用 `scrape_do_scenarios()` 查看支持场景。
5. 选择场景并调用 `scrape_do_run()`。
6. 如需复核，调用 `scrape_do_job_status(job_id)`。
7. 如需下载表格，调用 `scrape_do_export(job_id)`。

MCP 直连路径也不要要求用户提供认证令牌或 API Key；凭证由登录态、远端配置或服务端托管。

## 场景选择

| 用户需求 | scenario | 必填参数 | 说明 |
|---|---|---|---|
| 商品页 / PDP / ASIN 基础信息 / 评论字段 | `amazon-pdp` | `asin` | 返回商品页结构化字段；可能包含 `reviews` 基础信息 |
| 卖家报价 / Offer Listing / Buy Box | `amazon-offer-listing` | `asin` | 返回报价列表、卖家、配送、价格等 |
| 关键词搜索 / 搜索页商品列表 | `amazon-search` | `keyword` | 返回搜索商品、排名、广告位、筛选项等 |

常用可选参数：

- `site`：默认 `US`，也可用 `JP`、`DE`、`GB` 等。
- `zipcode`：本地化邮编。
- `countryName`：本地化国家名称。
- `language`：语言。
- `page`：搜索页页码。
- `super`：更高成本代理，仅在普通请求失败或用户明确要求时使用。

限制：`zipcode` 与 `countryName` 不能同时传。

## 推荐执行流程

1. 明确目标：ASIN、关键词、站点、是否需要报价/搜索/商品页。
2. 按“运行路径选择”确定 CLI 或 MCP 直连路径。
3. 按所选路径完成授权检查；不要要求用户提供 token 或 API Key。
4. 选择场景并执行采集。
5. 查看返回的 `job_id`、`row_count`、`billing`、`export.url`。
6. 如需复核，按所选路径查询任务状态。
7. 如需下载表格，按所选路径读取导出信息。
8. 向用户总结时只说业务结果、导出文件、字段情况，不暴露供应商、API Key、远端 URL 或内部 endpoint。

## 输出文件说明

每个任务会生成：

- `params.json`：脱敏后的请求参数和运行配置。
- `raw.json`：脱敏后的原始结构化响应。
- `result.json`：规范化结果、计费、导出信息。
- `*.xlsx`：Excel 导出。

Excel 默认包含：

- 主表：规范化业务字段。
- `Raw Fields`：`raw.json.response` 顶层字段全量输出。
- `Raw *`：顶层数组字段自动拆 sheet，例如 `Raw Reviews`、`Raw Offers`、`Raw Products`、`Raw Images`、`Raw Variants`。

数组元素为对象时展开为列；嵌套对象/数组以 JSON 字符串保留。

## 评论字段说明

商品页场景可能返回 `reviews`。当前真实样例中 `Raw Reviews` 包含：

- `asin`
- `review_id`
- `author`
- `date`
- `verified_purchase`

如果接口后续返回评论标题、评分、正文等字段，`Raw Reviews` 会自动把新增字段作为列输出。

## 示例调用参数

商品页：

```json
{
  "scenario": "amazon-pdp",
  "site": "US",
  "params": {"asin": "B0C7BKZ883"}
}
```

报价：

```json
{
  "scenario": "amazon-offer-listing",
  "site": "US",
  "params": {"asin": "B0DGJ7HYG1"}
}
```

搜索：

```json
{
  "scenario": "amazon-search",
  "site": "US",
  "params": {"keyword": "laptop stands", "page": 1}
}
```

## 用户回复模板

```text
已完成 Amazon 商品数据采集：

- 场景：商品页 / 报价 / 搜索
- 站点：US
- 目标：ASIN 或关键词
- 结果行数：N
- 计费：request_cost=N，remaining_credits=N
- Excel：<下载链接或本地文件>

表格包含：
- 主表：规范化业务字段
- Raw Fields：原始结构化字段全量输出
- Raw Reviews / Raw Offers / Raw Products 等数组明细表
```

## 常见错误

| 问题 | 处理 |
|---|---|
| 缺少 ASIN 或 keyword | 要求用户补充目标 |
| `zipcode` 和 `countryName` 同时传 | 二选一 |
| 没有导出 URL | 提示稍后重试或查看本地任务文件 |
| 用户要求页面源码 | 说明当前只支持结构化商品数据 |
| 用户要求大量并发 | 说明当前按认证令牌串行执行，建议拆批 |

## 安全与脱敏

- 不在回复中输出认证令牌。
- 不把认证令牌写入回归说明或示例。
- 不暴露内部 endpoint 或第三方服务商名称。
- 不展示 HTML 源码。
- 面向用户的错误摘要要保留业务可诊断信息，但去掉 token、本地绝对路径和内部接口细节。
