# amazon-rufus-mcp-headless-backend Proposal

## 背景

当前 `amazon_rufus_get` MCP 工具默认调用 `RufusManager.get()`，该路径会通过 Chrome CDP 连接或打开可见浏览器页面。用户明确要求参考 `E:/code/work/extension/python/app/contexts/rufus/application/account_runner.py`：Rufus MCP 服务默认应使用无头浏览器捕获上下文，并通过后端 HTTP streaming 请求 Rufus，而不是打开浏览器页获取。

## 范围

1. 将 `amazon_rufus_get` 默认路径切换到后端/headless 编排入口。
2. 新增 Rufus 后端请求凭证模型与 provider，内部结构对齐 `url/headers/cookies/payload_template`。
3. 新增或扩展 `RufusManager` 后端入口，复用现有题库解析、多问题解析、headless 捕获、SSE 请求与报告写入能力。
4. 默认 MCP 获取不再调用 `BrowserAttachService` 或 Chrome CDP。
5. 更新 `ops-amazon-rufus` Skill/README/reference 默认流程，避免继续推荐 `launch_if_needed=True` 作为默认获取方式。
6. 保留旧 CDP 路径作为兼容能力，不在本轮删除。

## 非目标

1. 不新增前端页面或授权管理 UI。
2. 不把 cookie、headers、payload_template 作为 MCP 明文参数暴露给 Agent。
3. 不建立账号池调度或批量 ASIN runner。
4. 不重写现有报告格式化、多问题输入或题库数据结构。
5. 不删除 `amazon_rufus_init`、`RufusManager.get()` 或 CDP 兼容路径。

## 验收标准

1. `amazon_rufus_get` 默认调用后端/headless 入口，不调用 `RufusManager.get()`。
2. 后端入口读取 Rufus secret，调用 headless 捕获和 streaming client。
3. Secret 缺失时返回稳定错误，不触发 CDP 浏览器。
4. MCP 成功返回和报告不包含 cookie、headers、payload_template、storage_state、seed_request。
5. Skill/README 默认流程不再把 CDP 自动启动作为 Rufus 获取默认路径。
6. `tests/mcp/test_amazon_rufus_tools.py` 与 `tests/amazon_rufus/test_core.py` 定向回归通过。
