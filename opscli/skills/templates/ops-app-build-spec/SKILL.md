---
name: ops-app-build-spec
description: 用于盘点未知 Web 项目、生成项目规范，并将受支持项目规范化为 Vite + React/Vue、FastAPI + SQLite 和 AppHub 单应用发布结构；遇到不支持的技术栈时停止并提示联系 IT。
---

# OPS 应用规范与发布初始化

面向不了解现有代码结构的业务开发者。先用仓库证据识别项目，再生成规范、迁移受支持技术栈，并准备当前 AppHub 可发布产物。

## Reference 路由

| 场景 | 必须读取 |
| --- | --- |
| 判断或改造前端 | `references/frontend-standard.md` |
| 空项目初始化 | `references/initialization-standard.md` |
| 新建或改造后端 | `references/backend-standard.md` |
| 现有项目不是目标结构 | `references/migration-standard.md` |
| 初始化发布或首次发布 | `references/deployment-standard.md` |

只读取当前阶段需要的文档。进入迁移时同时读取目标端规范；进入发布时读取全部与实际运行路径相关的规范。

## 必要输入

- 项目根目录。
- 操作意图：`检查`、`初始化/迁移` 或 `发布检查`。用户未明确时，根据动词判断；仍有歧义才询问。
- 应用名称。优先读取 `app.yaml`、现有包名或仓库名；无法得到唯一 URL 安全名称时询问。

应用名称只允许 3-64 位小写字母、数字和连字符，必须以字母开头、字母或数字结尾。发布身份和公开地址由 AppHub 管理，应用代码不得保存或派生平台身份字段。

## 执行流程

### 1. 只读盘点

读取 Git 根、当前分支、依赖清单、锁文件、入口、路由、静态资源、环境变量示例、API、数据库、测试、构建配置和现有发布文件。不得仅凭目录名判断技术栈，不读取或输出真实密钥。

将证据和结论写入 `docs/ops-app/assessment.md`，至少包含：

- 当前前端、后端、数据库和包管理器。
- 关键入口、构建命令与运行方式。
- `app.yaml`、Git 根和 `main` 分支是否满足发布前置。
- 支持结论、迁移风险、未识别项及预计文件变更。

### 2. 技术栈路由

| 当前项目 | 处理方式 |
| --- | --- |
| Vite + React | 保留 React，按前端规范补齐 |
| Vite + Vue 3 | 保留 Vue 3，按前端规范补齐 |
| Next.js + React | 按迁移规范转换为 Vite + React |
| 普通 HTML/CSS/JS | 转换为 Vite + Vue 3 + Element Plus |
| 无后端 | 创建最小 FastAPI 托管入口，不虚构业务接口或业务数据 |
| FastAPI + SQLite | 按后端规范补齐 |

Vue 2、其他前端框架、非 FastAPI 后端和任何非 SQLite 数据库，均停止自动改造。列出识别证据、保留现状并告诉用户：`当前技术栈不在自动迁移范围，请联系 IT 人员处理。`

Next.js 仅自动迁移能保持客户端行为的项目。发现 SSR、RSC、ISR、Server Actions、Edge Runtime 或 Middleware 等服务端语义时，按迁移规范停止，不做表面替换。

### 3. 生成迁移计划

`检查`模式到此停止并返回评估文件。`初始化/迁移`模式继续生成 `docs/ops-app/migration-plan.md`，列出页面、路由、接口、数据和发布映射。大范围移动、覆盖或删除文件前必须取得用户明确确认。

### 4. 规范化项目

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

只创建实际使用的目录和功能。空项目可以生成最小托管入口与平台健康路由，但不得生成虚假业务接口、业务表或示例生产数据。

生成或更新：

- `docs/ops-app/project-spec.md`：当前技术栈、目录、命令、路由、接口、数据和约束。
- `docs/ops-app/development.md`：本地开发、环境变量和联调方式。
- `docs/ops-app/deployment.md`：构建、持久化、发布检查和回滚说明。
- 根目录 `AGENTS.md`：只写简短受管区块，引用上述规范；已有文件时保留其他内容。

保留现有前端包管理器及唯一锁文件。依赖安装、服务启动、数据库迁移和发布仍遵守当前宿主的授权要求。

### 5. 唯一发布声明

根目录 `app.yaml` 是应用发布声明的唯一来源。初始化时复制 `assets/app.yaml`，再按实际应用修改 `name`、展示信息、数据集和可见范围；保持：

```yaml
apiVersion: apps.aukeys/v1
runtime: fastapi
python: "3.11"
entrypoint: backend/app.py
services:
  sqlite: true
```

禁止在应用代码、环境文件、构建文件或前端配置中重复维护平台身份、公开前缀或发布地址。`app.yaml` 必须位于独立 Git 仓库根目录，发布分支必须为 `main`；模板源目录嵌套在另一个仓库中时先迁出并初始化独立仓库。

同时复制根级资产：

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

未获得启动服务许可时，只执行静态检查、测试和构建，不启动容器或发布应用。

## 错误处理

- 识别证据冲突：列出冲突并询问，不猜测。
- 迁移后行为不一致：停止后续迁移，保留失败证据，不删除旧实现。
- 项目注册工具或 `opscli`/MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。
- 部分写入或发布状态不确定：重新读取本地状态后停止，不重复创建项目或重复发布。

## 输出规范

最终回复只包含：识别结果、支持结论、完成的规范/迁移/发布文件、验证结果、阻塞项和需要用户执行的下一步。不得把未运行的构建、容器或浏览器检查写成已通过。
