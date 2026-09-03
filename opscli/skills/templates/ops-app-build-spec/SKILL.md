---
name: ops-app-build-spec
description: 用于新建站点、新建看板、从零开发运营数据应用或改造未知 Web 项目；全新 opscli app 必须先通过 app create/init 拉取模板，再盘点、开发和执行发布检查，已有项目按受支持技术栈规范化。
---

# OPS 应用模板开发

统一模板仓库：`http://10.1.13.143:3000/aukeys-admin/template`，分支：`main`。

模板项目负责目录结构、具体开发命令、依赖版本、数据库实现和本地运行说明。当前 Skill 负责跨项目最低开发规范，以及会随 opscli 发版更新的取数、平台、安全、迁移和交付限制。

| 场景                                    | 必须读取                                                                                                       |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 判断或改造前端                          | `references/frontend-standard.md`                                                                              |
| 全新站点模板初始化                      | `references/initialization-standard.md`                                                                        |
| 新建或改造后端                          | `references/backend-standard.md`                                                                               |
| 后端 SQLite 细则、调用 opscli、红线总表 | `references/sqlite-standard.md`、`references/opscli-integration-standard.md`、`references/backend-redlines.md` |
| 页面需要真实业务数据                    | `references/data-access-standard.md`                                                                           |
| 现有项目不是目标结构                    | `references/migration-standard.md`                                                                             |
| 初始化发布或首次发布                    | `references/deployment-standard.md`                                                                            |

## 按需读取

| 场景                                         | 读取                                 |
| -------------------------------------------- | ------------------------------------ |
| 修改前端页面、组件、状态或请求               | `references/frontend-standard.md`    |
| 修改 FastAPI API、服务、任务或配置           | `references/backend-standard.md`     |
| 页面使用 OPS、Keepa、SellerSprite 或组合数据 | `references/data-access-standard.md` |
| 现有项目不符合模板合同                       | `references/migration-standard.md`   |
| 创建应用、绑定仓库、提交源码或检查部署条件   | `references/deployment-standard.md`  |

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

发布态固定为一个 FastAPI 进程托管 Vite 构建产物、API 和健康检查：

```text
frontend/
backend/
migrations/
tests/
docs/ops-app/
app.yaml
requirements.txt
nixpacks.toml
Dockerfile
.dockerignore
.gitignore
```

只创建实际使用的目录和功能。全新 opscli app 必须在模板项目上改造，不自行初始化空项目或生成第二套脚手架；已有项目按支持结论补齐必要结构。任何项目都不得生成虚假业务接口、业务表或示例生产数据。

生成或更新：

- `docs/ops-app/project-spec.md`：当前技术栈、目录、命令、路由、接口、数据和约束。
- 有真实数据需求时生成 `docs/ops-app/data-spec.md`：数据产品、真实合同、执行模式、站点 API、加工、SQLite、安全、测试和阻塞项。
- `docs/ops-app/development.md`：本地开发、环境变量和联调方式。
- `docs/ops-app/deployment.md`：构建、持久化、发布检查和回滚说明。
- 根目录 `AGENTS.md`：只写简短受管区块，引用上述规范；已有文件时保留其他内容。

保留现有前端包管理器及唯一锁文件。依赖安装、服务启动、数据库迁移和发布仍遵守当前宿主的授权要求。

### 5. 唯一发布声明

根目录 `app.yaml` 是应用发布声明的唯一来源。全新项目校验并调整模板已有声明；已有项目迁移时才按计划使用 `assets/app.yaml` 补齐，再按实际应用修改 `name`、展示信息、数据集和可见范围；保持：

```yaml
apiVersion: apps.aukeys/v1
runtime: fastapi
python: "3.11"
entrypoint: backend/app.py
services:
  sqlite: true
```

禁止在应用代码、环境文件、构建文件或前端配置中重复维护平台身份、公开前缀或发布地址。`app.yaml` 必须位于独立 Git 仓库根目录，发布分支必须为 `main`；模板源目录嵌套在另一个仓库中时先迁出并初始化独立仓库。

全新项目从 `.opscli/app.json.app_id` 和 `.opscli/app.json.slug` 读取平台身份，分别写入或校验 `ops-app.config.appId` 和 `ops-app.config.appName`，不在首次发布阶段重新注册应用。

已有项目迁移时按计划补齐根级资产；全新模板缺少这些必需资产时报告模板问题，不静默复制另一套基线：

- `assets/nixpacks.toml` → `nixpacks.toml`
- `assets/Dockerfile` → `Dockerfile`
- `assets/requirements.txt` → `requirements.txt`
- `assets/.dockerignore` → `.dockerignore`

### 6. 运行合同

当前路由合同为 `root-v1`。浏览器公开前缀由平台在鉴权后移除，应用只接收根路径请求：

- Vite 固定 `base: './'`，路由、静态资源、Axios 和 WebSocket 使用相对 URL。
- FastAPI 先注册 `/__apphub_healthz`、`/api/*` 和 WebSocket，再挂载静态资源，SPA fallback 最后注册。
- FastAPI 不读取公开前缀，不设置框架子路径参数。
- Vite `dist` 由同一个 FastAPI 进程托管，不启动第二个生产 Web 进程。
- SQLite 只读取 `APP_DB_PATH`；本地开发默认使用已忽略的 `.data/app.db`，测试使用临时目录，线上由平台注入 `/data/app.db`。

