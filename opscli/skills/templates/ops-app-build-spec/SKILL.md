---
name: ops-app-build-spec
description: 基于统一 AppHub 模板仓库创建、开发或迁移内部 Web 应用，以后端设计和 OpenAPI 合同为主统一前后端开发、取数、安全、迁移和源码交付规范。
---

# OPS 应用模板开发

统一模板仓库：`http://10.1.13.143:3000/aukeys-admin/template`，分支：`master`。

新项目通过统一模板仓库 clone 获取完整模板，但不得继承模板仓库的 Git 元数据。Skill 提供安全 clone 脚本，在 clone 成功后立即删除并验证项目根目录 `.git`；Skill 不再生成项目脚手架，只负责维护会随 opscli 发版更新的项目级规范和平台限制。

## 规范归属

- 当前 Skill 是跨项目红线、SQLite、opscli 接入、真实取数、安全、迁移和源码交付规则的维护源。
- 具体应用以后端实现为事实源：目标项目的 `backend/CLAUDE.md`、`docs/apphub-contract.md`、生成的 OpenAPI 和实际路由共同定义前后端合同。
- 前端规范只约束前端实现，不得另行定义 API 路径、响应信封、错误码、鉴权或字段语义。
- 目标项目可以补充业务规则，但不得弱化当前 Skill 的强制限制。
- 目录现状、辅助函数、依赖版本和具体命令以目标项目实际代码为准；发现与 Skill 冲突时先列出证据，不静默覆盖。
- `assets/backend/` 只保存项目规范模板，不包含应用代码、数据库、构建或部署脚手架。

## 按需读取

| 场景                                         | 读取                                                                |
| -------------------------------------------- | ------------------------------------------------------------------- |
| 修改纯前端页面、组件或状态                   | `references/frontend-standard.md`                                   |
| 修改前端请求、错误处理或前后端共享类型       | `references/frontend-standard.md`、`references/backend-redlines.md` |
| 修改 FastAPI API、服务、任务或配置           | `references/backend-redlines.md`                                    |
| 修改 SQLite 模型、事务、迁移或备份           | `references/sqlite-standard.md`                                     |
| 后端调用 opscli SDK 或 REST                  | `references/opscli-integration-standard.md`                         |
| 页面使用 OPS、Keepa、SellerSprite 或组合数据 | `references/data-access-standard.md`                                |
| 迁移或同步项目规范                           | `references/migration-standard.md`                                  |
| 创建应用、绑定仓库、提交源码或检查交付条件   | `references/deployment-standard.md`                                 |

不要加载与当前任务无关的参考文件。普通开发不读取 `assets/` 中的全文规范。

## 新项目

1. 确认应用展示名称，并确认目标目录不存在或为空。
2. 使用当前 Skill 根目录下的安全脚本克隆模板；将 `<skill-directory>` 替换为当前 `ops-app-build-spec` Skill 的绝对路径：

   ```bash
   python "<skill-directory>/scripts/clone_template.py" "<project-directory>"
   ```

   脚本直接 clone 到目标目录，成功后立即删除项目根目录 `.git` 并验证其不存在；不删除 `.gitignore`，不使用临时目录。任一步失败都停止，禁止手动跳过清理继续开发。

3. 模板源码准备成功后立即创建 AppHub 应用并写入本地 binding：

   ```bash
   opscli app create "<app-name>" --path "<project-directory>" --json
   ```

4. `create` 成功后立即初始化全新 Git 仓库并绑定 AppHub 业务仓库：

   ```bash
   opscli app init "<project-directory>" --json
   ```

5. 核对分支、HEAD 和 `origin`，确认 `origin` 不指向统一模板仓库；确认 `.opscli/app.json`、`app.yaml`、`AGENTS.md`、`frontend/`、`backend/app.py`、`backend/CLAUDE.md` 和 `docs/apphub-contract.md` 存在，且 `.opscli/app.json.slug == app.yaml.name`。
6. 开发前读取目标项目的 `AGENTS.md`、`docs/apphub-contract.md`、`backend/CLAUDE.md` 和 `README.md`。

新项目只通过安全 clone 脚本获取模板，不使用 `opscli app create/init` 代替 clone；但 clone 并脱离模板 Git 元数据、`create` 和 `init` 是开始开发前连续执行的必需步骤。任一步失败都停止后续开发，并按错误处理规范保留证据；业务代码不得推回模板仓库。

不得运行项目生成器、手写替代脚手架，或从 Skill 复制应用代码和发布资产。

## 识别模板项目

业务项目绑定自己的远端后，不能只根据 remote 判断。满足以下合同即可在原项目继续开发：

- 根目录包含 `app.yaml`、`AGENTS.md` 和 `docs/apphub-contract.md`。
- 存在 `frontend/`、`backend/app.py` 和 `backend/CLAUDE.md`。
- `app.yaml` 的 runtime、entrypoint 与项目内合同一致。
- 项目使用模板约定的单 FastAPI 应用入口，没有另建 Nginx 或前后端双服务发布结构。

