---
name: ops-amazon
description: 根据当前环境自动选择 CLI 或 MCP 方式抓取 Amazon 商品页和搜索结果样本
version: v0.1.5
---

# ops-amazon

用于抓取 Amazon 商品页快照、搜索结果页样本，以及面向 ops API 和数据表设计的标准化样本数据。

---

## 何时使用本 Skill

- 需要抓取某个 Amazon 商品的价格、评分、评论数、配送位置
- 需要抓取关键词搜索结果做竞品样本分析
- 需要输出未来提交给 ops API 的标准 payload
- 需要拿真实样本给后端做字段设计、表结构设计、接口设计
- 需要查看某个商品的本地历史抓取记录

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

优先级如下：

1. 如果用户明确要求使用 CLI 或 MCP，直接遵循用户指定
2. 如果当前就在 `opscli` 项目、本地终端可直接执行正式命令，默认使用 CLI，并读取 `references/cli.md`
3. 如果当前任务本身就是基于 MCP Tool 协作，或明显无法直接走本地 CLI，再读取 `references/mcp.md`
4. 如果一开始按 CLI 执行首个正式命令就失败（例如 `opscli amazon ...` 不可用、Amazon 扩展未安装、当前宿主不适合跑本地命令），直接切换到 MCP 版本，并读取 `references/mcp.md`
5. 如果 MCP 版本也不可用（例如当前没有可用 MCP 服务、Amazon 工具未注册、调用宿主不支持 MCP），再回退为帮助用户安装 `aukeys-opscli`

建议提问方式：

- `当前 CLI 与 MCP 入口都不可用。你希望我先帮你安装 aukeys-opscli，再继续处理吗？`

简化原则：

- 默认优先 CLI，因为它是 `opscli` 模块的正式入口，最贴近真实交付路径
- 不单独检查发行包、命令路径、子命令 help；用“首次正式调用是否可执行”作为唯一验证
- 一旦 CLI 和 MCP 都可行，优先保持单一路径，不要来回切换
- CLI 首次正式调用失败后，直接切到 MCP，不额外询问
- 只有在 MCP 版本也不可用时，才回退为帮助用户安装 `aukeys-opscli`

---

## 阅读入口

- CLI 模式：继续阅读 `references/cli.md`
- MCP 模式：继续阅读 `references/mcp.md`

---

## 使用原则

- 抓取动作必须统一走选定模式下的正式入口，不要在 Skill 内直接调用 Amazon HTTP 接口
- 认证检查仍然是强制门禁，具体门禁流程以对应 reference 文档为准
- 若目标是后端设计，优先使用商品页快照、payload、搜索结果、schema 四类能力取样
- 搜索结果页的 `review_count_value` 视为近似值；商品页抓取结果更适合作为精确快照值
