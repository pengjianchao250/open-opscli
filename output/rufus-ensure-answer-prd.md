# Rufus 回答确保有结果 PRD

日期：2026-06-22

## 目标

将 Rufus 回答链路从“请求成功即成功”升级为“有业务有效结果才成功”。当 Rufus 无有效结果时，自动调用 OPS 内部 AI 网关优化提示词，并使用优化后的问题再次向 Rufus 提问，同步链路最多尝试 10 次。最终有效结果必须写入数据库；如果 10 次后仍无结果，则返回明确失败或进入后端异步补偿状态，不能返回成功空结果。

## 成功定义

一个问题的取数成功必须同时满足：

- Rufus 请求完成并返回可解析 answer。
- answer 通过有效性验证。
- 最终有效答案已写入数据库，或明确返回 `valid_not_stored` 说明入库未启用/失败。

不再允许以下状态伪装成成功：

- `answer_count=0`
- answer 只有 `threadId`
- `isSuccess=false` 且无可展示内容
- 报告里只有“未获取到答案”

## 用户故事

### US-1 单题首次成功

作为运营 Agent，我提交 ASIN 和一个问题，希望 Rufus 返回有效答案并自动入库，这样后续诊断流程可以直接读取结果。

验收：

- `attempt_count=1`
- `valid_answer_count=1`
- `result_status=stored`
- 报告包含最终答案
- 数据库有对应结果

### US-2 首次无结果后 AI 改写成功

作为运营 Agent，当 Rufus 首次没有回答时，我希望系统自动优化问题并重试，而不是给我一份空报告。

验收：

- 第一次 attempt 记录失败原因
- 调用 AI prompt optimizer
- 第二次或后续 attempt 使用优化后的问题
- 成功后报告展示原问题、最终问题、改写原因和尝试次数
- 最终结果入库

### US-3 多题默认题库

作为运营 Agent，我使用默认题库，希望每个问题都独立判断是否有结果。

验收：

- 每个原问题都有独立 attempt 列表
- 每题都能看到最终状态
- 总状态能表达全部成功、部分成功或待补偿

### US-4 同步阶段仍无结果

作为调用方，我不希望同步接口无限卡住，也不希望收到成功空结果。

验收：

- 达到同步最大尝试次数 10 次后，不返回成功空报告
- 如果后端确认提供后台补偿任务，则状态为 `pending_retry`
- 如果本期没有后台任务，则状态为 `failed_no_valid_result`
- attempt 记录保留，便于排障和人工复核

## 功能需求

### FR-1 有效结果验证

系统必须新增结果验证器，对每个 `AnswerData` 判断是否有效。

有效结果规则：

- `text` 去空白后达到最小长度。
- 或 `summaryText` 去空白后达到最小长度。
- 或 `html` 转纯文本后达到最小长度。
- 或 `blocks` 中有可渲染文本、列表、表格等内容。
- 或问题属于推荐/对比类，且 `recommendedAsins` 或 `productLinks` 有有效项。

无效结果规则：

- 没有 answer。
- answer 全部展示字段为空。
- `isSuccess=false` 且没有任何内容。
- 只有 `threadId`。
- 命中明显拒答、无法回答、信息不足表达，且没有其他可用内容。

### FR-2 AI 优化提示词

当验证失败时，系统调用 OPS 内部 AI 网关优化当前问题。

AI 输入允许包含：

- ASIN。
- 国家站点。
- 原始问题。
- 当前提交问题。
- attempt 序号。
- 验证失败原因。
- 上次 answer 的非敏感摘要，例如文本长度、blocks 数量、推荐项数量。

AI 输入禁止包含：

- cookie。
- headers。
- authorization。
- cURL 原文。
- seed request。
- request body。
- storage state。
- upload payload。

AI 输出必须包含：

- `optimized_question`
- `rewrite_reason`
- `preserved_intent`

### FR-3 重试策略

系统在无效结果时必须重试。

推荐默认：

- 同步最大尝试次数：10。
- 可配置上限：10。
- 每次 Rufus 请求仍使用当前 `timeout_seconds`。
- 尝试间隔加入短延迟和 jitter。
- AI 优化失败时，可以使用本地模板兜底改写一次，但要标记来源。

不建议同步无限循环。若业务需要严格意义上的“一直到有结果”，推荐由后端后台 job 继续补偿；后台补偿指异步任务在同步调用结束后继续按策略重试，并把最终状态写入数据库或任务状态表。本次 CLI/MCP 改造以同步最多 10 次为确定范围，后台补偿依赖后端是否确认提供。

### FR-4 入库

最终有效结果必须写入数据库。

最小字段：

- ASIN。
- 国家。
- 原始问题。
- 最终问题。
- 最终答案。
- 尝试次数。
- 每次尝试的问题、验证结果、失败原因。
- AI 改写原因。
- Rufus `threadId`。
- 报告路径。
- 状态和时间戳。

状态建议：

- `stored`
- `valid_not_stored`
- `retrying`
- `pending_retry`
- `failed_no_valid_result`
- `failed_remote_error`

### FR-5 CLI 行为

建议新增参数：

- `--ensure-result/--allow-empty-result`
- `--max-answer-attempts <N>`
- `--ai-optimize/--no-ai-optimize`
- `--submit-result/--no-submit-result`

本需求不做灰度，默认启用 `ensure_result=true`。CLI 可保留 `--allow-empty-result` 作为显式兼容逃生开关，但默认行为必须执行有效结果验证、AI 改写重试和入库。

### FR-6 MCP 行为

MCP `amazon_rufus_get` 建议支持：

- `ensure_result`
- `max_answer_attempts`
- `ai_optimize`

MCP 响应只能返回脱敏摘要：

- `report_path`
- `asin`
- `country`
- `question_count`
- `valid_answer_count`
- `attempt_count`
- `result_status`
- `stored`
- `next_action`

### FR-7 报告行为

报告需要新增：

- 结果状态。
- 是否已入库。
- 有效答案数。
- 总尝试次数。
- 每题原问题。
- 每题最终问题。
- 每次失败原因和 AI 改写原因。

报告不得展示敏感请求材料。

## 非功能需求

### 安全

- AI 优化不能接触敏感登录态或请求材料。
- MCP 响应继续保持 denylist 防护。
- feedback 和日志只记录脱敏摘要。

### 可观测性

需要能追踪：

- job id。
- attempt id。
- result_status。
- validator reason。
- optimizer provider。
- persistence result。
- 总耗时。

### 稳定性

- 远端 401、403、登录态失效仍走现有登录恢复逻辑。
- 不要把所有失败都归因为 prompt 不好。
- 多题场景避免无限串行拖垮调用。

## 验收标准

- 首次有效答案会直接入库并返回 `stored`。
- 首次空答案会触发 AI 改写和再次提问。
- AI 改写后成功时，报告能看到改写链路。
- 达到同步最大次数 10 次仍失败时，不返回成功空报告。
- MCP 输出不包含敏感字段。
- AI 请求不包含敏感字段。
- 入库失败时不允许返回 `stored=true`。