合同缺失时读取迁移规范，不在原目录重新初始化或批量覆盖。

## 开发与规范同步

- 无论新项目还是已绑定项目，开发前都先读取目标项目的 `AGENTS.md`、`backend/CLAUDE.md`、`docs/apphub-contract.md` 和 `README.md`。
- 修改前端、后端、SQLite 或 opscli 接入时读取对应规范，只执行与当前改动相关的条款。
- 前端请求或共享类型变化时，先确认后端路由、Schema 和 OpenAPI，再改前端；不得用前端兼容分支掩盖后端合同漂移。
- 页面需要真实业务数据时必须读取取数规范并使用 `$ops-app-data-builder`；不选择或猜测数据集、字段、聚合、筛选、第三方场景、凭证、SDK 签名或运行时入口。
- 前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite；所有线上取数都经过当前站点 FastAPI `/api`。
- 只修改当前业务需要的代码，保留用户已有修改和模板基础能力。
- 不读取、输出或提交真实密钥、本地数据库和业务数据文件。
- 用户未授权时，不安装依赖、启动服务、执行数据库写入、提交、推送或部署。
- `app.yaml`、Git 根和 `master` 分支是否满足发布前置。
- # 支持结论、迁移风险、未识别项及预计文件变更。
- 页面真实数据用途、现有数据源、调用路径和前端直连或凭证风险。
- 第三方原始数据、SellerSprite 异步任务和用户私有加工结果是否正确分层。

克隆项目已有规范文件时，以当前 Skill 规则约束本次开发，不为了同步而覆盖项目特有内容。迁移项目缺少规范时，可按迁移规范使用 `assets/backend/` 补齐：

- `assets/backend/AGENTS.md` → `backend/AGENTS.md`
- `assets/backend/CLAUDE.md` → `backend/CLAUDE.md`
- `assets/backend/docs/开发指南/*.md` → `docs/开发指南/*.md`

同步前展示差异，只更新规范文件，并保留目标项目的业务说明和特有约定。

## 迁移项目

先判断目标是否已经符合模板合同。需要迁移时读取迁移规范，在独立模板目录中搬运业务能力；源项目保持可回退。

## 提交与部署

首次源码交付或后续推送时读取部署规范。Skill 负责配置校验、当前 opscli 命令边界和提交前检查；源码推送后的构建、自动 release、健康状态和回滚由线上 AppHub 处理。Skill 不绕过 `opscli app push` 直接 Push，也不调用 release 创建接口生成第二条 release。

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
- 第一阶段不增加运行时数据 YAML，避免形成第二套配置权威源。
- `docs/ops-app/development.md`：本地开发、环境变量和联调方式。
- `docs/ops-app/deployment.md`：构建、持久化、发布检查和回滚说明。
- 根目录 `AGENTS.md`：只写简短受管区块，引用上述规范；已有文件时保留其他内容。

保留现有前端包管理器及唯一锁文件。依赖安装、服务启动、数据库迁移和发布仍遵守当前宿主的授权要求。

### 5. 唯一发布声明

根目录 `app.yaml` 是应用发布声明的唯一来源。模板中的 `name/title` 只是示例身份；执行 `opscli app create` 后，以 AppHub 返回的真实 `slug` 和创建时确认的展示名称回填 `app.yaml.name/title`。其他运行时、入口、服务、数据集和可见范围字段按项目实际需求维护；保持：

```yaml
apiVersion: apps.aukeys/v1
database:
  kind: sqlite
  path: /data/app.db
```

禁止在应用代码、环境文件、构建文件或前端配置中重复维护平台身份、公开前缀或发布地址。`app.yaml` 必须位于独立 Git 仓库根目录，发布分支必须为 `master`；模板源目录嵌套在另一个仓库中时先迁出并初始化独立仓库。

首次源码交付前确认根目录存在 `.opscli/app.json`，binding 中具有有效 `app_id` 和 `slug`，且 `.opscli/app.json.slug == app.yaml.name`。`app_id`、仓库、Owner 和 Git 信息只保留在本地 binding，不写入 `app.yaml`；`.gitignore` 必须忽略 `.opscli/`。

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
- SQLite 只读取 `SQLITE_PATH`；模板库为 `data/app.db`，本地运行库为已忽略的 `.data/app.db`，容器运行库为 `/data/app.db`。平台只把命名卷挂到 `/data`，不注入数据库路径变量。

### 7. 构建与源码交付

项目构建合同以 AppHub 的 Nixpacks 运行环境为准：

- `nixpacks.toml` 分别在 `install` 与 `python:install` 使用 `...` 保留 Node/Python provider 计划；平台 SDK 导入门禁追加到 `python:install`，Vite 构建显式依赖两个安装阶段，并以平台同款命令启动 FastAPI。
- 根目录 `requirements.txt` 中普通第三方依赖使用 `==` 精确锁定；平台 SDK 使用真实包 `aukeys-opscli>=0.0.129`，并在构建阶段验证 `import opscli.app`。若索引中尚无兼容正式版本，停止源码交付并联系 IT，不得用本地同名包绕过。
- 禁止创建本地 `opscli/` 包、同名模块或路径依赖来绕过真实包安装。
- `Dockerfile` 只用于本地、CI 和可复现构建，不改变 AppHub 的 Nixpacks 运行合同。
- 启动命令为 `uvicorn backend.app:app --host 0.0.0.0 --port 8000`，数据库初始化和迁移遵循项目合同与 AppHub 运行时能力，不调用已废弃的项目侧部署命令。
- 平台健康检查固定为 `/__apphub_healthz`，必须快速返回 200，且不依赖业务查询。

