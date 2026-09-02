# AGENTS.md

> 本文件面向所有 AI 编码助手（Codex / Cursor / Copilot / Claude Code 等）。

## 唯一事实来源：`CLAUDE.md`

本仓库的开发规范**全部**写在同目录的 [`CLAUDE.md`](./CLAUDE.md) 中。
本文件**只做引用指向，不重复任何规范内容**——避免两份文档各写一份、随时间漂移。

**你必须先完整阅读 [`./CLAUDE.md`](./CLAUDE.md)，并严格遵循其中的全部内容后，再开始任何工作。**

如果你的工具不会自动加载 `CLAUDE.md`，请显式读取该文件。

`CLAUDE.md` 涵盖：项目概述与目录结构 · 环境准备与常用命令 · 架构要点（分层、事务边界、单一事实来源）·
代码规范（通用 / API / 数据库 ORM / 异步 / 定时任务 / 错误处理与日志 / 配置与依赖）· 开发铁律 ·
测试指引 · 数据库迁移指引 · 隔离环境规范 · 提交与 PR 规范 · 硬性禁令 · 工作方式 · 红线速查。

## 配套文档

| 文档 | 内容 |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | **本仓库规范唯一事实来源**，先读它 |
| [`docs/开发指南/FastAPI后端开发通用规范.md`](./docs/开发指南/FastAPI后端开发通用规范.md) | 通用工程规范全文：完整论述、代码模板、反模式清单 |
| [`docs/开发指南/SQLite数据库使用通用规范.md`](./docs/开发指南/SQLite数据库使用通用规范.md) | 使用 SQLite 时的专项规范 |
| [`docs/开发指南/OPSCLI_SDK调用规范.md`](./docs/开发指南/OPSCLI_SDK调用规范.md) | 进程内导入 opscli SDK 的授权与调用约束 |
| [`docs/开发指南/OPSCLI_SDK使用文档.md`](./docs/开发指南/OPSCLI_SDK使用文档.md) | opscli SDK 类与方法参考 |
| [`docs/开发指南/OPSCLI_API调用规范.md`](./docs/开发指南/OPSCLI_API调用规范.md) | 通过 HTTP 调用 opscli 服务端的纪律 |
| [`docs/开发指南/OPSCLI_API使用文档.md`](./docs/开发指南/OPSCLI_API使用文档.md) | opscli REST 端点参考 |
| `docs/API规范/openapi.json` | 接口契约（由应用生成，禁止手工编辑） |

`CLAUDE.md` 与全文规范冲突时，以 `docs/开发指南/` 下的通用开发规范为准。

## 维护约定

- 规范有任何增删改，**只改 `CLAUDE.md`**；本文件除文档索引外不新增内容。
- 发现本文件与 `CLAUDE.md` 出现内容重复，说明有人改错了地方，应删除本文件中的重复部分。
