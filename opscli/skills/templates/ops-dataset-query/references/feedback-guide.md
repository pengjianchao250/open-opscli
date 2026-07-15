---
name: ops-dataset-query-feedback
description: 仅对意外工具失败提交的 ops-feedback 规范
---

# 意外失败反馈

成功查询不自动提交反馈。仅当正式 opscli 命令或 MCP Tool 出现**意外失败**（抛出异常、`success: false`、超时或无法解释的服务错误）时，在同一请求中立即提交一次 `bug` 反馈。

## 不触发的情况

- 预期的认证未就绪、用户取消、需要澄清、查询返回 0 行，均不是反馈事件本身。
- 查询结果不符合业务预期但工具执行成功时，先澄清或移交 `ops-query-wizard`；不要把成功查询自动报为故障。
- `feedback_submit` 或 `opscli feedback submit` 本身失败时记录失败并停止，不再递归提交。

## 去重与内容

同一失败在 **30 分钟** 内只提交一次。以工具名、关键 `call_params`、错误码和错误文本判断相同；保留已提交的 `feedback_uuid` 供本次请求后续步骤引用。

提交前读取 `ops-feedback` Skill，并在 `execution_summary` 中至少提供：

```json
{
  "tool": "query_simple 或具体 opscli 命令",
  "call_params": {"仅保留关键参数": "不含凭据"},
  "error_message": "原始错误码和文本",
  "reason": "原因；不确定时标注推测",
  "fix_suggestion": "已采取的修复或下一步"
}
```

MCP 使用 `feedback_submit`，CLI 使用 `opscli feedback submit`。反馈提交成功后向用户返回 `feedback_uuid`，再继续原任务；不得上传账号凭据、绝对路径、缓存内容或无关结果数据。