源码交付前必须确认：

- `app.yaml` 能通过当前 schema，入口文件存在，Git 根独立且当前分支为 `master`。
- `requirements.txt` 的普通依赖全部精确锁定，真实 `aukeys-opscli` 通过兼容模块导入检查。
- 前端测试和生产构建、后端测试、健康检查通过。
- Nixpacks 与 Dockerfile 的构建产物、启动模块、端口和健康路径一致。
- 构建产物使用相对 URL，根路径页面、静态资源、SPA 刷新、API 和 WebSocket 可用。
- `.data/` 和 SQLite 文件不进入源码或构建产物。
- 根目录 `.gitignore` 忽略 `.opscli/`，`.opscli/app.json` 未被跟踪或暂存；`app.yaml` 必须保留在源码中。
- 根目录 `.dockerignore` 排除依赖目录、构建缓存、本地数据库、环境文件和密钥，同时保留 `app.yaml`、锁文件、源码和必要构建资产。
- Dockerfile 使用精确 `COPY` 分层和 BuildKit 缓存；禁止无边界 `COPY . .`，但必须复制依赖清单、锁文件、源码和必要配置。
- 后端依赖统一使用 `uv`、`pyproject.toml`、`uv.lock`；项目不得自行派生 AppHub 公开路径、Compose service 名或线上镜像名。
- 模板项目开发只要求 Node.js 主版本大于 22；补丁版本 engine 警告允许记录到评估文档，不作为构建或测试的阻断条件。
- 前后端构建、测试和健康检查通过。
- 构建产物引用部署前缀，本地开发仍使用根路径。
- SPA 嵌套路由刷新、API 访问和容器重启后的数据持久化通过。
- 前端只调用当前站点 `/api`，没有直连 OPS、opscli REST、Keepa 或 SellerSprite。
- `VITE_*`、源码、构建产物、日志和 SQLite 中没有 API Key、JWT、Cookie 或完整鉴权头。
- OPS 使用实际项目中经过批准的应用运行时身份适配器，未隔离的 viewer 数据没有写入共享 SQLite。
- Keepa 页面运行时只使用正式 `POST /api/v1/keepa/run`，请求级 `ThirdPartyApiClient` 复用模板 `get_query_credentials()` 解析出的 `viewer/session/local` 身份。
- SellerSprite 使用正式异步 jobs 或 Listing Analysis 接口，按当前 `owner_user_id` 持久化并复用 pending `job_id`，成功 JSON 结果只进入当前用户私有快照。
- Keepa 和 SellerSprite 只共用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`；生产注入 `https://ops.mcp.xenkee.com`，预发布注入 `https://ops.api.qa.aukeyit.com`，不得设置默认环境、读取共享 API Key 或旧变量别名。
- 第三方调用只从已校验的 `QueryCredentials` 重建允许的 Header，不盲目透传浏览器 Header，不把凭证写入请求体、前端、日志、SQLite 或源码，也不在三种模式间回退。
- `third_party_source_snapshot` 和 `third_party_async_job` 都使用 `UNIQUE(owner_user_id, provider, request_hash)`；XLS/XLSX 和临时下载 URL 不写入 SQLite。
- `docs/ops-app/data-spec.md` 与实际 Pydantic Schema、前端类型、迁移和运行时能力一致。

未获得启动服务许可时，只执行静态检查、测试和构建，不启动容器。

源码交付获得用户确认后，由 Codex 执行 `opscli app push <root> --message <summary>`。该命令成功只表示源码到达应用远端仓库，随后 `opscli app` 职责结束。
应用发布、构建排队、版本状态、线上 URL、健康检查和回滚由 AppHub 或其他发布平台负责，本 Skill 不调用或指导调用 `opscli app` 发布命令。
没有线上平台证据时，不得把 push、构建或镜像生成报告成已发布或已部署。

## 错误处理

- 模板克隆或 `.git` 清理验证失败：保留原始错误并停止，不退回旧脚手架，不执行 `create/init`。
- 模板合同冲突：列出证据和影响，不猜测。
- 迁移无法保持业务行为：停止迁移，保留源实现和失败证据。
- `opscli` CLI 或 MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。
- 数据合同无法验证、OPS 运行时适配器缺失、第三方场景未验证或结果格式不支持目标数据产品：保留已验证部分，在 data-spec 标记阻塞，不伪造调用代码。

## 输出

简要报告模板识别、规范同步、修改文件、实际验证、交付状态和阻塞项。未执行的测试、构建或线上部署不得写成通过。
