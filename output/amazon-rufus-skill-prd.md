# Amazon Rufus Skill 回答质量重试与登录采集修复 PRD

## 背景

`ops-amazon-rufus` 当前能完成 MCP-first Rufus 获取、登录态恢复、CLI fallback 和报告输出。但如果 Rufus 没有回答、拒答，或回答内容只停留在商品详情而没有覆盖用户真正询问的评价、风险、适配性、广告投放等问题，现有 Skill 缺少问题改写重试规则。

用户补充发现亚马逊登录态失效时，流程会先打开商品页，再反复打开并快速关闭其他页面。根因是同一次 Skill 调用内多个分支都能触发 `watch_login`，但原流程只限制登录恢复次数，没有限制 `watch_login` 总次数；同时 Chrome 启动参数中带有自动打开 DevTools 的参数，增加额外页面干扰。

## 目标

1. Rufus 获取成功后必须读取本次 `report_path` 做回答质量判断。
2. 无回答、拒答、答非所问、复杂问题退化为商品详情时，开启子 agent 改写问题。
3. 子 agent 固定提示词：`重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。`
4. 拿到新问题后重新请求 Rufus。
5. 多问题获取保持在同一个 Rufus 对话中，不拆成多个独立对话。
6. 使用 `answer_rewrite_attempts_by_question` 按问题分别记录，每个问题最多 10 次。
7. 同一次 Skill 调用最多触发一次 `watch_login`，MCP 和 CLI 登录采集共享 `watch_login_attempted`。
8. Chrome 启动不再携带自动打开 DevTools 的参数。
9. 同步更新项目安装版 Skill、内置模板版 Skill、reference、README、Super Dev 文档和流程图。

## 非目标

1. 不在 Skill 目录新增 Python 获取脚本。
2. 不修改 `opscli/amazon_rufus/` 的后端获取逻辑。
3. 不改变远程授权偏好、MCP 登录恢复、CLI fallback 白名单。
4. 不向子 agent 传递敏感登录态、请求头、payload 或 cURL 命令。

## 功能需求

### 回答质量判断

每次 `amazon_rufus_get` 或 CLI `get-backend` 成功后，Agent 只读取本次返回的 `report_path`，逐题判断答案是否合格。不得读取历史 ASIN 报告或 IDE 打开的旧文件。

### 问题改写

当发现不合格答案时，只把不合格题目交给子 agent。子 agent 输出必须保持问题数量一致、语义不变、总字数不超过 200。

### 重新请求

改写后的题目替换原位置，形成完整问题列表，然后按改写后的完整问题来源重新调用 `amazon_rufus_get` 或 CLI `get-backend`。多题或默认题库重试时传完整 `questions` 列表，保持同一个 Rufus 对话语义。

### 重试上限

使用 `answer_rewrite_attempts_by_question={}` 按问题分别记录回答质量重试次数。每完成一次 Rufus 重新请求后，只增加本轮被改写题目的计数；每个问题最多 10 次。某题达到上限后停止重试该题，其他题目仍可按各自上限继续，最终返回最新 `report_path`。

### 登录采集单次触发

同一次 Skill 调用初始化 `watch_login_attempted=false`。任何分支准备调用 MCP `amazon_rufus_watch_login` 或 CLI `opscli amazon-rufus watch-login` 前，必须先检查该状态，并在调用前设置为 `watch_login_attempted=true`。如果状态已经为 true，直接返回最新错误，不再打开第二次登录窗口或商品页。

### DevTools 参数

工具自动启动 Chrome/Edge 调试窗口时，只保留远程调试端口、独立 profile、首次运行和默认浏览器检查相关参数；不得携带 `--auto-open-devtools-for-tabs`。

## 验收标准

| 项目 | 标准 |
|---|---|
| Skill 入口 | 项目版和模板版 `SKILL.md` 都包含回答质量判断和问题改写重试规则。 |
| reference | 两份 `rufus-mcp-workflow.md` 都包含不合格判断、子 agent 提示词、同一个 Rufus 对话和每个问题最多 10 次规则。 |
| README | 两份 README 都说明获取后需要质量判断和重试。 |
| 流程图 | Mermaid 图包含回答质量判断、问题改写重试和 `watch_login_attempted` 分支。 |
| 测试 | `test_ops_amazon_rufus_docs_require_answer_quality_rewrite_retry`、`test_ops_amazon_rufus_docs_limit_watch_login_once_per_skill_call` 和 Chrome 启动参数测试通过。 |
