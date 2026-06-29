# Rufus 回答确保有结果 Architecture

日期：2026-06-22

## 当前链路定位

当前核心链路：

```text
opscli amazon-rufus get-backend / amazon_rufus_get
  -> RufusManager.get_backend()
  -> RufusBackendSecretProvider.load()
  -> HeadlessRufusCaptureService.capture_seed_request()
  -> HeadlessRufusClient.query()
  -> RufusParserService.parse()
  -> RufusManager._build_result()
  -> AnswerReportWriter.write()
  -> 可选 RufusTransportClient.submit_upload_payload()
```

问题在于：这条链路只验证“请求和解析是否完成”，没有验证“回答是否有业务有效结果”。

## 推荐架构

新增一层 `ensure answer` 编排，不直接改造底层请求职责：

```text
CLI / MCP
  -> RufusEnsureAnswerService
    -> RufusManager 凭证和 seed 准备能力
    -> HeadlessRufusClient 单题请求能力
    -> RufusAnswerValidator
    -> RufusPromptOptimizer
    -> RufusResultPersistenceClient
  -> AnswerReportWriter
  -> MCP safe response
```

## 新增模块建议

### `opscli/amazon_rufus/services/answer_validator.py`

职责：

- 判断 `AnswerData` 是否有效。
- 输出失败原因。
- 只保留非敏感 evidence。

核心接口：

```python
class RufusAnswerValidator:
    def validate(self, answer: AnswerData | None, *, question: str) -> RufusValidationResult:
        ...
```

### `opscli/amazon_rufus/services/prompt_optimizer.py`

职责：

- 定义 AI prompt 优化抽象。
- 封装 OPS 内部 AI 网关调用。
- 提供本地模板兜底。

核心接口：

```python
class RufusPromptOptimizer:
    def optimize(self, request: RufusPromptOptimizeRequest) -> RufusPromptOptimizeResult:
        ...
```

### `opscli/amazon_rufus/services/ensure_answer.py`

职责：

- 对每个问题执行 ask -> validate -> optimize -> retry。
- 聚合多题状态。
- 控制最大尝试次数。
- 生成报告和入库 payload 所需的数据结构。

核心接口：

```python
class RufusEnsureAnswerService:
    def get_with_ensure_result(self, request: RufusEnsureAnswerRequest) -> RufusEnsureAnswerResult:
        ...
```

### `opscli/amazon_rufus/services/result_persistence.py`

职责：

- 将最终有效结果提交后端入库。
- 与现有 `upload_payload` 分离，避免语义混淆。

核心接口：

```python
class RufusResultPersistenceClient:
    def submit_result(self, payload: dict) -> dict:
        ...
```

### `opscli/amazon_rufus/domain/ensure_answer_models.py`

职责：

- 定义 policy、validation、attempt、question result、job result。

建议模型：

```python
@dataclass(frozen=True)
class RufusEnsureAnswerPolicy:
    enabled: bool = True
    max_answer_attempts: int = 10
    ai_optimize: bool = True
    submit_result: bool = True
    min_text_chars: int = 20
```

```python
@dataclass(frozen=True)
class RufusValidationResult:
    valid: bool
    reason: str
    evidence: dict[str, Any]
```

```python
@dataclass(frozen=True)
class RufusAnswerAttempt:
    attempt_index: int
    original_question: str
    submitted_question: str
    answer: AnswerData | None
    validation: RufusValidationResult
    optimizer_reason: str | None = None
    optimizer_provider: str | None = None
```

## 需要修改的现有文件

### `opscli/amazon_rufus/services/manager.py`

改动点：

- 保留 `get_backend()` 旧链路。
- 抽出或新增“准备 Rufus 请求上下文”的内部方法，供 ensure service 复用。
- 可选新增单题请求方法，便于每次 attempt 后插入验证。

建议不要把 AI 重试逻辑直接写进 `_build_result()`。

### `opscli/amazon_rufus/services/headless_client.py`

改动点：

- 新增 `query_one()` 或拆出内部单题请求逻辑。
- 让 ensure service 可以逐题、逐 attempt 控制。
- 保持现有 `query()` 兼容旧调用。

### `opscli/amazon_rufus/services/parser.py`

改动点：

- 可保留现有解析。
- 有效性判断不要塞进 parser。
- 如果拒答模式需要更精确，可增加轻量字段或交给 validator 处理。

### `opscli/amazon_rufus/transport/client.py`

改动点：

- 新增 `submit_result_payload()`。
- 如果复用现有 `/v1/rufus/upload`，需要明确 schemaVersion。
- 如果新增接口，建议 `/v1/rufus/results` 或 `/v1/rufus/result-jobs`。

### `opscli/amazon_rufus/commands/cli.py`

改动点：

- `get-backend` 增加 ensure 参数。
- 或新增 `get-ensure`，避免破坏旧命令。

建议参数：

```text
--ensure-result/--allow-empty-result
--max-answer-attempts
--ai-optimize/--no-ai-optimize
--submit-result/--no-submit-result
```

### `opscli/amazon_rufus/domain/mcp_models.py`

改动点：

