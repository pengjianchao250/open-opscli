---
name: ops-app-build-spec
description: 用于新建站点、新建看板、从零开发运营数据应用或改造未知 Web 项目；全新 opscli app 必须先通过 app create/init 拉取模板，再盘点、开发和执行发布检查，已有项目按受支持技术栈规范化。
---

# OPS 应用规范与发布初始化

面向不了解现有代码结构的业务开发者。先用仓库证据识别项目，再生成规范、迁移受支持技术栈，并准备当前 AppHub 可发布产物。

## Reference 路由

| 场景                 | 必须读取                                |
| -------------------- | --------------------------------------- |
| 判断或改造前端       | `references/frontend-standard.md`       |
| 全新站点模板初始化   | `references/initialization-standard.md` |
| 新建或改造后端       | `references/backend-standard.md`        |
| 页面需要真实业务数据 | `references/data-access-standard.md`    |
| 现有项目不是目标结构 | `references/migration-standard.md`      |
| 初始化发布或首次发布 | `references/deployment-standard.md`     |

只读取当前阶段需要的文档。进入迁移时同时读取目标端规范；进入发布时读取全部与实际运行路径相关的规范。

## 必要输入

- 项目根目录。
- 操作意图：`检查`、`初始化/迁移` 或 `发布检查`。用户未明确时，根据动词判断；仍有歧义才询问。
- 应用名称。优先读取 `app.yaml`、现有包名或仓库名；无法得到唯一 URL 安全名称时询问。

应用名称只允许 3-64 位小写字母、数字和连字符，必须以字母开头、字母或数字结尾。发布身份和公开地址由 AppHub 管理，应用代码不得保存或派生平台身份字段。

## 执行流程

### 0. 新项目模板门禁

用户表达新建站点、新建看板、从零开发运营数据应用等意图时，本 Skill 作为统一建站入口，
先判断目标目录是全新项目还是已有源码项目。该判断必须发生在写入任何项目文件之前。

全新 opscli app 必须按以下顺序执行：

```text
opscli app create "<站点显示名称>" --path <项目根目录>
opscli app init <项目根目录>
确认首次初始化返回 template_applied=true
重新读取模板项目并进入只读盘点
```

在 `app init` 成功前，不得提前写入 `assessment.md`、README、需求文档、前后端、
`app.yaml`、配置或部署文件，也不运行 `pnpm create vue` 或其他脚手架。需求内容暂时
保留在会话或项目目录之外。模板是唯一基线；模板缺少必需结构时停止并报告模板问题，
不得静默生成另一套项目。

全新项目在模板完成前只执行上述门禁和命令编排，不进入后续写文件步骤；模板完成后由同一个
Skill 重新盘点并继续正式开发，不使用初始化前的空目录结论。已有源码项目进入既有盘点和迁移流程，后续
`opscli app init` 会保留源码并跳过模板。

### 1. 只读盘点

读取 Git 根、当前分支、依赖清单、锁文件、入口、路由、静态资源、环境变量示例、API、数据库、测试、构建配置和现有发布文件。不得仅凭目录名判断技术栈，不读取或输出真实密钥。

将证据和结论写入 `docs/ops-app/assessment.md`，至少包含：

- 当前前端、后端、数据库和包管理器。
- 关键入口、构建命令与运行方式。
- `app.yaml`、Git 根和 `main` 分支是否满足发布前置。
- # 支持结论、迁移风险、未识别项及预计文件变更。
- 页面真实数据用途、现有数据源、调用路径和前端直连或凭证风险。
- 支持结论、迁移风险和未识别项。
- 预计新增、修改、保留的文件。

### 2. 技术栈路由

| 当前项目         | 处理方式                                            |
| ---------------- | --------------------------------------------------- |
| Vite + React     | 保留 React，按前端规范补齐                          |
| Vite + Vue 3     | 保留 Vue 3，按前端规范补齐                          |
| Next.js + React  | 按迁移规范转换为 Vite + React                       |
| 普通 HTML/CSS/JS | 转换为 Vite + Vue 3 + Element Plus                  |
| 无后端           | 创建最小 FastAPI 托管入口，不虚构业务接口或业务数据 |
| FastAPI + SQLite | 按后端规范补齐                                      |

Vue 2、其他前端框架、非 FastAPI 后端和任何非 SQLite 数据库，均停止自动改造。列出识别证据、保留现状并告诉用户：`当前技术栈不在自动迁移范围，请联系 IT 人员处理。`

Next.js 仅自动迁移能保持客户端行为的项目。发现 SSR、RSC、ISR、Server Actions、Edge Runtime 或 Middleware 等服务端语义时，按迁移规范停止，不做表面替换。

### 3. 生成迁移计划

`检查`模式到此停止并返回评估文件。`初始化/迁移`模式继续生成 `docs/ops-app/migration-plan.md`，列出页面、路由、接口、数据、加工、存储和部署映射。大范围移动、覆盖或删除文件前必须取得用户明确确认。

### 3.1 真实数据层路由

发现页面需要 OPS、Keepa、SellerSprite 或组合数据时，读取 `references/data-access-standard.md` 并使用 `$ops-app-data-builder`。向其传递项目根目录、页面业务需求和已确认范围，由它验证真实合同并生成或改造站点数据层。

本 Skill 只负责识别和委托，不选择或猜测数据集、字段、聚合、筛选、第三方场景、SDK 导入路径或运行时方法签名。`检查`模式只记录需求和风险，不执行数据层改造。

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

- 识别证据冲突：列出冲突并询问，不猜测。
- 迁移后行为不一致：停止后续迁移，保留失败证据，不删除旧实现。
- 项目注册工具或 `opscli`/MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。
- 数据合同无法验证、OPS 运行时适配器缺失或 SellerSprite 没有正式入口：保留已验证部分，在 data-spec 标记阻塞，不伪造调用代码。
- 部分写入或发布状态不确定：重新读取本地状态后停止，不重复创建项目或重复发布。

## 输出规范

最终回复只包含：识别结果、支持结论、完成的规范/迁移/发布文件、验证结果、阻塞项和需要用户执行的下一步。不得把未运行的构建、容器或浏览器检查写成已通过。
