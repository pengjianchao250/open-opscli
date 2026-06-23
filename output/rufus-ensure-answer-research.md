# Rufus 回答确保有结果 Research

日期：2026-06-22

## 需求摘要

用户要求 Rufus 的回答“一定要有结果”。具体行为是：

- 每次 Rufus 回答后必须判断是否有有效结果。
- 如果没有有效结果，将当前提示词/问题发送给 AI 优化。
- 使用优化后的提示词再次向 Rufus 提问。
- 重复该过程，直到拿到有效结果。
- 最终结果需要存入数据库。

本轮只做方案和改动点说明，不进入代码实现。

## 当前实现现状

### 主要入口

- CLI：`opscli amazon-rufus get-backend <ASIN> <COUNTRY>`
- MCP：`amazon_rufus_get`
- 核心服务：`RufusManager.get_backend()`
- Rufus 请求客户端：`HeadlessRufusClient.query()`
- Rufus 解析器：`RufusParserService.parse()`
- 报告写入：`AnswerReportWriter.write()`
- 远端上传：`RufusTransportClient.submit_upload_payload()`

当前调用链：

```text
CLI get-backend / MCP amazon_rufus_get
  -> RufusManager.get_backend()
  -> RufusBackendSecretProvider.load()
  -> 读取亚马逊 Rufus 登录态和 streaming cURL
  -> 必要时 headless 捕获 seed
  -> HeadlessRufusClient.query()
  -> RufusParserService.parse()
  -> _build_result()
  -> 写报告 / 可选 submit_upload
```

### 当前空结果行为

当前实现把“请求成功”和“业务有结果”混在一起：

- `RufusParserService.parse()` 会返回 `AnswerData`，其中 `is_success=bool(text or html_text)`。
- `RufusMcpManager.get()` 使用 `len(answers)` 计算 `answer_count`，不判断答案是否真的可用。
- `AnswerReportFormatter` 遇到空答案时会输出“未获取到答案”。
- 当前 Skill 文档明确写着：成功但 `answer_count=0` 时按正常 0 答案报告处理。

因此，新需求不是小修补，而是要改变成功语义：只有“业务有效答案”才算成功。

### 当前入库能力

已有远端接口：

- 常量：`RUFUS_UPLOAD_ENDPOINT = "/v1/rufus/upload"`
- 方法：`RufusTransportClient.submit_upload_payload(upload_payload)`
- CLI 参数：`--submit-upload`

但当前 payload 更偏“请求采集 payload”，并不一定是最终 Rufus 回答结果入库结构。新需求需要确认后端数据库接口到底是扩展现有 `/v1/rufus/upload`，还是新增结果入库接口。

## 外部依据

- Amazon 官方说明 Rufus 是生成式 AI 购物助手，核心场景是商品问答、比较、总结和推荐。因此这里的“有结果”应按可用于商品分析的业务内容判断，而不是只看 HTTP 请求成功。参考：About Amazon 对 Rufus 的官方介绍。
- AWS 对远程调用重试的最佳实践强调有边界的重试、退避和 jitter，避免无限同步重试造成服务放大故障。参考：AWS Architecture Blog 关于 Exponential Backoff and Jitter 的文章。
- Amazon Bedrock prompt engineering 文档强调 prompt 需要清晰、带上下文、约束输出格式。AI 优化提示词应该输出结构化改写结果，而不是自由发挥。

## 关键冲突

### 冲突 1：现有允许空答案，新需求不允许

现状：`answer_count=0` 或空文本可以作为正常报告结束。

新需求：无有效结果必须触发 AI 改写重试。

影响：需要更新 Skill、MCP 返回、报告和测试对空答案的预期。

### 冲突 2：“一直到有结果”不能直接做成同步无限循环

如果同步无限重试，会产生：

- MCP/CLI 调用长时间挂起。
- Amazon/Rufus 风控风险。
- AI 调用成本不可控。
- 无法提供稳定 SLA。
- 失败时没有清晰状态。

推荐定义：

- 同步阶段最大尝试次数支持配置到 10 次；本需求确认按最多 10 次设计。
- 如果同步阶段没有结果，可以保存任务为 `pending_retry`，由后台 job 继续重试；后台补偿是后端异步任务能力，不是本次 CLI/MCP 同步链路的硬前置。
- 对外不返回“成功但无结果”；只返回 `stored`、`pending_retry` 或失败状态。

### 冲突 3：AI 服务来源

本需求确认 AI 优化服务走 OPS 内部 AI 网关。当前项目依赖只有 `httpx`，没有内置 OpenAI 或其他模型 SDK。因此应先设计抽象接口：

- 默认接 OPS 内部 AI 网关或由 ops 后端封装的 prompt optimize API。
- 代码侧保持 provider 抽象，避免把模型 SDK 直接耦合进 Rufus 请求链路。

核心要求：不要把 Rufus 登录态、cookie、headers、seed、payload、cURL 发给 AI。

## 研究结论

推荐将能力拆成四层：

- 结果验证层：判断 Rufus answer 是否是有效业务结果。
- Prompt 优化层：无结果时请求 AI 改写问题。
- 重试编排层：控制 ask -> validate -> optimize -> retry。
- 结果持久化层：将最终有效结果和尝试过程写入数据库。

这些逻辑不应放进 `HeadlessRufusClient.query()`，因为它当前职责是底层请求和解析。更合理的位置是 `RufusManager` 上层或旁路新增 `RufusEnsureAnswerService`。

## 已确认和待确认

- 已确认：同步最多重试 10 次，不做灰度，默认启用确保有结果逻辑。
- 已确认：AI prompt 优化服务走 OPS 内部 AI 网关。
- 已确认：多题部分成功状态不作为本次需求重点变更，沿用现有聚合语义；新增字段只补充每题有效性和尝试记录。
- 待确认：数据库入库接口是现有 `/v1/rufus/upload` 扩展，还是新增 `/v1/rufus/results`。
- 待确认：后台持续补偿是否需要后端提供异步任务和任务状态查询；若本期不做，则同步 10 次后返回 `failed_no_valid_result`。
