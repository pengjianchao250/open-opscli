---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵 MCP 使用规范。用于通过 seller_sprite_* 工具执行场景查询、轮询异步任务、读取导出文件并给出用户可读结果。
---

# ops-seller-sprite MCP

先读 [SCENARIO_PARAMS_ZH.md](SCENARIO_PARAMS_ZH.md) 获取场景映射、缺参规则和参数口径；本文件只保留 MCP 工具链和异步执行规则。

## MCP 工具

- `seller_sprite_scenarios`：查看支持的场景。
- `seller_sprite_run`：执行场景并创建导出任务。
- `seller_sprite_job_status`：按 `job_id` 查看任务状态。
- `seller_sprite_export`：读取导出文件路径、URL、文件名和 MIME 信息。

## 执行规则

1. 拿不准场景或必填参数时，先调 `seller_sprite_scenarios` 或先回看参数手册。
2. 真正执行只用 `seller_sprite_run`；不要调用内部 start helper。
3. 不要传 `mode`、`browser-route`、`api-direct`、`async_mode` 这类控制参数；同步/异步与采集模式由后端决定。
4. `competitor-lookup` 如果只有单个 ASIN，也要先按 `asins` 传；缺少 `keyword`、`brand`、`sellerName`、`asin/asins` 这类主筛选条件时，直接报错或澄清，不要把无效请求拖成 30 秒超时。
5. 每次成功执行后都记录 `data.job_id`；状态查询和导出都复用这个 `job_id`。
6. 如果返回 `data.state=queued` 或 `running`，在当前回复轮次内每 5-10 秒调用一次 `seller_sprite_job_status(job_id)`，总等待 60-90 秒。
7. 如果任务在当前轮次内完成，直接返回结果和导出文件；如果还在跑，明确告诉用户任务仍在进行，并保留 `job_id` 供后续续查。
8. 用户后续只说 `继续`、`查结果`、`刚才那个好了没` 时，直接复用最近一次 SellerSprite `job_id`。
9. 用户只需要文件链接时，调用 `seller_sprite_export`。
10. MCP tools 不可用时，直接说明当前宿主没有可用的 SellerSprite MCP。

## 认证与运行时边界

- SellerSprite 登录态由后端缓存；不要手动重复登录。
- 集成账号也由后端缓存；只有 SellerSprite 登录本身失败时，才需要后端刷新账号或登录态。
- 浏览器运行时由部署侧决定；Agent 不负责切换 Patchright / Playwright / Chrome。

## 异步状态

| `state` | 含义 | Agent 动作 |
| --- | --- | --- |
| `queued` | 任务已创建，等待后台 worker | 继续轮询，或告知用户稍后续查 |
| `running` | 后台正在执行 | 继续轮询，或告知用户稍后续查 |
| `succeeded` | 已完成，结果和导出可读 | 返回 `summary`、`job_id`、`row_count`、导出文件 |
| `failed` | 后台执行失败 | 报告 `error.message`，不要复用旧导出文件 |

## 回复规则

- 优先读取并复用：
  - `data.summary`
  - `data.job_id`
  - `data.row_count`
  - `data.export.filename`
  - `data.export.url`
  - `data.export.path`
  - `data.export.format`
- 不要在最终回复里打印完整工具参数、原始 JSON、内部路径或账号信息。
- 若存在 `data.summary`，优先把它当成结果主文案，只补最少的任务信息。

成功模板：

```md
已按 `site` 做好了 `scenario title`，并导出为 `format`。

结果：
- `job_id`: xxx
- `row_count`: 20
- 导出文件: [filename](url-or-path)
```

补充规则：

- 第一行只保留关键条件，如站点、关键词、ASIN、月份、推荐模式。
- 优先展示文件名或链接，不要单独贴长本地路径。
- `row_count=0` 时，要明确提示用户核对站点、ASIN、关键词、类目或筛选是否过窄。
