---
name: ops-feedback-query
description: Use when an internal Aukeys developer needs to search all submitted feedback, triage feedback by status or severity, or retrieve full details for multiple feedback UUIDs.
---

# ops-feedback-query

本 Skill 仅供内部开发人员进行反馈检索和分诊。它通过独立密钥查询全量用户反馈，不使用 opscli JWT、session 或 Cookie，也不会注册公开 CLI/MCP 查询入口。

## 使用前配置

将内部密钥写入本 Skill 的 `data/credentials.json`：

```json
{
  "feedback_api_key": "替换为内部密钥"
}
```

不要把密钥放在命令参数、对话、日志或查询结果中。脚本只会通过 `X-Feedback-Api-Key` Header 发送该值。

## 查询反馈列表

```bash
python scripts/query_feedbacks.py list \
  --feedback-type bug \
  --status new \
  --severity high \
  --page 1 \
  --per-page 20 \
  --output output/feedback-query/feedback-list.json \
  --pretty
```

关键词和时间范围示例：

```bash
python scripts/query_feedbacks.py list \
  --feedback-type all \
  --search "查询失败" \
  --date-from "2026-07-01 00:00:00" \
  --date-to "2026-07-14 23:59:59" \
  --sort-by created_at \
  --sort-direction desc \
  --pretty
```

### list 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--feedback-type` | 否 | `all/bug/feature/data_issue/ux/docs/other/query_result`，服务端默认 `bug` |
| `--severity` | 否 | `low/medium/high/critical` |
| `--status` | 否 | `new/triaged/processing/resolved/rejected` |
| `--source` | 否 | `cli/mcp/skill/api` |
| `--user-id` | 否 | 提交人 ID，必须大于 0 |
| `--user-email` | 否 | 提交人邮箱精确匹配 |
| `--system-alias` | 否 | 目标系统别名，如 `ops` |
| `--search` | 否 | 标题和正文关键词 |
| `--date-from` | 否 | 提交时间起点 |
| `--date-to` | 否 | 提交时间终点 |
| `--sort-by` | 否 | `created_at/updated_at/severity/failed_call_count/id` |
| `--sort-direction` | 否 | `asc/desc` |
| `--page` | 否 | 页码，从 1 开始 |
| `--per-page` | 否 | 每页 1 到 100 条 |
| `--base-url` | 否 | 测试环境服务根地址，不含 `/api` |
| `--timeout` | 否 | HTTP 超时秒数，默认 20 |
| `--output` | 否 | JSON 文件路径；自动创建父目录且只允许写入项目根 `output/feedback-query/` |
| `--pretty` | 否 | 格式化输出 JSON |

## 批量查询完整详情

```bash
python scripts/query_feedbacks.py batch-detail \
  --feedback-uuids \
  f782fbb3-c51d-4d3e-ab58-216e6882446c \
  58af57f2-34ff-40ed-b8d2-58bcdfd8e57e \
  --feedback-type all \
  --output output/feedback-query/feedback-detail.json \
  --pretty
```

### batch-detail 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--feedback-uuids` | 是 | 1 到 100 个反馈 UUID，以空格分隔 |
| `--feedback-type` | 否 | 类型过滤，服务端默认 `bug`；传 `all` 查询全部类型 |
| `--base-url` | 否 | 测试环境服务根地址，不含 `/api` |
| `--timeout` | 否 | HTTP 超时秒数，默认 20 |
| `--output` | 否 | JSON 文件路径；自动创建父目录且只允许写入项目根 `output/feedback-query/` |
| `--pretty` | 否 | 格式化输出 JSON |

## 输出约定

- 不传 `--output` 时，完整 JSON 信封输出到终端。
- 传入 `--output` 时，脚本自动创建父目录并写入 UTF-8 JSON 文件；终端只输出成功状态和绝对文件路径，不重复展示敏感详情。
- 脚本会从当前目录向上定位 Git 项目根；`result.json` 与 `output/feedback-query/result.json` 都会写到项目根 `output/feedback-query/result.json`。
- 绝对路径仅在已位于项目根 `output/feedback-query/` 内时接受；父目录穿越、目录外路径和无法定位 Git 项目根的执行环境都会被拒绝。
- 所有反馈查询导出统一放在项目根目录 `output/feedback-query/`，该目录已从 Git 跟踪中排除。

## 典型工作流

1. 先用 `list` 按 `status/severity/date` 缩小范围，避免无边界读取全量数据。
2. 从列表结果提取需要分析的 `feedback_uuid`。
3. 用 `batch-detail` 一次读取最多 100 条完整详情。
4. 根据 `content`、`execution_summary.failed_calls` 和版本信息进行分诊。
5. 只保留解决问题所需字段，不把邮箱、payload、context、附件或执行参数复制到公开渠道。

## 安全边界

- 本 Skill 仅存在于 dev/internal 构建，不进入公开 source、wheel 或二进制产物。
- `data/credentials.json` 是内部明文凭据文件；更换密钥时只修改该文件。
- 不得输出、上传或反馈该密钥，也不要把它复制到命令行参数。
- 完整详情可能包含个人邮箱、文件路径、工具参数和执行上下文，按最小必要原则查询和使用。
- 请求失败时只报告业务码、错误消息和安全的参数校验详情，不输出请求 Header。
