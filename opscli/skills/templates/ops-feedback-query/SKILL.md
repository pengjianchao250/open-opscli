---
name: ops-feedback-query
description: Use when an internal Aukeys developer needs to search or triage submitted feedback, retrieve batch details, generate a daily Markdown feedback report, or send a sanitized summary to a WeCom group robot.
---

# ops-feedback-query

本 Skill 仅供内部开发人员进行反馈检索和分诊。它通过独立密钥查询全量用户反馈，不使用 opscli JWT、session 或 Cookie，也不会注册公开 CLI/MCP 查询入口。

## 使用前配置

将内部密钥和企业微信群机器人 Webhook 写入本 Skill 的 `data/credentials.json`：

```json
{
  "feedback_api_key": "替换为内部密钥",
  "wecom_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=替换为机器人Key"
}
```

不要把密钥或 Webhook 放在命令参数、对话、日志或查询结果中。查询脚本只会通过 `X-Feedback-Api-Key` Header 发送反馈密钥；日报脚本只在显式传入 `--send` 时使用 Webhook。

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

## 生成 Markdown 日报并推送企业微信

默认统计 Asia/Shanghai 时区的完整昨日，只生成 Markdown 文件，不发送消息：

```bash
python scripts/daily_feedback_report.py
```

生成报告并向企业微信群机器人发送脱敏 Markdown V2 摘要：

```bash
python scripts/daily_feedback_report.py --send
```

### 使用大模型生成反馈洞察

洞察模式会读取当前周期及上一等长周期的反馈列表和批量详情，调用正式的
`opscli feedback insight` 命令进行语义分类，再由确定性规则计算模块问题次数、
环比、影响用户数、P0-P4 优先级和建议工作。旧日报默认不调用模型；必须显式
传入 `--insight`。

先参考 `data/feedback_insight.example.json` 创建独立模型配置：

```json
{
  "endpoint": "https://your-model-gateway.example/v1/chat/completions",
  "api_key": "替换为模型密钥",
  "model": "替换为模型名称",
  "batch_size": 50
}
```

默认配置路径为 `~/.config/opscli/feedback_insight.json`。也可以通过
`--insight-config` 指向受保护文件：

```bash
python scripts/daily_feedback_report.py \
  --insight \
  --insight-config /etc/opscli/feedback-insight.json \
  --send
```

模型接口必须兼容 OpenAI Chat Completions JSON 协议，非本机 endpoint 必须使用 HTTPS，
HTTP 仅允许 localhost/127.0.0.1/::1 调试地址。发送模型前只保留反馈 UUID、
类型、严重度、来源、系统、Skill/命令/工具、版本、标题、正文和首条失败摘要；邮箱、
用户 ID、payload、context、附件、调用参数和凭据不会发送。用户仅以本地哈希参与影响
人数统计，该哈希也不会发送给模型。

模型只负责 `module/problem_key/problem_category/problem_summary/recommended_work/confidence`
分类；次数、环比、影响人数和优先级由本地规则计算。Critical 固定为 P0；其他问题按
严重度、当前次数、影响人数和增长趋势计分，依次划分为 P1-P4。模型输出缺项、重复 UUID、
非法稳定键或置信度越界时整次洞察失败，不生成不完整报告。`batch_size` 控制每次模型
请求的反馈数，必须在 1 到 100 之间，默认 50。

后续模型批次会携带最多 100 个已建立的问题分类；本地还会按“原始系统/调用入口 + 标准化
错误模板”对齐跨周期重复问题，避免模型批次间 problem_key 或 module 漂移造成次数失真。
没有结构化错误信息时不按通用标题强制合并，避免不同根因被错误累计。平均置信度低于 0.7 的问题在
报告中标为“待复核”，不会触发 P0/P1 洞察提醒。模型或对比周期查询失败时自动降级为
基础日报，继续发送原有 Critical/High 提醒，不把可选 AI 能力变成日报单点故障。

指定统计时间范围：

