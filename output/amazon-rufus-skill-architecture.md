# Amazon Rufus Skill 回答质量重试与登录采集约束架构

## 架构定位

回答质量重试属于 Agent 编排层，不属于 `RufusManager.get_backend(...)` 的 Python 后端逻辑。

```text
amazon_rufus_get / get-backend
  -> 写入本次 report_path
  -> Agent 读取本次报告
  -> 判断回答质量
  -> 子 agent 改写不合格问题
  -> 替换回完整问题来源
  -> 在同一个 Rufus 对话语义下重新请求 Rufus
```

登录采集单次触发也属于 Agent 编排层。`amazon_rufus_watch_login` 是监听登录态并捕获 `/rufus/cl/streaming` 请求种子的阻塞入口；同一次 Skill 调用内的登录态缺失、OPS 401、旧 content、headless 恢复和 CLI fallback 都共享 `watch_login_attempted`，避免反复打开浏览器页面。

## 分层职责

| 层级 | 职责 |
|---|---|
| Skill 文档层 | 定义什么时候判断回答质量、什么时候改写问题、每个问题最多重试几次。 |
| Agent 编排层 | 读取本次 `report_path`、判断不合格题目、开启子 agent、重新调用 Rufus。 |
| MCP 工具层 | 继续提供 `amazon_rufus_get`、`amazon_rufus_watch_login` 等工具。 |
| Rufus 后端层 | 继续只负责请求 Rufus、解析结果、写报告；Chrome 启动不再携带自动打开 DevTools 的参数。 |
| 报告层 | 输出本次 Markdown 报告，供 Agent 做质量判断。 |

## 状态机

| 状态 | 说明 |
|---|---|
| `answer_rewrite_attempts_by_question={}` | 按问题分别记录回答质量重试次数，每个问题最多 5 次。 |
| `login_recovery_attempted=false` | 本轮登录恢复次数，两者互不影响。 |
| `watch_login_attempted=false` | 同一次 Skill 调用最多触发一次 `watch_login`，MCP 和 CLI 登录采集都计入。 |

## 登录采集约束

1. 任何分支准备调用 `amazon_rufus_watch_login` 或 CLI `opscli amazon-rufus watch-login` 前，必须检查 `watch_login_attempted=false`。
2. 调用前立即设置 `watch_login_attempted=true`，再进入阻塞监听。
3. 如果 `watch_login_attempted=true`，不得再次打开浏览器，不得先 `amazon_rufus_logout` 后重复登录，直接返回最新错误。
4. 回答质量重试不得重置 `watch_login_attempted`。

## 质量判断输入

只允许读取：

1. 本次 `amazon_rufus_get` 或 CLI `get-backend` 返回的 `report_path`。
2. 本次问题列表。
3. 本次报告正文。

禁止读取：

1. 历史 ASIN 报告。
2. OPS 平台 Cookie 接口 content。
3. cookie、headers、payload、`storage_state`、cURL 命令、请求种子。

## 子 agent 契约

固定提示词：

```text
重写这些问题，修改其中的字，但要求意思保持不变。总字数不要超过200。
```

输入只包含待改写问题文本。输出必须满足：

1. 问题数量一致。
2. 意思保持不变。
3. 总字数不超过 200。

## 重试链路

1. 判断出不合格题目。
2. 子 agent 改写不合格题目。
3. 替换原问题位置，形成完整问题列表。
4. 按改写后的完整问题来源重新调用 Rufus；多题或默认题库重试时传完整 `questions` 列表，保持同一个 Rufus 对话语义。
5. 只增加本轮被改写题目的 `answer_rewrite_attempts_by_question` 计数。
6. 再次读取最新 `report_path` 判断。
7. 合格则输出最新 `report_path`。
8. 某题 5 次仍不合格则停止重试该题，其他题目继续按各自上限处理；最终输出最新 `report_path` 并说明对应题目达到上限。

## 边界

1. 回答质量重试不触发 `amazon_rufus_logout`。
2. 回答质量重试不扩大 CLI fallback 白名单。
3. 回答质量重试不重置 `login_recovery_attempted`。
4. 默认题库重试时转为完整 `questions` 列表，不再用 `skills_dir` 重新取题库，避免问题来源漂移。
