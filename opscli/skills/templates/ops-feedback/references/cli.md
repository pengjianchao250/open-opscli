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
  "context": {
    "skill_name": "ops-dataset-query",
    "command_name": "opscli query simple",
    "client_name": "opscli"
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
  --command-name "opscli query simple" \
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
- `execution_summary.failed_calls[*].call_params` 必须保留具体字段和值
- 不要提交 Token、Cookie、密码等敏感信息
