# Amazon Rufus Skill 流程图 UIUX

## 目标

流程图需要让维护者一眼看懂两个关键路径：Rufus 报告生成后的回答质量重试，以及亚马逊登录态失效时 `watch_login` 只允许触发一次。图中必须清楚表达第二次登录采集会直接返回错误，不再打开新的登录页或商品页。

## 图表规则

| 项目 | 规则 |
|---|---|
| 图表语言 | Mermaid flowchart。 |
| 输出 | `.mmd` 源文件和 `.svg` 渲染图。 |
| 方向 | 自上而下。 |
| 文案 | 中文为主，保留函数名、错误码和状态变量。 |
| 敏感信息 | 不在图中展示 cookie、headers、payload、cURL 或登录态内容。 |

## 新增图层

| 区域 | 内容 |
|---|---|
| 回答质量判断 | 读取本次 `report_path`，判断是否无回答、拒答、答非所问或退化为商品详情。 |
| 子 agent 改写 | 固定提示词，改写不合格问题，总字数不超过 200。 |
| 重试上限 | `answer_rewrite_attempts_by_question[题目] < 5` 时重试，达到 5 次只停止对应题目。 |
| 登录采集守卫 | `watch_login_attempted=false` 时才执行 MCP/CLI 登录采集；已经为 true 时进入错误出口。 |

## 产物

| 文件 | 用途 |
|---|---|
| `output/amazon-rufus-skill-flow.mmd` | Mermaid 源图。 |
| `output/amazon-rufus-skill-flow.svg` | 渲染后的流程图。 |
