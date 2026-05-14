---
name: ops-auth
description: 根据当前环境自动选择 CLI 或 MCP 方式处理 Aukeys 内部系统认证与 Token 管理
version: v1.0.2
---

# ops-auth

用于管理 Aukeys 内部系统的 OAuth2 登录授权、JWT Token、系统列表和认证诊断。

---

## 何时使用本 Skill

- 需要通过 Device Flow 完成首次登录授权
- 需要获取、校验、刷新各系统的 JWT
- 遇到 401、未登录、Token 过期等认证报错
- 需要查看、添加、同步、移除已注册系统
- 需要在脚本或其他 Skill 前置环节确认认证状态

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

优先级如下：

1. 如果用户明确要求使用 CLI 或 MCP，直接遵循用户指定
2. 如果当前就在 `opscli` 项目、本地终端可直接执行正式命令，默认使用 CLI，并读取 `references/cli.md`
3. 如果当前任务本身就是基于 MCP Tool 协作，或明显无法直接走本地 CLI，再读取 `references/mcp.md`
4. 如果一开始按 CLI 执行首个正式命令就失败（例如 `opscli auth ...` 不可用、当前宿主不适合跑本地命令），直接切换到 MCP 版本，并读取 `references/mcp.md`
5. 如果 MCP 版本也不可用（例如当前没有可用 MCP 服务、认证工具未注册、调用宿主不支持 MCP），再回退为帮助用户安装 `aukeys-opscli`

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

- 认证动作必须统一走选定模式下的正式入口，不要绕过 Skill 直接拼接鉴权请求
- `ops-auth` 是 `ops-amazon`、`ops-dataset-query` 等 Skill 的前置依赖，出现认证异常时应优先回到本 Skill
- 认证检查、Token 刷新、系统同步和诊断流程都以对应 reference 文档为准
