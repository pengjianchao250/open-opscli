---
name: ops-app-build-spec
description: 基于统一 AppHub 模板创建、开发或迁移内部 Web 应用，并按当前 opscli 版本约束前后端开发、真实数据访问、源码提交和线上部署边界。
---

# OPS 应用模板开发

统一模板仓库：`http://10.1.13.143:3000/aukeys-admin/template`，分支：`main`。

模板项目负责目录结构、具体开发命令、依赖版本、数据库实现和本地运行说明。当前 Skill 负责跨项目最低开发规范，以及会随 opscli 发版更新的取数、平台、安全、迁移和交付限制。

发生冲突时：项目结构、辅助函数和具体命令以目标项目内规范为准；前后端底线、取数、凭证、安全、AppHub 平台和源码交付限制以当前 Skill 为准。不要静默覆盖，先列出冲突和需要调整的文件。

## 按需读取

| 场景 | 读取 |
| --- | --- |
| 修改前端页面、组件、状态或请求 | `references/frontend-standard.md` |
| 修改 FastAPI API、服务、任务或配置 | `references/backend-standard.md` |
| 页面使用 OPS、Keepa、SellerSprite 或组合数据 | `references/data-access-standard.md` |
| 现有项目不符合模板合同 | `references/migration-standard.md` |
| 创建应用、绑定仓库、提交源码或检查部署条件 | `references/deployment-standard.md` |

不要加载与当前任务无关的参考文件。

## 新项目

1. 确认目标目录不存在或为空。
2. 克隆模板：

   ```bash
   git clone --branch main --single-branch http://10.1.13.143:3000/aukeys-admin/template "<project-directory>"
   ```

3. 核对 remote、分支和 HEAD，并确认 `app.yaml`、`AGENTS.md`、`frontend/`、`backend/`、`docs/apphub-contract.md` 存在。
4. 开发前读取目标项目的 `AGENTS.md`、`docs/apphub-contract.md`、`backend/CLAUDE.md` 和 `README.md`。

不得运行项目生成器、手写替代脚手架或从 Skill 复制项目文件。克隆后的 `origin` 指向模板仓库，业务代码不得推回模板仓库。

## 识别模板项目

业务项目绑定自己的远端后，不能只根据 remote 判断。满足以下合同即可在原项目继续开发：

- 根目录包含 `app.yaml`、`AGENTS.md` 和 `docs/apphub-contract.md`。
- 存在 `frontend/`、`backend/app.py` 和 `backend/CLAUDE.md`。
- `app.yaml` 的 runtime、entrypoint 和项目内合同一致。
- 项目仍使用模板约定的单应用入口，没有另建一套 AppHub 发布结构。

合同缺失时读取迁移规范，不在原目录重新初始化或覆盖。

## 开发项目

- 目录、辅助函数、测试命令和数据库迁移方式直接遵循目标项目规范。
- 修改前端或后端时读取对应简要规范，只执行与当前改动相关的条款。
- 只修改当前业务需要的代码，保留用户已有修改和模板基础能力。
- 不读取、输出或提交真实密钥、本地数据库和业务数据文件。
- 页面涉及真实数据时必须读取取数规范；不得凭经验猜测数据集、接口、凭证或 SDK 调用。
- 用户未授权时，不安装依赖、启动服务、执行数据库写入、提交、推送或部署。

前后端参考只保留跨项目强制规则，不复制模板的完整开发手册。数据库实现和迁移步骤由目标项目随代码维护。

## 迁移项目

先识别目标是否已经符合模板合同。需要迁移时读取迁移规范，在独立模板目录中搬运业务能力；源项目保持可回退。

## 提交与部署

用户要求创建应用、绑定仓库、提交源码或部署时读取部署规范。Skill 负责当前 opscli 命令边界和提交前检查；源码推送后的构建、发布、健康状态和回滚由线上 AppHub 处理。

没有线上证据时，不得把 push、构建排队或镜像生成报告成已部署。

## 错误处理

- 模板克隆失败：保留 Git 原始错误并停止，不退回旧脚手架。
- 模板合同冲突：列出证据和影响，不猜测。
- 迁移无法保持业务行为：停止迁移，保留源实现和失败证据。
- `opscli` CLI 或 MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。

## 输出

简要报告模板识别、修改文件、实际验证、交付状态和阻塞项。未执行的测试、构建或线上部署不得写成通过。
