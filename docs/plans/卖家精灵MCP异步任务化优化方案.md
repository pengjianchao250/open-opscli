# 卖家精灵 MCP 异步任务化优化方案

> **当前契约（2026-07-10）**：本文的背景、问题分析和方案比较作为历史诊断保留；其中早期关于按条件异步、短间隔轮询、较短总预算或仅续查单个任务的建议已被当前契约取代。当前所有普通 `seller_sprite_run` 均立即持久化入队，Agent 按下文“Agent 对话管理（当前契约）”执行。

## 历史诊断（保留）

### 背景

用户在多轮对话中确认 Bookcases 最终类目后，调用 `seller_sprite_run` 执行 `product-research`，参数中已包含精确类目路径：

```json
{
  "nodeIdPaths": ["1055398:1063306:1063312:10824421"]
}
```

该路径为纯数字类目路径，后端会直接作为精确目录使用，不再触发类目文本搜索或多候选匹配。实际超时更可能发生在 `product-research` 主查询、`browser-route` 浏览器登录/跳转/请求、导出或上传阶段。

当前 MCP 同步调用在约 120 秒后由调用方超时中断，用户无法拿到任务标识，也无法继续查询已启动任务的状态。

### 问题分析

当前 `seller_sprite_run` 是同步长任务入口，调用链包含：

1. 解析调用参数和认证信息。
2. 构造 `SellerSpriteScenarioRequest`。
3. 同步等待 `SellerSpriteApiManager.run()` 完整执行。
4. 按默认 `browser-route` 打开或复用浏览器上下文。
5. 检查登录态、跳转 referer、执行页面准备动作。
6. 发起卖家精灵接口请求。
7. 落盘 `params.json`、`raw.json`、`result.json`。
8. 生成 `json` 或 `xlsx` 导出文件。
9. 如启用文件上传，再上传导出文件。
10. 全部完成后才返回 MCP 响应。

这个模式适合短接口，不适合卖家精灵这类可能超过 120 秒的外部网页态采集任务。外层 MCP 调用超时后，即使后端仍在执行，Agent 也无法可靠获得 `job_id`。

## 目标

- 避免长耗时卖家精灵任务被 MCP 单次同步等待上限中断。
- 保留现有单账号单窗口串行执行模型，降低风控和登录态污染风险。
- 让 Agent 在同一对话中自动管理任务进度，用户不需要重新提交完整请求。
- 保留 `seller_sprite_job_status` 和 `seller_sprite_export` 作为状态查询与导出读取入口。
- 为后续多账号并发预留扩展空间，但本期不默认开启同账号多窗口。

## 非目标

- 本期不提升同账号并发吞吐。
- 本期不默认开启多个浏览器窗口。
- 本期不改变卖家精灵账号来源和登录缓存策略。
- 本期不改动 `product-research` 业务参数语义。

## 推荐方案

采用“立即持久化入队 + 单窗口串行队列 + Agent 有界单/批量跟踪”的方案。

### MCP 工具层

新增或调整以下能力：

| 工具 | 职责 |
| --- | --- |
| `seller_sprite_run` | 唯一普通采集入口；立即持久化入队并返回 `job_id/state/stage/position` |
| `seller_sprite_job_status` | 使用 `seller_sprite_job_status(job_id, wait_seconds=30)` 有界查询一个普通任务 |
| `seller_sprite_jobs_status` | 使用 `seller_sprite_jobs_status(job_ids, wait_seconds=30)` 有界批量查询多个普通任务 |
| `seller_sprite_export` | 在任务成功后读取导出文件信息 |

对 Agent 和用户隐藏 `seller_sprite_start`、`async_mode`、`browser-route`、`api-direct` 等内部控制。所有普通 `seller_sprite_run` 调用都立即持久化入队并返回任务快照，不在提交入口等待最终结果。

### 任务状态

每个任务目录中增加轻量状态文件，例如 `status.json`：

```json
{
  "job_id": "SellerSprite-ProductResearch-US-Bookcases-20260616-120000-a1b2c3",
  "scenario": "product-research",
  "state": "running",
  "stage": "browser_request",
  "created_at": "2026-06-16T12:00:00+08:00",
  "started_at": "2026-06-16T12:00:03+08:00",
  "finished_at": null,
  "error": null,
  "export": null
}
```

建议状态枚举：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已创建任务，等待 worker 执行 |
| `running` | 正在执行 |
| `succeeded` | 已完成并生成结果 |
| `failed` | 执行失败，错误信息写入状态 |
| `cancelled` | 预留，后续支持取消任务时使用 |

建议阶段枚举：

| 阶段 | 含义 |
| --- | --- |
| `created` | 任务刚创建 |
| `category` | 类目解析阶段 |
| `browser_prepare` | 浏览器登录、跳转、页面准备 |
| `browser_request` | 主接口请求 |
| `high_frequency` | 高频词附加请求 |
| `export` | 本地导出 |
| `file_upload` | 上传导出文件 |
| `finished` | 已结束 |

### 执行模型

本期保留当前单账号单窗口串行模型：

- 同一个卖家精灵账号只绑定一个 browser worker。
- 同一账号任务按队列顺序执行。
- 不在同账号下开启多个并发窗口。
- 失败后的冷却仍由 worker 控制，但状态查询应能看到 `queued` 或 `running`，而不是让 MCP 同步调用一直等待。

不建议本期直接多窗口并发，原因：

