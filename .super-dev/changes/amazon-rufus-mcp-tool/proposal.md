# amazon-rufus-mcp-tool Proposal

## 背景

`ops-amazon-rufus` 已经沉淀题库数据、报告格式和用户授权编排规则，但 Rufus 获取能力需要收敛到 MCP Tool。用户明确要求：MCP 应拥有获取 Rufus 的 Python 工具文件，Skill 中不应出现获取 Rufus 的 Python 脚本文件或 CLI/Python 获取实现流程。

## 范围

1. 新增 MCP 工具模块 `opscli/mcp/tools/amazon_rufus.py`，承载 `amazon_rufus_*` 工具函数。
2. MCP 工具复用 `opscli/amazon_rufus/` 现有业务实现，不把获取逻辑复制到 Skill 目录。
3. 在 `opscli/mcp/server.py` 注册 Rufus MCP 工具。
4. `ops-amazon-rufus` Skill 保留题库数据、升级说明、MCP 工具索引和用户授权编排规则。
5. 用户同意保存 cookie / browser state 时，Skill 指导 Agent 调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。

## 非目标

1. 不新增独立 MCP Server。
2. 不把 Skill 改造成执行脚本集合。
3. 不在 Skill 目录新增 `scripts/get_rufus.py`、`scripts/rufus.py`、`scripts/headless_rufus.py` 等获取脚本。
4. 不在 MCP 返回、报告、stdout、feedback 中暴露 cookie、localStorage、storage state 或原始请求头。
5. 不重写既有 Rufus 核心获取链路。

## 验收标准

1. MCP 工具列表包含 `amazon_rufus_init` 和 `amazon_rufus_get`。
2. `amazon_rufus_get` 调用现有 Rufus Python 业务层并返回报告路径。
3. 远程授权工具必须要求 `allow_capture_browser_state=True`，否则拒绝执行。
4. `ops-amazon-rufus` Skill 文档不再描述 CLI/Python 获取流程。
5. `ops-amazon-rufus` Skill 目录不包含获取 Rufus 的 `.py` 脚本文件。
6. 现有 Amazon Rufus 与 MCP 测试继续通过。
