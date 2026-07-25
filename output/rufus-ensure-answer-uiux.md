# Rufus 回答确保有结果 UIUX

日期：2026-06-22

## 范围

本需求没有 Web 前端页面。UIUX 重点是 CLI、MCP 返回和 Markdown 报告如何表达“是否有结果、重试了几次、是否入库”。

## 输出目标

- 调用方能一眼判断结果是否有效。
- 调用方能知道是否已经入库。
- 调用方能看到原问题和最终问题。
- 调用方能看到尝试次数和非敏感失败原因。
- 调用方不会看到任何敏感登录态和请求材料。

## MCP 返回设计

成功：

```json
{
  "report_path": "output/amazon-rufus/B0EXAMPLE-20260622-120000.md",
  "asin": "B0EXAMPLE",
  "country": "US",
  "question_count": 1,
  "valid_answer_count": 1,
  "attempt_count": 2,
  "result_status": "stored",
  "stored": true,
  "next_action": "已生成 Rufus 报告并完成入库，请读取 report_path 查看完整答案。"
}
```

同步阶段未拿到有效结果：

```json
{
  "report_path": "output/amazon-rufus/B0EXAMPLE-20260622-120000.md",
  "asin": "B0EXAMPLE",
  "country": "US",
  "question_count": 1,
  "valid_answer_count": 0,
  "attempt_count": 10,
  "result_status": "pending_retry",
  "stored": false,
  "next_action": "同步阶段 10 次尝试后仍未获得有效答案，已保留尝试记录；如后端补偿任务可用，将等待后台继续处理。"
}
```

## CLI 输出设计

成功：

```text
Rufus 答案报告已保存：output/amazon-rufus/B0EXAMPLE-20260622-120000.md
结果状态：stored
有效答案：1 / 1
总尝试次数：2
入库状态：已完成
```

无结果：

```text
Rufus 未获得有效答案。
结果状态：failed_no_valid_result
已尝试次数：10
失败原因：invalid_empty_content
下一步：检查问题表达、ASIN 商品页状态或稍后重试。
```

## 报告结构

建议报告顶部增加：

```text
# Rufus 取数结果

- ASIN：B0EXAMPLE
- 国家：US
- 结果状态：stored
- 是否入库：是
- 有效答案数：1 / 1
- 总尝试次数：2
```

每题结构：

```text
## 第 1 题

- 原问题：这个商品适合送礼吗？
- 最终问题：基于当前 Amazon 商品页信息，这个商品是否适合作为礼物？请说明关键原因。
- 尝试次数：2
- 验证结果：valid_text
- 入库状态：stored

### 尝试记录

| 次数 | 验证结果 | 失败原因 | AI 改写原因 |
|---|---|---|---|
| 1 | 无效 | invalid_empty_content | - |
| 2 | 有效 | - | make_question_product_specific |

### 答案

...
```

## 文案规则

- 使用“有效答案”而不是只说“答案数”。
- 使用“入库状态”而不是“上传状态”。
- AI 改写原因只展示简短业务原因，不展示完整系统提示词。
- 失败建议要可行动，但不能引导绕过 Amazon/Rufus 安全限制。

## 敏感信息隐藏规则

禁止展示：

- cookie。
- headers。
- authorization。
- cURL 原文。
- seed request。
- request body。
- storage state。
- upload payload 原文。

允许展示：

- ASIN。
- 国家。
- 原问题。
- 最终问题。
- 尝试次数。
- 非敏感失败原因。
- 最终答案。
- 报告路径。
- job id。

## 待确认

- 多题部分成功状态本次先沿用现有聚合语义；新增展示只补充每题有效性、尝试次数和入库状态。
- 是否允许报告展示 AI 改写后的最终问题。
- 如果入库失败但有有效答案，是否允许报告输出正文，状态为 `valid_not_stored`。
