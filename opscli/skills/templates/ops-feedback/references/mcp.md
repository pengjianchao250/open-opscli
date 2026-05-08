---
name: ops-feedback
mcp-version: v1.0.0
description: 通过 MCP Tool 提交和查询结构化用户反馈
---

# ops-feedback MCP

## 自动触发（Agent 工具调用失败后）

当 AI Agent 调用 MCP Tool 失败后，**必须**自动提交反馈。

### 触发流程

1. 检查错误响应中的 `feedback` 字段（由 `_err` 自动生成）
2. 补充 `title`、`content`、`reason`、`fix_suggestion`，并确认 `call_params` 已保留
3. 删除 `_hint` 等非提交字段
4. 调用 `feedback_submit`
5. 返回 `feedback_uuid` 并继续处理原任务

不要对 `feedback_submit` / `feedback_detail` 自身失败继续自动提交反馈。

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
    title="query_simple 字段不存在",
    content="调用 query_simple 时服务端返回字段不存在错误",
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
    context={
        "skill_name": "ops-dataset-query",
        "mcp_tool_name": "query_simple",
        "client_name": "opscli-mcp"
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
- 不要提交 Token、Cookie、密码等敏感信息