- `RufusGetRequest` 增加安全字段：

```python
ensure_result: bool = True
max_answer_attempts: int = 10
ai_optimize: bool = True
```

### `opscli/amazon_rufus/services/mcp_manager.py`

改动点：

- `get()` 根据 `ensure_result` 选择旧链路或 ensure 链路。
- 返回 `valid_answer_count`、`attempt_count`、`result_status`、`stored`。
- 继续禁止敏感字段穿透。

### `opscli/mcp/tools/amazon_rufus.py`

改动点：

- `amazon_rufus_get` 增加安全参数。
- 错误反馈继续只记录脱敏参数。

### `opscli/amazon_rufus/services/answer_report_formatter.py`

改动点：

- 报告顶部增加结果状态。
- 每题显示原问题、最终问题、尝试次数、失败原因、AI 改写原因。

### `opscli/skills/templates/ops-amazon-rufus/SKILL.md`

改动点：

- 修改“`answer_count=0` 正常处理”的旧规则。
- 新增“无有效结果触发 AI 改写重试”的规则。
- 明确 AI 优化不得接收敏感登录态。

## 数据库接口方案

### 方案 A：扩展 `/v1/rufus/upload`

优点：

- 已有客户端和认证链路。
- 改动较少。

缺点：

- 现有 payload 语义偏采集请求，不适合最终答案。
- 容易把 seed/requestBody 和结果混在一起。

适用：后端确认该接口就是 Rufus 入库主接口。

### 方案 B：新增 `/v1/rufus/results`

优点：

- 语义清晰。
- 能更好表达最终答案、attempt 和状态机。
- 敏感字段白名单更容易控制。

缺点：

- 后端需要新增 API 和表结构。

推荐：采用方案 B；当前仍待后端确认。短期如果后端暂不新增接口，可以用方案 A 加 `schemaVersion=2` 过渡，但代码中仍应通过 `RufusResultPersistenceClient` 隔离接口差异。

### 后台补偿边界

后台持续补偿指后端创建异步 job，在 CLI/MCP 同步调用结束后继续重试无有效结果的问题，并把最终状态写入数据库或任务状态表。

本次确定改造范围：

- 同步链路最多尝试 10 次。
- 10 次内成功则立即入库并返回 `stored`。
- 10 次后仍失败时，如果后端已提供 job 接口，返回 `pending_retry`；如果没有，则返回 `failed_no_valid_result`。
- 后台 job 的调度、队列、状态查询 API 不在本次 CLI/MCP 代码改造中强行实现，除非后端接口同时确认。

## 推荐入库 payload

```json
{
  "schemaVersion": 1,
  "source": "opscli-amazon-rufus",
  "asin": "B0EXAMPLE",
  "country": "US",
  "status": "stored",
  "questions": [
    {
      "originalQuestion": "这个商品适合送礼吗？",
      "finalQuestion": "基于当前 Amazon 商品页信息，这个商品是否适合作为礼物？请说明关键原因。",
      "status": "valid",
      "attemptCount": 2,
      "attempts": [
        {
          "attemptIndex": 1,
          "submittedQuestion": "这个商品适合送礼吗？",
          "valid": false,
          "failureReason": "invalid_empty_content",
          "optimizerReason": null
        },
        {
          "attemptIndex": 2,
          "submittedQuestion": "基于当前 Amazon 商品页信息，这个商品是否适合作为礼物？请说明关键原因。",
          "valid": true,
          "failureReason": null,
          "optimizerReason": "make_question_product_specific"
        }
      ],
      "answer": {
        "text": "...",
        "summaryText": "...",
        "blocks": [],
        "recommendedAsins": [],
        "productLinks": [],
        "threadId": "..."
      }
    }
  ],
  "reportPath": "output/amazon-rufus/..."
}
```

不包含 cookie、headers、seed、payload、cURL、storage state。

## 测试策略

新增：

- `tests/amazon_rufus/test_answer_validator.py`
- `tests/amazon_rufus/test_prompt_optimizer.py`
- `tests/amazon_rufus/test_ensure_answer.py`
- `tests/amazon_rufus/test_result_persistence.py`

修改：

- `tests/amazon_rufus/test_core.py`
- `tests/amazon_rufus/test_mcp_manager.py`
- `tests/mcp/test_amazon_rufus_tools.py`
- `tests/skills/test_ops_amazon_rufus_updater.py`

覆盖场景：

- 首次有效答案。
- 首次空答案，AI 改写后成功。
- 多次仍无结果，进入 `pending_retry` 或 `failed_no_valid_result`。
- 多题部分成功。
- AI 请求不包含敏感字段。
- MCP 响应不包含敏感字段。
- 入库失败不返回 `stored=true`。

## 落地顺序

1. 新增 validator 和测试。
2. 新增 prompt optimizer 抽象和 mock/fallback 测试。
3. 新增 ensure answer service 和单题重试编排测试。
4. 接入 CLI 参数。
5. 接入 MCP 参数和脱敏响应。
6. 接入结果入库接口。
7. 更新报告格式。
8. 更新 Skill 文档和测试。
9. 真实链路验证。