- 卖家精灵网页态接口可能有风控，多个窗口同时请求更容易触发限制。
- 多窗口共享同一个 profile/cookie 时，容易出现登录态互相影响。
- 页面 route、下载、上下文请求可能出现竞争，排查成本高。
- 本次主要问题是同步等待超时，不是吞吐不足。

后续如确实需要吞吐提升，应优先支持“多账号并发”，即一个账号一个 worker，而不是同账号多窗口。

### Agent 对话管理（当前契约）

用户不应该重新发送完整请求。Agent 必须管理本轮产生及跨轮保留的全部普通任务 `job_id`：

1. 每个普通场景只调用一次 `seller_sprite_run`；任务立即持久化入队，保存返回的 `job_id/state/stage/position`。
2. 只有一个普通 pending ID 时，调用 `seller_sprite_job_status(job_id, wait_seconds=30)`；有多个普通 pending ID 时，优先调用 `seller_sprite_jobs_status(job_ids, wait_seconds=30)`。
3. 同一轮连续执行 3–4 个 30 秒有界状态窗口，总预算 90–120 秒；全部任务进入终态时提前停止。
4. 每个窗口后完成已进入终态的任务处理，并保留全部未完成 `job_id`；下一窗口查询完整 pending 子集。`queued`、`running`、`ready=false` 或等待窗口到期都表示 pending 不是失败。
5. 预算用尽后向用户说明任务仍在后台执行，并保存完整 pending 集合。用户后续只说 `继续` / `查结果` / `刚才那些好了没` 时续查完整 pending 集合；只有用户明确指定子集时才缩小范围。
6. pending 任务不得重新提交，也不得再次调用 `seller_sprite_run` 查状态；不得重新消耗额度。`run` 消耗额度；状态和导出不消耗额度。
7. Listing Analysis 必须使用专用 submit/status/result；`seller_sprite_run` 生产入口会明确拒绝 `listing-analysis`，调用方必须改用 `seller_sprite_listing_analysis_submit`；Listing Analysis `job_id` 不得传入 `seller_sprite_jobs_status`，续查时仍使用专用 status/result。

多数对话宿主在回复结束后不会继续后台等待，因此 Agent 只在当前回复内执行上述 3–4 个有界窗口；预算结束后依靠保存的完整 pending 集合跨轮继续，不重新入队。

## 备选方案

### 方案 A：只调大超时时间

优点是改动小。

缺点是不能解决外层 MCP 客户端固定 120 秒超时的问题。即使内部超时调到 180 秒，调用方仍可能先断开，用户仍拿不到 `job_id`。

不推荐作为主方案。

### 方案 B：同账号多窗口并发

优点是可能提升吞吐。

缺点是风控风险、登录态竞争、浏览器资源占用和排错成本都明显上升。本次问题不是并发不足，因此不建议本期采用。

### 方案 C：异步任务化但不自动轮询

优点是 MCP 层简单。

缺点是用户体验差，用户需要主动说“查进度”。可以作为兜底，但不应作为默认交互方式。

## 实施建议

分三阶段推进。

### 第一阶段：异步任务骨架

- 增加任务状态文件写入能力。
- `seller_sprite_run` 对所有普通任务立即持久化入队并返回 `job_id/state/stage/position`。
- 后台仍复用现有 `SellerSpriteApiManager.run()` 执行真实采集。
- `seller_sprite_job_status` 支持读取 `status.json` 和已完成的 `result.json`。

### 第二阶段：Agent 使用规范

- 更新 `ops-seller-sprite/SKILL_MCP.md`。
- 明确普通任务立即持久化入队，提交入口不等待终态。
- 规定单任务和批量状态均使用 `wait_seconds=30`，同一轮执行 3–4 个窗口，总预算 90–120 秒。
- 规定每个窗口后完成已终态任务处理，并在预算结束后保留完整 pending 集合，用户可用自然语言继续查询。
- 明确 pending 不是失败，不得重新提交或重新消耗额度。
- 修正文档中 `export_format` 默认值不一致的问题。

### 第三阶段：稳定性增强

- 增加任务阶段和耗时统计。
- 对冷却中的任务快速返回 `queued` 和预计等待时间。
- 增加失败错误的结构化落盘，避免外层超时导致错误丢失。
- 如有吞吐需求，再评估多账号 worker 并发。

## 测试建议

- MCP 单测：所有普通 `seller_sprite_run` 均立即持久化入队并返回 `job_id`，不等待 manager 完成。
- 状态单测：`queued`、`running`、`succeeded`、`failed` 都能被单任务和批量状态工具正确读取。
- 契约单测：提交入口不隐藏轮询，单任务和批量状态调用均限制为 0–30 秒。
- 失败单测：后台任务抛异常时，`status.json` 写入 `failed` 和错误摘要。
- 文档单测：`ops-seller-sprite` Skill 中默认导出格式和调用流程与代码一致。

## 风险与约束

- Python 进程内后台任务在 MCP Server 重启后会丢失运行态；本期可先接受，后续再考虑持久化队列。
- 状态等待请求被外层取消或到期时，后台持久任务继续执行；Agent 保留 `job_id` 后续查询。
- 文件上传仍可能拖慢完成时间，应纳入后台任务阶段，不阻塞提交响应。
- 单窗口串行会牺牲吞吐，但更符合当前风控与稳定性目标。

## 推荐结论

当前采用“立即持久化入队 + 单账号单窗口串行 + Agent 有界单/批量跟踪”。

不要因为异步任务化而默认开启多窗口。多窗口并发应作为后续多账号吞吐优化能力，在限流、冷却、账号隔离和状态观测完善后再评估。
