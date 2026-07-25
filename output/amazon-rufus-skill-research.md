# Amazon Rufus Skill 回答质量重试研究

## 研究目标

本轮研究聚焦 `ops-amazon-rufus` Skill 的回答质量兜底能力：当 Rufus 获取完成但答案为空、拒答、答非所问，或复杂问题只得到商品详情类回答时，Agent 需要改写问题并重新请求 Rufus；多问题仍在同一个 Rufus 对话中处理，每个问题最多 5 次。

本轮补充排查亚马逊 Rufus 登录态失效时的页面反复打开问题：`watch_login` 本身会打开登录页，检测到登录后再打开目标商品页捕获 `/rufus/cl/streaming`。商品页打开一次是预期行为；问题在于 Skill 多个错误分支都可再次调用 `amazon_rufus_watch_login`，原流程只记录 `login_recovery_attempted`，无法限制 OPS 401、登录态缺失、旧 content、headless 恢复等分支的总登录采集次数。同时浏览器启动参数包含 `--auto-open-devtools-for-tabs`，会额外打开 DevTools 页签。

## 本地基线

已核对以下文件：

| 文件 | 发现 |
|---|---|
| `.agents/skills/ops-amazon-rufus/SKILL.md` | 原流程把 `answer_count=0` 当正常 0 答案报告处理。 |
| `opscli/skills/templates/ops-amazon-rufus/SKILL.md` | 模板版同样缺少回答质量判断和问题改写重试。 |
| `references/rufus-mcp-workflow.md` | 已有 MCP-first、登录恢复、CLI fallback 和报告新鲜度规则，但没有语义级回答质量判断。 |
| `opscli/amazon_rufus/services/manager.py` | 后端只负责按问题请求 Rufus 和组装结果，不适合承载子 agent 语义改写。 |
| `opscli/amazon_rufus/services/mcp_manager.py` | MCP 响应只返回 `report_path`、问题数和答案数等脱敏摘要。 |
| `opscli/amazon_rufus/services/browser.py` | `_start_new_chrome()` 会携带 `--auto-open-devtools-for-tabs`，导致新开调试浏览器时自动打开 DevTools。 |

## 设计判断

该需求应落在 Agent 编排层，而不是 Python 后端层：

1. 用户明确要求“开启一个子 agent”，这是 Agent 工作流能力。
2. 判断“问题不止商品详情但回答是商品详情”属于语义判断，后端规则硬编码容易误伤。
3. `opscli` 后端继续保持单一职责：请求 Rufus、写报告、隐藏敏感信息。
4. Skill 文档负责约束 Agent 在读取本次 `report_path` 后执行质量判断和有限重试。

## 新增状态

| 状态 | 初始值 | 用途 |
|---|---|---|
| `answer_rewrite_attempts_by_question` | `{}` | 按问题分别记录回答质量重试次数，每个问题最多 5 次。 |
| `login_recovery_attempted` | `false` | 继续只限制登录恢复，两者互不重置。 |
| `watch_login_attempted` | `false` | 同一次 Skill 调用最多触发一次 `watch_login`；MCP 和 CLI 登录采集都计入。 |

## 登录采集结论

1. `watch_login` 是监听登录态和捕获请求种子的阻塞入口，不是普通重试动作。
2. 同一次 Skill 调用中，任何分支准备调用 `amazon_rufus_watch_login` 或 CLI `opscli amazon-rufus watch-login` 前，都必须先检查 `watch_login_attempted=false`。
3. 调用前立即设置 `watch_login_attempted=true`；如果已经为 true，直接返回最新错误，避免重复打开浏览器和商品页。
4. 移除 Chrome 启动参数 `--auto-open-devtools-for-tabs`，保留远程调试端口和独立 profile 即可。

## 不合格答案定义

以下任一情况需要改写问题并重新请求 Rufus：

1. `answer_count=0`、报告为空、题目下没有实际答案。
2. Rufus 明确拒答、提示重试、表示无法回答或只返回错误性文本。
3. 问题询问差评、风险、评价、适配人群、广告投放、对比、场景判断或优化建议，但回答只描述商品详情、规格参数或基础卖点。
4. 多题场景中某一题答案串题、漏题，或回答内容明显属于另一道题。

## 子 agent 改写规则

只把不合格题目交给子 agent。固定提示词为：

```text
重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。
```

子 agent 只接收待改写问题文本，不接收 cookie、headers、payload、`storage_state`、cURL 命令、请求种子、OPS 平台 Cookie 接口 content 或亚马逊 Rufus 登录态。

## 重新请求规则

1. 将改写后的题目替换回原位置，形成完整问题列表。
2. 按改写后的完整问题来源重新调用 `amazon_rufus_get` 或 CLI `get-backend`。
3. 单题继续传 `question`；多题或默认题库重试时传完整 `questions` 列表，并保持同一个 Rufus 对话语义。
4. 不把多个问题拼成一个长字符串，不因为重试改跑默认题库。
5. 每完成一次 Rufus 重新请求，只增加本轮被改写题目的 `answer_rewrite_attempts_by_question` 计数。
6. 某题达到 5 次仍不合格时停止重试该题，其他题目继续按各自上限处理；最终只展示最新一次 `report_path` 并说明对应题目达到回答质量重试上限。

## 结论

本轮改动应同步项目安装版 Skill 与内置模板版 Skill，并新增文档约束测试。这样既满足用户对“子 agent 改写 + 每个问题最多 5 次重试”的流程要求，也保持 `opscli` 后端的 KISS、YAGNI 和最小权限边界。
