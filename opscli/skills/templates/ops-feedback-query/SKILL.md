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
  "batch_size": 100
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
HTTP 仅允许 localhost/127.0.0.1/::1 调试地址。发送模型前只保留批内短引用、
类型、严重度、来源、系统、Skill/命令/工具、版本、标题、正文和首条失败摘要；邮箱、
用户 ID、payload、context、附件、调用参数和凭据不会发送。用户仅以本地哈希参与影响
人数统计，该哈希也不会发送给模型。

模型只负责 `module/problem_key/problem_category/problem_summary/recommended_work/confidence`
分类；次数、环比、影响人数和优先级由本地规则计算。Critical 固定为 P0；其他问题按
严重度、当前次数、影响人数和增长趋势计分，依次划分为 P1-P4。模型输出缺项、重复批内引用、
非法稳定键或置信度越界时整次洞察失败，不生成不完整报告。`batch_size` 控制每次模型
请求的反馈数，必须在 1 到 100 之间，默认 100。单批网络失败自动重试一次。

后续模型批次会携带最多 200 个已建立的问题分类；本地还会按“原始系统/调用入口 + 标准化
错误模板”对齐跨周期重复问题，避免模型批次间 problem_key 或 module 漂移造成次数失真。
没有结构化错误信息时不按通用标题强制合并，避免不同根因被错误累计。平均置信度低于 0.7 的问题在
报告中标为“待复核”，不会触发 P0/P1 洞察提醒。模型或对比周期查询失败时自动降级为
基础日报，继续发送原有 Critical/High 提醒，不把可选 AI 能力变成日报单点故障。

### 本地 Codex 两阶段日报

本地生产默认使用“08:30 提前取数，Codex App 稍后分析”的两阶段模式，避免长时间网关请求
占用 Windows 计划任务。第一阶段只查询昨天及前一天数据、读取详情、脱敏并分块，不调用模型、
不生成最终日报、不发送企业微信：

```bash
python scripts/daily_feedback_report.py --prepare-only
```

准备结果固定写入 `output/feedback-query/prepared/YYYY-MM-DD/`。只有 `analysis-input.json`、
`report-input.json`、全部 chunk 和契约哈希成功落盘后，manifest 才会从 `preparing` 原子切换为
`ready`，并写入内容为“YYYY-MM-DD 数据已完成”的 `READY` 标记。重复执行同一天准备任务会复用
完整的 `ready/analyzing/completed` 产物，不重复取数。

Codex App 自动化必须先完整读取本 Skill 和 `reference/Codex反馈洞察分类契约.md`，然后领取
上海时区昨日对应的 ready 数据；更早的 backlog 不会被误发为当日日报：

```bash
python scripts/daily_feedback_report.py --claim-ready
```

返回 `state=idle` 时直接结束，不生成或发送任何内容。领取命令也会恢复上一次未完成的
`analyzing` 数据；返回 `state=analyzing` 时，按 manifest 的
chunk 顺序处理；每个 `chunk-XXX.output.json` 只写契约允许的分类字段，且必须覆盖输入中的全部
UUID。写完一块立即运行：

```bash
python scripts/daily_feedback_report.py \
  --validate-chunk output/feedback-query/prepared/YYYY-MM-DD/chunks/chunk-001.output.json
```

校验失败只修复该 chunk；不得直接修改 manifest、最终统计、Markdown 或完成标记。全部 chunk
返回 `status=validated` 后执行离线收尾：

```bash
python scripts/daily_feedback_report.py \
  --finalize-prepared output/feedback-query/prepared/YYYY-MM-DD \
  --analysis-model scheduled-codex \
  --send
```

收尾阶段会再次校验所有输入哈希、chunk 元数据、稳定键、置信度和 UUID 全覆盖，再复用
`opscli.feedback.services.insight` 的确定性规则计算次数、环比、影响人数和 P0-P4，最后生成运行
产物、发布 Markdown、推送企业微信并写入“YYYY-MM-DD AI 洞察已完成”的 `COMPLETED` 标记。
分类不完整、文件被修改或通知失败都会留下结构化失败状态；Codex 不得绕过 Python 自行计算统计。

Windows 取数任务可重复执行下面的安装脚本进行创建或修复，默认任务名为
`OpsCLI Feedback Daily Insight`，每天 08:30 触发，错过时间后在下次可用时补跑：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/install_windows.ps1 `
  -ProjectRoot D:\Gitlab\open-opscli
```

该任务使用当前 Windows 用户的交互登录令牌和受限权限；电脑需开机且用户已登录。Codex App
09:00 自动化是本机应用配置，不由此脚本创建，需在 Codex App 中启用“反馈日报 Codex 洞察”。

