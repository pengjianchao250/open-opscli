---
name: ops-feedback
cli-version: v1.0.0
description: 通过 opscli feedback 提交和查询结构化用户反馈
---

# ops-feedback CLI

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
- 不要手工传 `app_version`、`client_version`；由当前 `aukeys-opscli` 自动写入
- `execution_summary.failed_calls[*].call_params` 必须保留具体字段和值
- 不要提交 Token、Cookie、密码等敏感信息
