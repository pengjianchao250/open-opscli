---
name: ops-amazon-rufus
description: Amazon Rufus 默认题库数据与 Agent 编排入口。用于基于 amazon_rufus_get MCP 工具对 ASIN 商品页进行 Rufus 问答、Listing 诊断、默认题库报告、临时问题获取、报告读取和 headless 后端获取错误处理。
---

# ops-amazon-rufus

本 Skill 是 Amazon Rufus 默认题库数据包与 Agent 编排入口。Rufus 获取能力由 MCP Tool 提供，获取 Rufus 的 Python 工具文件归属 `opscli/mcp/tools/amazon_rufus.py`，不得放在本 Skill 目录中。

## 触发范围

当用户提到 Amazon Listing、listing 商品页、listing 分析或 listing 优化，并且目标是通过 Rufus 对 ASIN 商品页进行问答、诊断、报告或表达风险判断时，使用本 Skill。

如果用户要求基于卖家精灵采集材料、关键词、高频词、PPC/ABA 数据做 Listing 表达与一致性优化，优先使用 `ops-amazon-listing-analysis`，不要用本 Skill 代替。

## 前置条件

1. 确认本 Skill 已安装并完成题库升级。
2. 确认当前宿主可调用 `amazon_rufus_get` MCP 工具；未暴露该工具时，可改用 opscli 正式 CLI 的本机 Chrome CDP 入口，不能在 Skill 目录新增脚本。
3. 不同国家站点授权状态相互独立，例如 `US` 对应 `amazon.com`，`DE` 对应 `amazon.de`；登录恢复必须使用原国家站点。
4. 获取结果只以工具返回的 `report_path` 或报告文件路径为准。

## 主流程

1. 解析用户提供的 ASIN、国家站点和可选 Rufus 问题，并初始化本次 Skill 调用状态：`login_recovery_attempted=false`。
2. 默认调用 `amazon_rufus_get`，由 MCP 后端使用 headless 链路获取 Rufus 回答并写入报告。
3. 如果用户提供一个临时问题，传 `question`；如果提供多个临时问题，传 `questions`；未提供问题时传 `skills_dir=".agents/skills"` 读取默认题库。
4. 如果 `amazon_rufus_get` 返回 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_SECRET_NOT_READY`，且 `login_recovery_attempted=false`，按 `references/rufus-mcp-workflow.md` 进入一次 CLI 登录页监听恢复。
5. 进入登录恢复后立即记录 `login_recovery_attempted=true`，先调用 `opscli amazon-rufus logout <COUNTRY> --pretty` 清理旧 Rufus 状态和 opscli-owned Chrome profile；`logout` 成功后再执行 `watch-login`，失败则停止恢复并提示用户关闭对应调试 Chrome 后重试。
6. 调用 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed`；该命令会打开或连接目标国家站点 Amazon 页面，通过 `#nav-tools` 未登录提示和 `sso-state-main` / `at-main` Cookie key 判断登录完成，自动打开目标商品页并捕获 `/rufus/cl/streaming` 请求种子。
7. `watch-login` 成功后按原 ASIN、国家和问题来源重新调用 `amazon_rufus_get`；MCP 服务层读取本地明文状态（敏感）请求 Rufus，不在 MCP 参数、报告或回复中展示 cookie、localStorage、`storage_state`、headers、payload 或完整请求。
8. 如果本次 Skill 调用已经触发过一次登录恢复，或保存后重新调用 `amazon_rufus_get` 仍失败，不再打开第二次登录窗口，直接返回错误并说明本次已完成一次登录恢复。
9. 如果成功但 `answer_count=0`，按正常 0 答案报告处理，不推断为登录恢复。
10. 最终回复只展示本次工具返回的 `report_path` 或报告文件路径；如需正文，只读取本次工具返回的 `report_path`，不得按 ASIN 读取历史报告。

## References

- `references/rufus-mcp-workflow.md`：Rufus 后端/headless 获取、MCP 工具调用、三类 MCP 错误的一次 CDP 登录恢复、问题来源选择和 `report_path` 输出规则。
- `references/question-templates.md`：默认题库数据结构、问题模板维护和本地题库文件说明。
- `references/rufus-report-formatting.md`：报告格式化、拒答改写和输出隐藏规则。

## 数据文件

- `data/VERSION.json`：Skill 名称与版本。
- `data/question_templates.json`：合并模板与题目的默认题库；未传临时问题时由 Rufus 获取链路读取。

## 文件边界

本 Skill 目录只承载文档、题库数据和 reference，不承载 Rufus 获取实现。

不得在本 Skill 下新增：

```text
scripts/get_rufus.py
scripts/rufus.py
scripts/headless_rufus.py
```

所有获取 Rufus、读取后端授权材料、请求 Amazon Rufus 的 Python 代码必须位于 `opscli/amazon_rufus/` 或 `opscli/mcp/tools/amazon_rufus.py`。
