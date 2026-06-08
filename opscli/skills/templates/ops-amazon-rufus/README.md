# ops-amazon-rufus 使用说明

`ops-amazon-rufus` 提供 Amazon Rufus 默认问题模板库，并作为 Agent 使用 `amazon_rufus_get` MCP 工具的入口索引。Rufus 获取 Python 文件归属 MCP 层，目标路径为 `opscli/mcp/tools/amazon_rufus.py`；本 Skill 不包含获取脚本。

## 文件结构

```text
ops-amazon-rufus/
├── README.md
├── SKILL.md
├── data/
│   ├── VERSION.json
│   └── question_templates.json
└── references/
    ├── question-templates.md
    ├── rufus-mcp-workflow.md
    └── rufus-report-formatting.md
```

## 前置条件

1. 已安装本 Skill。
2. 已同步 `data/question_templates.json`。
3. 当前宿主可调用 `amazon_rufus_get` MCP 工具；未暴露该工具时，改用 opscli 正式 CLI 的本机 Chrome CDP 入口。
4. 不同国家站点授权状态相互独立；登录恢复必须使用原国家站点。

## 阅读入口

- `SKILL.md`：Agent 入口、触发范围、前置条件和精简主流程。
- `references/rufus-mcp-workflow.md`：Rufus 后端/headless 获取、MCP 工具调用、三类 MCP 错误的一次 CDP 登录恢复、问题来源选择和错误处理。
- `references/question-templates.md`：默认题库和问题模板维护说明。
- `references/rufus-report-formatting.md`：报告格式化、拒答改写和输出隐藏规则。

## 接口配置

默认题库 path `/opencalw/default-question-templates` 与上传 path `/v1/rufus/upload` 固定在 opscli 代码中。接口前缀域名/base URL 复用 opscli 的 `[systems] ops_url` 或 `.env` 中的 `OPSCLI_OPS_URL`；上传只有 CLI 显式传入 `--submit-upload` 时才发送。配置方式见 `references/question-templates.md` 和 `references/rufus-mcp-workflow.md`。

## 常用路径

1. 用户给出 ASIN、国家站点和可选问题。
2. Agent 先读取 `SKILL.md` 判断是否触发本 Skill。
3. 调用 `amazon_rufus_get`，由 MCP 后端使用 headless 链路获取。
4. 如果当前宿主未暴露 `amazon_rufus_get`，才改用 `opscli amazon-rufus get` 的本机 Chrome CDP 兼容入口；必要时使用 `--launch-if-needed`，自动发现失败后再传 `--chrome-path`。
5. 如果 MCP 返回 `RUFUS_HEADLESS_REQUEST_ERROR`、`RUFUS_HEADLESS_CAPTURE_ERROR` 或 `RUFUS_SECRET_NOT_READY`，本次 Skill 调用尚未触发登录恢复时，按 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed -> amazon_rufus_get` 闭环刷新本地登录态并保存请求种子。
6. 每次 Skill 调用最多触发一次登录恢复；`watch-login` 成功后仍失败时直接报错，不再重复打开登录窗口。
7. 最终只向用户展示本次工具返回的 `report_path` 或报告文件路径；不得返回历史 ASIN 报告。

## 文件边界

本 Skill 目录只承载数据与说明，不承载 Rufus 获取实现。

不应出现：

```text
ops-amazon-rufus/scripts/get_rufus.py
ops-amazon-rufus/scripts/rufus.py
ops-amazon-rufus/scripts/headless_rufus.py
```

所有获取 Rufus、读取后端授权材料、请求 Amazon Rufus 的 Python 代码必须位于 `opscli/amazon_rufus/` 或 `opscli/mcp/tools/amazon_rufus.py`。


$ops-amazon-rufus  帮我分析美国站，B0B1MLVMY5 这个商品的信息，要问 1. 这是什么商品 2. 这个商品评价如何 ？
