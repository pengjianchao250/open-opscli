---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵 MCP 使用规范。用于通过 seller_sprite_* 工具执行场景查询、轮询异步任务、读取导出文件并给出用户可读结果。
---

# ops-seller-sprite MCP

先读 [SCENARIO_PARAMS_ZH.md](SCENARIO_PARAMS_ZH.md) 获取场景映射、缺参规则和参数口径；本文件只保留 MCP 工具链和异步执行规则。

## MCP 工具

- `seller_sprite_scenarios`：查看支持的场景。
- `seller_sprite_quota_status`：查看当前用户今日剩余额度。
- `seller_sprite_run`：执行场景，并在公开入口内先等待任务完成。
- `seller_sprite_job_status`：按 `job_id` 查看任务状态。
- `seller_sprite_export`：读取导出文件路径、URL、文件名和 MIME 信息。

## 执行规则

1. 如果当前宿主是通过远端 MCP `api_key` 直接连接 `seller_sprite_*` tools，首次执行前必须先完成 `auth_mcp_login`；不要在仅拿到 `api_key` 后直接调用 `seller_sprite_run`。
2. 拿不准场景或必填参数时，先调 `seller_sprite_scenarios` 或先回看参数手册。
3. 真正执行只用 `seller_sprite_run`；不要调用内部 start helper。
4. 不要传 `mode`、`browser-route`、`api-direct`、`async_mode` 这类控制参数；同步/异步与采集模式由后端决定。
5. `competitor-lookup` 如果只有单个 ASIN，也要先按 `asins` 传；缺少 `keyword`、`brand`、`sellerName`、`asin/asins` 这类主筛选条件时，直接报错或澄清，不要把无效请求拖成 30 秒超时。
6. `seller_sprite_run` 会在公开入口内持续等待：`queued` 阶段继续等，进入 `running` 后最多再等 8 分钟。
7. 如果任务在上述等待窗口内完成，直接返回结果和导出文件；如果 `running` 超过 8 分钟仍未完成，才返回 `job_id` 供后续续查。
8. 只有当 `seller_sprite_run` 已经返回 `job_id` 但结果未完成时，才继续调用 `seller_sprite_job_status(job_id)`。
9. 用户后续只说 `继续`、`查结果`、`刚才那个好了没` 时，直接复用最近一次 SellerSprite `job_id`。
10. 用户只需要文件链接时，调用 `seller_sprite_export`。
11. 用户执行前如果想确认今天还能查几次，调用 `seller_sprite_quota_status`。
12. MCP tools 不可用时，直接说明当前宿主没有可用的 SellerSprite MCP。

## 认证与运行时边界

- 远端 MCP 直连场景下，OPS `session_id` 由 `auth_mcp_login` 建立并保存在当前 MCP 用户的隔离凭证里；不要把“已拿到 MCP `api_key`”误当成“已经具备 `seller_sprite_run` 所需的 OPS 登录态”。
- 正式 `opscli seller-sprite ...` CLI 代理链路不属于本文件的默认语境；如果宿主走的是 CLI 代理链路，可由 CLI 显式透传本机 `session_id`，因此不要求先单独执行 `auth_mcp_login`。
- SellerSprite 登录态由后端缓存；不要手动重复登录。
- 集成账号也由后端缓存；只有 SellerSprite 登录本身失败时，才需要后端刷新账号或登录态。
- 浏览器运行时由部署侧决定；Agent 不负责切换 Patchright / Playwright / Chrome。

## 异步状态

| `state` | 含义 | Agent 动作 |
| --- | --- | --- |
| `queued` | 任务已创建，等待后台 worker | `seller_sprite_run` 内部继续等待 |
| `running` | 后台正在执行 | `seller_sprite_run` 内部继续等待；超过 8 分钟仍未完成时返回 `job_id` |
| `succeeded` | 已完成，结果和导出可读 | 返回 `summary`、`job_id`、`row_count`、导出文件 |
| `failed` | 后台执行失败 | 报告 `error.message`，不要复用旧导出文件 |

## 回复规则

- 优先读取并复用：
  - `data.summary`
  - `data.job_id`
  - `data.row_count`
  - `data.queue_duration`
  - `data.running_duration`
  - `data.export.filename`
  - `data.export.url`
  - `data.export.path`
  - `data.export.format`
- 若 `seller_sprite_run` 响应顶层存在 `quota`，在最终自然语言回复末尾补一句：
  - `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
- `seller_sprite_scenarios`、`seller_sprite_quota_status`、`seller_sprite_job_status`、`seller_sprite_export` 不消耗额度；只有 `seller_sprite_run` 消耗次数。
- `job_status` 和 `export` 默认不重复提示额度，避免轮询阶段重复刷屏。
- 不要在最终回复里打印完整工具参数、原始 JSON、内部路径或账号信息。
- 若存在 `data.summary`，优先把它当成结果主文案，只补最少的任务信息。
- 若 `seller_sprite_run` 因运行超时才返回 `job_id`，补充说明 `queue_duration` 与 `running_duration`，让用户知道当前是排队久还是执行久。

成功模板：

```md
已按 `site` 做好了 `scenario title`，并导出为 `format`。

结果：
- `job_id`: xxx
- 返回行数: 20
- 导出文件: [filename](url-or-path)
```

补充规则：

- 第一行只保留关键条件，如站点、关键词、ASIN、月份、推荐模式。
- 优先展示文件名或链接，不要单独贴长本地路径。
- `row_count=0` 时，要明确提示用户核对站点、ASIN、关键词、类目或筛选是否过窄。
