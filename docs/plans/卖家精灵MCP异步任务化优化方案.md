# 卖家精灵 MCP 异步任务化优化方案

## 背景

用户在多轮对话中确认 Bookcases 最终类目后，调用 `seller_sprite_run` 执行 `product-research`，参数中已包含精确类目路径：

```json
{
  "nodeIdPaths": ["1055398:1063306:1063312:10824421"]
}
```

该路径为纯数字类目路径，后端会直接作为精确目录使用，不再触发类目文本搜索或多候选匹配。实际超时更可能发生在 `product-research` 主查询、`browser-route` 浏览器登录/跳转/请求、导出或上传阶段。

当前 MCP 同步调用在约 120 秒后由调用方超时中断，用户无法拿到任务标识，也无法继续查询已启动任务的状态。

## 问题分析

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

采用“异步任务化 + 单窗口串行队列 + Agent 自动轮询”的方案。

### MCP 工具层

新增或调整以下能力：

| 工具 | 职责 |
| --- | --- |
| `seller_sprite_run` | 唯一采集入口；内部自动决定同步或异步 |
| `seller_sprite_job_status` | 查询任务状态，返回 `queued`、`running`、`succeeded`、`failed` |
| `seller_sprite_export` | 在任务成功后读取导出文件信息 |

对 Agent 和用户隐藏 `seller_sprite_start`、`async_mode`、`browser-route`、`api-direct` 等内部控制。`seller_sprite_run` 根据长任务场景、浏览器队列状态和服务端配置自动返回同步结果或异步 `job_id`。

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

### Agent 对话管理

用户不应该重新发送完整请求。推荐由 Agent 在同一对话中自动管理 `job_id`：

1. Agent 调用 `seller_sprite_run`。
2. 如果后端判断需要异步，MCP 立即返回 `job_id`、`state=queued` 或 `running`。
3. Agent 在同一轮对话内自动轮询 `seller_sprite_job_status(job_id)`，建议每 5 到 10 秒一次。
4. 如果 60 到 90 秒内完成，Agent 直接回复结果和导出文件。
5. 如果仍未完成，Agent 回复任务仍在运行，并给出 `job_id`。
6. 用户后续说“继续”“查结果”“刚才那个好了没”时，Agent 复用对话上下文中的 `job_id` 查询状态。

需要注意：多数对话宿主在回复结束后不会继续后台自动轮询。因此“对话框自管理”应理解为 Agent 在当前回复完成前自动轮询一段时间；超过预算后，必须把 `job_id` 暴露给用户和上下文，供后续继续查。

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
- `seller_sprite_run` 内部判断长任务或浏览器队列忙时自动入队并立即返回 `job_id`。
- 后台仍复用现有 `SellerSpriteApiManager.run()` 执行真实采集。
- `seller_sprite_job_status` 支持读取 `status.json` 和已完成的 `result.json`。

### 第二阶段：Agent 使用规范

- 更新 `ops-seller-sprite/SKILL_MCP.md`。
- 标明长任务优先使用异步模式。
- 规定 Agent 默认自动轮询 60 到 90 秒。
- 规定超出轮询预算后保留 `job_id`，用户可用自然语言继续查询。
- 修正文档中 `export_format` 默认值不一致的问题。

### 第三阶段：稳定性增强

- 增加任务阶段和耗时统计。
- 对冷却中的任务快速返回 `queued` 和预计等待时间。
- 增加失败错误的结构化落盘，避免外层超时导致错误丢失。
- 如有吞吐需求，再评估多账号 worker 并发。

## 测试建议

- MCP 单测：`seller_sprite_run` 在长任务或浏览器队列忙时能快速返回 `job_id`，不等待 manager 完成。
- 状态单测：`queued`、`running`、`succeeded`、`failed` 都能被 `job_status` 正确读取。
- 兼容单测：旧 `seller_sprite_run` 默认行为不变，或按设计明确切换。
- 失败单测：后台任务抛异常时，`status.json` 写入 `failed` 和错误摘要。
- 文档单测：`ops-seller-sprite` Skill 中默认导出格式和调用流程与代码一致。

## 风险与约束

- Python 进程内后台任务在 MCP Server 重启后会丢失运行态；本期可先接受，后续再考虑持久化队列。
- 如果任务已被外层取消，后台是否继续执行需要明确策略。推荐异步模式下继续执行，用户可用 `job_id` 查询。
- 文件上传仍可能拖慢完成时间，建议异步模式下把上传也纳入任务阶段，而不是阻塞启动响应。
- 单窗口串行会牺牲吞吐，但更符合当前风控与稳定性目标。

## 推荐结论

本期采用“异步任务化 + 单账号单窗口串行 + Agent 自动轮询”。

不要因为异步任务化而默认开启多窗口。多窗口并发应作为后续多账号吞吐优化能力，在限流、冷却、账号隔离和状态观测完善后再评估。
