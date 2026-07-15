---
name: ops-feedback
cli-version: v1.0.0
description: 通过 opscli feedback 提交和查询结构化用户反馈
---

# ops-feedback CLI

## 分级反馈策略

- 失败即时反馈：`opscli` CLI 非 0、MCP `success=false`、异常和远端错误码必须立即提交 `bug`。
- 成功默认本地任务摘要：成功查询、成功引导和批量评估正常样本只写入本地执行总结或项目结果文件。
- 远端成功反馈默认关闭：只有用户明确要求、发布/审计门禁或 L2 可疑结果需要 owner 处理时，才提交 `query_result`。
- 抽样：无异常成功样本默认只进入本地评估集或回归候选；用户要求完整审计时才远端提交。
- 去重：同一失败指纹 30 分钟内只提交 1 次，复用已有 `feedback_uuid`。去重是滑动窗口：窗口内重复失败只刷新本地 occurrence_count，不会自动再次远端提交。
- 批量失败聚合：批量烟测、回归和多数据集扫描中的同根因 L3 失败在事件 JSON 中传 `feedback_group_key`，首条失败远端提交，后续同组失败复用已有 `feedback_uuid`；显式 group key 会覆盖变化的完整命令字符串和参数。
- guard 状态恢复：本地状态损坏时按空状态继续；重复失败记录缺少 `feedback_uuid` 时重新提交，不复用空 UUID。
- 事件瘦身与敏感字段脱敏：guard 生成 fingerprint 的副本会脱敏 token/cookie/authorization/password/secret，并把大日志、大数组和大字典压到 4096 bytes 以内。
- fail-open：`opscli feedback submit` 自身失败时只报告该失败，不递归提交，不阻塞原任务。
- L3 新失败的 guard 决策为 `submit_remote=true`、`non_blocking=true`：仍要立即提交或复用反馈 UUID，但提交动作完成后继续原任务恢复或降级处理。

## 提交前守门

推荐先用本 Skill 内置 guard 生成决策，再决定是否调用 `opscli feedback submit`。事件 JSON 应带 `session_id` / `thread_id` / `task_id`，用于把 L2 非失败反馈预算限制在当前任务内；批量同根因 L3 失败应带 `feedback_group_key`，用于 issue grouping 式去重：

```bash
python3 scripts/feedback_guard.py decide --event-file event.json
```

返回 `submit_remote: true` 时才提交远端反馈；提交成功后记录 UUID：

```bash
python3 scripts/feedback_guard.py record --event-file event.json --feedback-uuid <feedback_uuid>
```

返回 `agent_action: reuse_existing_feedback_uuid` 时复用已有 `feedback_uuid`，不要重复提交。返回 `agent_action: fail_open_no_recursive_feedback` 时只报告反馈通道失败，继续原任务。L3 决策会返回 `event_hygiene.fingerprint_payload_bytes`、`sensitive_key_count` 和 `oversized_value_count`，用于确认低 token 快速路径没有携带大日志或敏感值。

`decide` 返回 `budget_scope` 时，该值表示当前非失败预算桶；同一 `budget_scope` 默认最多提交 1 条 L2 远端反馈。

## 提交反馈

推荐使用文件方式，避免命令行 JSON 过长：

```bash
opscli feedback submit --file feedback.json --pretty
```

`feedback.json` 必须遵循接口字段结构：`skill_name`、`skill_version`、`command_name`、`mcp_tool_name` 是顶层字段，不能只写在 `context` 里。`app_version` 和 `client_version` 不要写入文件，当前 `aukeys-opscli` 会自动填入真实版本。

完整 `feedback.json` 示例：

```json
{
  "source": "cli",
  "feedback_type": "bug",
  "severity": "medium",
  "title": "ops-dataset-query simple 字段不存在",
  "content": "使用 simple 查询时字段 original_price 无法识别，已改用 build 完成。",
  "payload": {
    "expected": "返回原价汇总",
    "actual": "字段不存在"
  },
  "skill_name": "ops-dataset-query",
  "skill_version": "v1.0.0",
  "command_name": "opscli query simple",
  "context": {
    "cwd": "/Users/mask/python3/opscli",
    "agent": "Codex",
    "workflow": "ops-dataset-query"
  },
  "execution_summary": {
    "summary": "本次通过 ops-dataset-query 查询数据，simple 接口因字段识别失败，最终改用 build。",
    "failed_calls": [
      {
        "tool": "Bash → opscli query simple --table-id 1 --json '...' --run --pretty",
        "call_params": {
          "table_id": 1,
          "metrics": [
            {
              "field": "original_price",
              "aggregation": "SUM",
              "alias": "f_original_price"
            }
          ]
        },
        "error_message": "REMOTE_BUSINESS_ERROR: 字段不存在: original_price",
        "reason": "简化接口的 field 参数传了 field_name，但服务端未能识别；metadata 中该字段完整 origin_name 是 ds_d35ac6f3910c.original_price。",
        "fix_suggestion": "改用 opscli query build 的 --dimension/--metric 参数形式，由 CLI 自动完成字段映射。"
      }
    ],
    "successful_calls": [],
    "final_resolution": "已通过 build 查询完成任务。"
  },
  "attachments": []
}
```

也可以拆分提交：

```bash
opscli feedback submit \
  --type bug \
  --severity medium \
  --title "ops-dataset-query simple 字段不存在" \
  --content "使用 simple 查询时字段 original_price 无法识别，已改用 build 完成。" \
  --execution-summary-file summary.json \
  --skill-name ops-dataset-query \
  --skill-version v1.0.0 \
  --command-name "opscli query simple" \
  --pretty
```

如果失败来自 MCP Tool，但当前选择 CLI 通道提交反馈，也要通过 `--mcp-tool-name` 传入实际工具名：

```bash
opscli feedback submit \
  --type bug \
  --severity medium \
  --source mcp \
  --title "query_simple 字段不存在" \
  --content "调用 query_simple 时服务端返回字段不存在错误。" \
  --execution-summary-file summary.json \
  --skill-name ops-dataset-query \
  --skill-version v1.0.0 \
  --mcp-tool-name query_simple \
  --pretty
```

## 查询反馈详情

```bash
opscli feedback detail --uuid <feedback_uuid> --pretty
```

## 查看 Schema

```bash
opscli feedback schema --pretty
```

## 注意事项

- 提交前先确认已经完成 `opscli auth login`
- Skill 相关反馈必须传 `--skill-name` 和 `--skill-version`
- CLI 失败必须传 `--command-name`；MCP 失败必须传 `--mcp-tool-name`
- 成功默认本地任务摘要，远端成功反馈默认关闭；不要为同一用户任务中的每次成功 query_simple 都提交一条反馈
- 不要手工传 `app_version`、`client_version`；由当前 `aukeys-opscli` 自动写入
- `execution_summary.failed_calls[*].call_params` 必须保留具体字段和值
- 不要提交 Token、Cookie、密码等敏感信息