### 7. 构建与发布

AppHub 发布主路径固定为 Nixpacks：

- `nixpacks.toml` 分别在 `install` 与 `python:install` 使用 `...` 保留 Node/Python provider 计划；平台 SDK 导入门禁追加到 `python:install`，Vite 构建显式依赖两个安装阶段，并以平台同款命令启动 FastAPI。
- 根目录 `requirements.txt` 中普通第三方依赖使用 `==` 精确锁定；平台 SDK 使用真实包 `aukeys-opscli>=0.0.129`，并在构建阶段验证 `import opscli.app`。若索引中尚无兼容正式版本，停止发布并联系 IT，不得用本地同名包绕过。
- 禁止创建本地 `opscli/` 包、同名模块或路径依赖来绕过真实包安装。
- `Dockerfile` 只用于本地、CI 和可复现构建，不改变 AppHub 的 Nixpacks 发布路径。
- 启动命令为 `python -m opscli.app.migrate && uvicorn backend.app:app --host 0.0.0.0 --port 8000`。
- 平台健康检查固定为 `/__apphub_healthz`，必须快速返回 200，且不依赖业务查询。

发布前必须确认：

- `app.yaml` 能通过当前 schema，入口文件存在，Git 根独立且当前分支为 `main`。
- `requirements.txt` 的普通依赖全部精确锁定，真实 `aukeys-opscli` 通过兼容模块导入检查。
- 前端测试和生产构建、后端测试、健康检查通过。
- Nixpacks 与 Dockerfile 的构建产物、启动模块、端口和健康路径一致。
- 构建产物使用相对 URL，根路径页面、静态资源、SPA 刷新、API 和 WebSocket 可用。
- `.data/` 和 SQLite 文件不进入源码或镜像；迁移通过 `opscli.app.migrate` 执行。
- `deployment/Dockerfile`、`deployment/compose.yaml`、`deployment/nginx.conf.template`、`deployment/ops-app-config.mjs`、`deployment/ops-app-config.d.mts`、`deployment/render-nginx-config.mjs` 存在；Dockerfile 同时提供前端、后端构建 target，并通过共享配置模块和渲染脚本生成项目内 Nginx 配置。
- 部署构建基线为 Linux 服务器：Compose 必须显式使用 `context: ..` 与 `dockerfile: deployment/Dockerfile`；本地宿主机兼容性问题只记录，不改变项目产物规范。
- 根目录 `.dockerignore` 存在，且没有排除构建必需的源码、锁文件、`ops-app.config` 或 deployment 资产。
- Vite 配置已导入 `deployment/ops-app-config.mjs`，Compose、Dockerfile 和环境变量中没有重复的应用 ID、应用名称或部署路径。
- Compose 同时声明前端、后端服务；SQLite 使用持久卷。
- Dockerfile 使用精确 `COPY` 分层和 BuildKit 缓存；禁止无边界 `COPY . .`，但必须复制依赖清单、锁文件、源码和部署模板。
- 后端依赖统一使用 `uv`、`pyproject.toml`、`uv.lock`；Nginx 以非 root 用户监听 `8080`；Dockerfile 不声明 `VOLUME`，持久卷只由 Compose 管理。
- 根目录 `.dockerignore` 排除依赖目录、构建缓存、本地数据库、环境文件和密钥，同时保留锁文件、配置和部署资产。
- Compose 使用最新 Compose Specification；前后端镜像名由 `ops-app.config` 派生为 `<appId>-<appName>-frontend|backend`，同时发布 `:sha-<git-sha>` 和 `:latest`，线上始终拉取 `:latest`。
- 模板项目开发只要求 Node.js 主版本大于 22；补丁版本 engine 警告允许记录到评估文档，不作为构建或测试的阻断条件。
- 前后端构建、测试、健康检查及 `docker compose config` 通过。
- 构建产物引用部署前缀，本地开发仍使用根路径。
- SPA 嵌套路由刷新、API 访问和容器重启后的数据持久化通过。
- 前端只调用当前站点 `/api`，没有直连 OPS、opscli REST、Keepa 或 SellerSprite。
- `VITE_*`、源码、镜像、Compose、日志和 SQLite 中没有 API Key、JWT、Cookie 或完整鉴权头。
- OPS 使用实际项目中经过批准的应用运行时身份适配器，未隔离的 viewer 数据没有写入共享 SQLite。
- Keepa 只使用正式 opscli REST 端点和后端 Secret；SellerSprite Mock 没有被当作真实线上接入。
- `docs/ops-app/data-spec.md` 与实际 Pydantic Schema、前端类型、迁移和运行时能力一致。

未获得启动服务许可时，只执行静态检查、测试和构建，不启动容器或发布应用。

发布检查通过且用户已授权发布时，由 Codex 执行 `opscli app push <root> --message <summary>`；本 Skill 不绕过该命令直接创建 release。

## 错误处理

- 模板克隆失败：保留 Git 原始错误并停止，不退回旧脚手架。
- 模板合同冲突：列出证据和影响，不猜测。
- 迁移无法保持业务行为：停止迁移，保留源实现和失败证据。
- `opscli` CLI 或 MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。

## 输出

简要报告模板识别、修改文件、实际验证、交付状态和阻塞项。未执行的测试、构建或线上部署不得写成通过。