### 日报运行产物

每次日报运行都会在 `output/feedback-query/runs/<run-id>/` 写入两份结构化产物：

- `manifest.json`：时间窗口、运行状态、日报路径、AI 是否成功或降级、明确的安全错误码，
  以及企业微信通知状态。
- `clusters.json`：基础反馈指标、对比窗口、AI 问题簇、模块汇总和模型契约元数据。

`run_key` 由报告类型、完整时间窗哈希、`base/insight` 分析 profile 和 schema 版本确定，
`run_id` 再追加 UTC 尝试时间，因此同一天不同窗口或不同分析模式不会混组，重跑也不会覆盖
上一份运行记录。每次尝试还会保存不可变的 `report.md` 及其 SHA-256；根目录日报
只是供浏览器访问的最新发布副本，并通过同目录临时文件原子替换。后续周报、月报按不含 profile
的 `period_key` 分组，每个时间窗只选一份：依次选择最新的 `insight success`、
`insight degraded`、`base success`；企业微信投递状态不影响分析快照选择。不得解析或累加
Markdown。产物只保存聚合指标、问题簇和样本反馈 UUID，不保存
邮箱、用户 ID、原始 payload、context、附件或模型密钥。AI 模式还会保存当前期、对比期和
脱敏模型输入哈希，以及查询、详情读取、模型和通知阶段耗时；即使 AI 降级，仍保留不含密钥的
model、batch size、Prompt 版本和 Prompt 哈希，供连续运行后统计稳定性。

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
| `--prepare-only` | 否 | 只准备昨日脱敏数据、分块和 READY 标记，不调用模型或推送 |
| `--claim-ready` | 否 | 领取最新 ready 数据并切换为 analyzing，供 Codex App 自动化使用 |
| `--validate-chunk` | 否 | 校验一个 Codex chunk 输出并记录 validated/failed 检查点 |
| `--finalize-prepared` | 否 | 从准备目录离线聚合并发布最终 AI 日报 |
| `--analysis-model` | 否 | 最终化时记录的 Codex 模型名称，默认 `codex_app`，不参与统计 |

日报包含反馈类型、问题严重度、来源、状态、失败调用数和问题列表，并使用 Mermaid `pie` 扩展语法展示反馈类型与严重度分布；两张图在本地浏览器中并排展示，数量与占比整合在图例中，原始统计表默认折叠并继续作为不支持 Mermaid 时的降级数据；问题来源与状态统计表同样使用桌面双列、移动单列布局。洞察模式额外包含模块、主要问题、本周期/上一周期次数、变化、优先级和建议工作；群消息优先提醒最多 3 条 P0/P1 洞察。群消息使用企业微信官方 `markdown_v2` 协议，内容不超过 4096 个 UTF-8 字节，不使用仅旧版 Markdown 支持的字体颜色和成员 `@` 语法。报告、运行产物与群消息不会写入邮箱、用户 ID、原始 payload、context、附件或凭据；未启用洞察时，群消息仍按“严重度 + 标题”聚合重复问题，最多展示 5 类 Critical/High 问题并标注每类反馈数，底部提供固定的“详细文档查看”入口，完整逐条记录保留在本地 Markdown 文件。

### 本地浏览日报

启动只读的本地 HTTP 服务，按更新时间浏览 `output/feedback-query/` 中的 Markdown 日报：

```bash
python scripts/serve_feedback_reports.py
```

服务默认监听 `http://127.0.0.1:8780`，不会暴露到局域网。可使用 `--port` 修改端口：

```bash
python scripts/serve_feedback_reports.py --port 8877
```

需要让同一局域网的设备访问时，显式传入本机私有 IPv4 地址，并在系统防火墙中只对本地子网放行对应端口：

```bash
python scripts/serve_feedback_reports.py --host 10.6.53.56 --port 8780
```

`--host` 只接受明确的回环或私有 IPv4 地址；拒绝 `0.0.0.0`、公网地址和主机名。LAN 模式仍使用 Host 白名单，不会接受其他地址的 Host 请求。

浏览服务只读取报告目录根部、符合 `反馈日报-YYYY-MM-DD[_YYYY-MM-DD][-*].md` 或月度反馈复盘命名的文件，提供报告页面、Markdown 原文、`/api/reports` 列表和 `/health` 健康检查；日报使用的 Mermaid `pie showData` 会转换为无外部脚本的本地图表，桌面端使用双列分布概览，窄屏自动切换单列，原始表格可按需展开；其他 Mermaid 类型安全回退为转义源码。其他 Markdown、JSON 查询结果、模型配置、凭据、子目录和目录外文件均不可访问。

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
