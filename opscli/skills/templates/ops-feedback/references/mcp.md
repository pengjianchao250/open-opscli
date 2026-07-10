---
name: ops-feedback
mcp-version: v1.0.0
description: 通过 MCP Tool 提交和查询结构化用户反馈
---

# ops-feedback MCP

## 分级反馈策略

- 失败即时反馈：MCP Tool `success=false`、抛异常、远端错误码必须立即提交 `bug`。
- 成功默认本地任务摘要：成功查询、成功引导和批量评估正常样本只写入本地执行总结或项目结果文件。
- 远端成功反馈默认关闭：只有用户明确要求、发布/审计门禁或 L2 可疑结果需要 owner 处理时，才提交 `query_result`。
- 抽样：无异常成功样本默认只进入本地评估集或回归候选；用户要求完整审计时才远端提交。
- 去重：同一失败指纹 30 分钟内只提交 1 次，复用已有 `feedback_uuid`。去重是滑动窗口：窗口内重复失败只刷新本地 occurrence_count，不会自动再次远端提交。
- 批量失败聚合：批量烟测、回归和多数据集扫描中的同根因 L3 失败在事件 JSON 中传 `feedback_group_key`，首条失败远端提交，后续同组失败复用已有 `feedback_uuid`；显式 group key 会覆盖变化的完整命令字符串和参数。
- guard 状态恢复：本地状态损坏时按空状态继续；重复失败记录缺少 `feedback_uuid` 时重新提交，不复用空 UUID。
- 事件瘦身与敏感字段脱敏：guard 生成 fingerprint 的副本会脱敏 token/cookie/authorization/password/secret，并把大日志、大数组和大字典压到 4096 bytes 以内。
- fail-open：`feedback_submit` 自身失败时只报告该失败，不递归提交，不阻塞原任务。
- L3 新失败的 guard 决策为 `submit_remote=true`、`non_blocking=true`：仍要立即提交或复用反馈 UUID，但提交动作完成后继续原任务恢复或降级处理。

## 提交前守门

在调用 `feedback_submit` 前，优先把失败或可疑事件写成小 JSON，并运行。事件 JSON 应带 `session_id` / `thread_id` / `task_id`，用于把 L2 非失败反馈预算限制在当前任务内；批量同根因 L3 失败应带 `feedback_group_key`，用于 issue grouping 式去重：

```bash
python3 scripts/feedback_guard.py decide --event-file event.json
```

返回 `submit_remote: true` 时才调用 `feedback_submit`。提交成功后运行：

```bash
python3 scripts/feedback_guard.py record --event-file event.json --feedback-uuid <feedback_uuid>
```

返回 `agent_action: reuse_existing_feedback_uuid` 时复用已有 `feedback_uuid`，不要重复调用 `feedback_submit`。返回 `agent_action: fail_open_no_recursive_feedback` 时只报告反馈通道失败，不递归提交。L3 决策会返回 `event_hygiene.fingerprint_payload_bytes`、`sensitive_key_count` 和 `oversized_value_count`，用于确认低 token 快速路径没有携带大日志或敏感值。

`decide` 返回 `budget_scope` 时，该值表示当前非失败预算桶；同一 `budget_scope` 默认最多提交 1 条 L2 远端反馈。

## 自动触发（Agent 工具调用失败后）

当 AI Agent 调用 MCP Tool 失败后，**必须**自动提交反馈。

### 触发流程

1. 检查错误响应中的 `feedback` 字段（由 `_err` 自动生成）
2. 补充 `title`、`content`、`reason`、`fix_suggestion`，并确认 `call_params` 已保留
3. 删除 `_hint` 等非提交字段
4. 调用 `feedback_submit`，并按接口参数显式传入 `skill_name`、`skill_version`、`mcp_tool_name`
5. 返回 `feedback_uuid` 并继续处理原任务

不要对 `feedback_submit` / `feedback_detail` 自身失败继续自动提交反馈。

成功查询不走本节的失败自动触发流程；默认只写本地任务摘要，不远端提交。只有用户明确要求、发布/审计门禁或 L2 可疑结果需要 owner 处理时，才提交汇总反馈。

## 参数结构铁律

`feedback_submit` 的结构化字段必须按接口参数传递：

- `skill_name`、`skill_version`、`command_name`、`mcp_tool_name` 是顶层参数，不能只放进 `context`
- MCP Tool 失败必须传 `mcp_tool_name`
- 由 Skill 执行过程触发的反馈必须传 `skill_name` 和 `skill_version`
- `payload`、`context`、`execution_summary` 必须是对象；`attachments` 必须是数组
- `app_version` 和 `client_version` 不要传；当前 `aukeys-opscli` 会自动写入真实版本
- `context` 只保存补充上下文，例如 `cwd`、`agent`、`workflow`、`request_id`

### 示例：自动触发

```python
# Tool 调用失败
result = query_simple(table_id=1, metrics=[...])
# result = {"success": false, "error": {...}, "feedback": {...}}

# 自动提取 feedback 草案并补充后提交
feedback = result["feedback"]
feedback.pop("_hint", None)
failed_call = feedback["execution_summary"]["failed_calls"][0]
failed_call["reason"] = "推测：字段名未匹配到服务端 metadata。"
failed_call["fix_suggestion"] = "改用 metadata 中的完整字段名，或先调用 query_metadata 校验字段。"
feedback_submit(
    feedback_type=feedback["feedback_type"],
    severity=feedback.get("severity", "medium"),
    source="mcp",
    title="query_simple 字段不存在",
    content="调用 query_simple 时服务端返回字段不存在错误",
    skill_name="ops-dataset-query",
    skill_version="v1.0.0",
    mcp_tool_name="query_simple",
    context={
        "cwd": "/Users/mask/python3/opscli",
        "agent": "Codex"
    },
    execution_summary=feedback["execution_summary"],
)
```

---

## 提交反馈

使用 `feedback_submit`：

```python
feedback_submit(
    feedback_type="bug",
    severity="medium",
    title="ops-dataset-query simple 字段不存在",
    content="使用 simple 查询时字段 original_price 无法识别，已改用 build 完成。",
    source="mcp",
    skill_name="ops-dataset-query",
    skill_version="v1.0.0",
    mcp_tool_name="query_simple",
    payload={
        "expected": "返回原价汇总",
        "actual": "字段不存在"
    },
    context={
        "cwd": "/Users/mask/python3/opscli",
        "agent": "Codex",
        "workflow": "ops-dataset-query"
    },
    execution_summary={
        "summary": "本次通过 ops-dataset-query 查询数据，simple 接口因字段识别失败，最终改用 build。",
        "failed_calls": [
            {
                "tool": "MCP → query_simple(table_id=1, metrics=[...])",
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
    }
)
```

## 查询反馈详情

```python
feedback_detail(feedback_uuid="<feedback_uuid>")
```

## 必填复盘字段

失败调用必须保留：

- `tool`：具体工具或命令
- `call_params`：具体关键参数和值
- `error_message`：原始错误码和错误文本
- `reason`：原因；推测时明确标注
- `fix_suggestion`：修复建议或已采用方案

## 注意事项

- 当前 MCP 工具会自动尝试读取本地 session，也支持显式传入 `session_id` 和 `jwt`
- 成功默认本地任务摘要，远端成功反馈默认关闭；不要为同一用户任务中的每次成功 query_simple 都提交一条反馈
- 不要提交 Token、Cookie、密码等敏感信息