```bash
python scripts/daily_feedback_report.py \
  --date-from "2026-07-20 00:00:00" \
  --date-to "2026-07-20 23:59:59" \
  --send
```

### 日报参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--date-from` | 否 | 查询起点；必须与 `--date-to` 同时传入，格式为 `YYYY-MM-DD HH:MM:SS` |
| `--date-to` | 否 | 查询终点；不传时间时默认完整昨日 |
| `--per-page` | 否 | 每页 1 到 100 条，默认 100；脚本自动翻页并按反馈 UUID 去重 |
| `--base-url` | 否 | 测试环境服务根地址，不含 `/api` |
| `--timeout` | 否 | 单次反馈查询超时秒数，默认 20 |
| `--output` | 否 | Markdown 文件路径；只允许写入项目根 `output/feedback-query/` |
| `--send` | 否 | 显式发送企业微信 Markdown 摘要；未传时绝不调用机器人 |
| `--insight` | 否 | 调用大模型生成模块问题洞察，并查询上一等长周期进行对比 |
| `--insight-config` | 否 | 模型配置文件；仅与 `--insight` 一起使用，默认读取 opscli 用户配置目录 |

日报包含反馈类型、问题严重度、来源、状态、失败调用数和问题列表。洞察模式额外包含模块、主要问题、本周期/上一周期次数、变化、优先级和建议工作；群消息优先提醒最多 3 条 P0/P1 洞察。群消息使用企业微信官方 `markdown_v2` 协议，内容不超过 4096 个 UTF-8 字节，不使用仅旧版 Markdown 支持的字体颜色和成员 `@` 语法。报告与群消息不会写入邮箱、用户 ID、原始 payload、context、附件或凭据；未启用洞察时，群消息仍按“严重度 + 标题”聚合重复问题，最多展示 5 类 Critical/High 问题并标注每类反馈数，底部提供固定的“详细文档查看”入口，完整逐条记录保留在本地 Markdown 文件。

## Linux 每日自动推送

Skill 内置 `deploy/` systemd 部署包，可在 Linux 服务器以专用服务账号每天 09:00（Asia/Shanghai）推送完整昨日的反馈日报：

```bash
sudo bash deploy/install_systemd.sh \
  --project-root /opt/open-opscli \
  --venv /opt/open-opscli/.venv \
  --user ops-feedback \
  --insight-config /etc/opscli/feedback-insight.json
```

`--insight-config` 可选；不传时继续生成旧版日报。传入时安装脚本会校验模型配置并将权限收紧为 `0600`，定时任务随后每日生成大模型洞察。安装脚本还会校验项目、虚拟环境、日报脚本和反馈凭据文件，收紧输出目录权限，安装 `ops-feedback-report.service/timer` 并立即启用 timer。首次部署后应手动执行 `sudo systemctl start ops-feedback-report.service` 验证真实推送；完整安装、巡检、排障与回滚步骤见 `docs/release/反馈日报定时推送运维指南.md`。

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
6. 需要模块分类、周期趋势和建议工作时增加 `--insight`；先不传 `--send` 检查 Markdown，确认模型分类和优先级后再显式推送企业微信。

## 安全边界

- 本 Skill 仅存在于 dev/internal 构建，不进入公开 source、wheel 或二进制产物。
- `data/credentials.json` 是内部明文凭据文件；更换反馈密钥或企业微信 Webhook 时只修改该文件。
- 不得输出、上传或反馈该密钥与 Webhook，也不要把它们复制到命令行参数。
- 企业微信发送前必须确认群成员范围；群消息仅包含脱敏摘要，完整报告只落在本地专用输出目录。
- 模型密钥只能放在 opscli 用户配置目录、受保护 CI File Variable 或 `/etc/opscli/` 受限文件，不得写入 Skill 的已跟踪凭据文件、命令行或日志。
- 完整详情可能包含个人邮箱、文件路径、工具参数和执行上下文，按最小必要原则查询和使用。
- 请求失败时只报告业务码、错误消息和安全的参数校验详情，不输出请求 Header。
