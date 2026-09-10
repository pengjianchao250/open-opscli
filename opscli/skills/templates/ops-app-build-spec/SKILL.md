---
name: ops-app-build-spec
description: AppHub 模板业务项目的开发规范。创建、开发、排错、评审、迁移或推送源码时使用，约束前端维护、项目边界和源码交付；按任务读取相关后端与数据规范。
---

# OPS 应用模板开发

统一模板仓库：`http://10.1.13.143:3000/aukeys-admin/template`，分支：`master`。模板提供应用代码和发布资产，Skill 维护跨项目开发规则；不另建脚手架。

## 规范归属与读取

- 具体应用以后端实现为事实源：目标项目的 `backend/CLAUDE.md`、`docs/apphub-contract.md`、生成的 OpenAPI 和实际路由共同定义前后端合同。前端不得另行定义协议。
- 目录、依赖、命令和辅助函数以目标项目实际代码为准。发现 Skill、项目文档与代码冲突时列出证据和影响，不静默覆盖配置或用兼容分支掩盖漂移。
- 项目可补充业务约定；通用规则只在 Skill 维护，平台运行合同只在项目合同维护，避免多份文档重复。

| 本轮任务                                   | 读取                                                                                     |
| ------------------------------------------ | ---------------------------------------------------------------------------------------- |
| 前端页面、组件、样式或状态                 | [前端规范](references/frontend-standard.md)                                              |
| 修改前端请求、错误处理或前后端共享类型     | [前端规范](references/frontend-standard.md)、[后端红线](references/backend-redlines.md)  |
| 修改 FastAPI API、服务、任务或配置         | [后端红线](references/backend-redlines.md)                                               |
| SQLite 模型、事务、迁移或备份              | [SQLite 规范](references/sqlite-standard.md)                                             |
| 后端调用 opscli SDK 或 REST                | [opscli 接入规范](references/opscli-integration-standard.md)                             |
| 页面需要真实业务数据                       | [数据访问规范](references/data-access-standard.md)，按其要求使用 `$ops-app-data-builder` |
| 项目迁移或补齐后端规范                     | [迁移规范](references/migration-standard.md)                                             |
| 创建应用、绑定仓库、提交源码或检查交付条件 | [源码交付规范](references/deployment-standard.md)                                        |

首次接手或相关文件变化时，读取项目 `AGENTS.md`、`README.md` 和 `docs/apphub-contract.md`；进入子目录时读取适用的项目规则。后端改动与接口变化再核对 `backend/CLAUDE.md`、受影响路由、Pydantic Schema 和 OpenAPI；纯样式改动不额外读取后端全文。普通开发不读取 `assets/backend/` 中的全文规范。

## 新项目

1. 确认应用展示名称，并确认目标目录不存在或为空。
2. 使用当前 Skill 的安全脚本；`<skill-directory>` 为当前 Skill 绝对路径，`<project-directory>` 为目标项目目录：

   ```bash
   python "<skill-directory>/scripts/clone_template.py" "<project-directory>"
   ```

   脚本直接 clone 到目标目录，成功后立即删除项目根目录 `.git` 并验证其不存在；保留 `.gitignore` 和原有项目说明，不使用临时目录。任一步失败都停止，禁止手动跳过清理继续开发。

3. 模板准备成功后立即创建 AppHub 应用并写入本地 binding：

   ```bash
   opscli app create "<app-name>" --path "<project-directory>" --json
   ```

4. `create` 成功后立即初始化全新 Git 仓库并绑定业务仓库：

   ```bash
   opscli app init "<project-directory>" --json
   ```

5. 核对独立 Git 根、`master` 分支和 `origin`，确认 `origin` 不指向统一模板仓库；首次绑定目标远端必须已有 `git-bind-preflight` 成功证据，正常后续 push 不重复执行空仓库预检。确认 `.opscli/app.json.slug == app.yaml.name`，并按部署规范检查 binding。
6. 开发前读取目标项目的规则与本轮参考文件，再实现业务需求。

clone 并脱离模板 Git 元数据、`create` 和 `init` 是开始开发前连续执行的必需步骤。`create/init` 不负责获取模板。任何一步失败都停止后续开发，业务代码不得推回模板仓库。不得运行项目生成器、手写替代脚手架，或从 Skill 复制应用代码与发布资产。

## 已有项目与项目约定

应用唯一身份是严格匹配 `^[0-9A-Za-z]{5}$`、区分大小写的 `app_id`。只接受 schema v4 的 `.opscli/app.json`；v1、v2、v3、`site_name/site_id/created_by` 旧字段、非法 ID 或缺失环境标识时立即停止，不迁移、不备份替换。仅在目录完全没有 binding 时，核对平台应用 ID 后执行 `opscli app init "<project-directory>" --app-id "<app_id>" --json`。`--app` 仅核对 slug，不能查询、选择、恢复或创建应用。

创建超时或失败后，在原目录使用相同名称、账号和环境重试 `create`；保留 `.opscli/creation.json` 的本地创建意图和并发保护记录，但不得把其中 UUID 作为 `Idempotency-Key` 发送给 AppHub。服务端按同一 owner 和 slug 幂等重入。`app_id` 不写入 `app.yaml`，仓库地址只使用平台返回的 `repo_url`，不得从 slug 拼接。

Git 凭据禁止自动轮换。平台已绑定但本机缺少匹配凭据时停止；只有用户明确接受其他机器旧凭据失效后，才执行 `opscli app init "<project-directory>" --rotate-git-credential --json`。`app push` 不得隐式发送 `rotate=true`。

业务项目绑定自己的远端后，不能只根据 remote 判断模板身份。根目录应有 `app.yaml`、`AGENTS.md`、`docs/apphub-contract.md`、`frontend/`、`backend/app.py` 和 `backend/CLAUDE.md`，运行入口与项目合同一致。合同缺失时读取迁移规范，不在原目录重新初始化或批量覆盖。

无论新项目还是已绑定项目，都沿用实际项目规则：

- Skill 的安装和调用入口由模板项目维护，本 Skill 不注入项目规则或宿主钩子。
- `AGENTS.md` 保持简短，只放项目约束和规范入口；保留原有业务说明与其他工具规则。开发命令继续维护在 `README.md`，不为普通需求强制生成另一套 `project-spec/development/deployment` 文档。
- 只有新增长期有效的业务约定、维护限制或验证方式时，才更新对应项目文档，并引用实际源码或测试。数据层需要的 `docs/ops-app/data-spec.md` 等文档仍按数据访问规范维护。
- 迁移项目缺少后端规范时，可按迁移规范从 `assets/backend/` 补齐；这些资产只有规范，不含构建或发布脚手架。

## 开发纪律

- 动手前查现有实现和调用方。较大改动简要说明目标、涉及模块及可观察的验收结果；小改动直接处理，不强制任务目录、PRD、多 Agent 或重复确认。
- 技术事实从代码、测试和配置查证；只向用户确认项目无法回答的业务口径、范围或验收行为。不让非开发用户选择实现框架。
- 优先复用项目已有能力和依赖。仅实现当前需求；不提前设计插件系统、万能组件、配置驱动框架或未使用的扩展点。
- 同一业务概念需要一起变化时再抽取公共能力；外观相似或字面量相同不构成抽象理由。文件按职责拆分，不追求最少文件或固定行数。
- 只修改当前需求相关代码，保留用户已有修改；清理本次产生的无用代码，不顺手格式化或重构无关模块。简短注释说明业务规则与特殊处理的原因。
- 改公共组件、请求函数或状态字段时搜索全部调用方，检查影响；修复行为实际所属位置，避免调用处层层补丁。不得用前端兼容分支掩盖后端合同漂移。
- 页面涉及真实数据时按数据规范交给数据 Skill；本 Skill 不选择或猜测数据集、字段、聚合、筛选、第三方场景或运行时签名。前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 不读取、输出或提交真实密钥、本地运行数据库和业务数据文件。已初始化的空白模板库按项目合同保留。
- 执行沿用用户已明确授权的范围和宿主权限。范围内的检查、修复不重复求确认；提交、推送、部署和真实数据写入须有相应授权，加载本 Skill 不授予这些权限。

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
## 验证与源码交付

- 完成后检查实际 diff，包括新增文件和已有暂存改动，确认没有无关重构、重复基础设施、调试残留或通过关闭规则绕过检查。
- 按改动运行相关行为测试；Bug 修复应有能复现问题的验证。文案、间距等低风险改动不机械新增测试。已有无关失败要说明，不删测试以换取通过。
- 源码交付前按部署规范执行前端测试、生产构建及项目合同要求的检查；命令取实际项目，不能编造尚不存在的 `lint/typecheck`。
- 页面主流程、布局、真实联调、平台环境分别需要对应证据；构建通过不能代替浏览器或线上验收。
- 提交前重新读取部署规范，确认本次完整文件范围、binding 与目标仓库。用户明确授权后执行 `opscli app push "<project-directory>" --message "<summary>"`；不绕过它直接 Push，不创建第二条 release。
- push 成功只表示源码到达远端。线上构建、发布、健康状态和回滚由 AppHub 处理，没有平台证据时不得报告已部署。

## 错误与输出

模板克隆或 Git 清理失败时保留原始错误并停止后续初始化；合同无法核实时保留已验证部分，不伪造实现。迁移无法保持业务行为时保留源项目。

`opscli` CLI 或相关 MCP 工具失败时，立即按 `ops-feedback` 规范提交结构化反馈并返回 `feedback_uuid`；认证未授权、用户取消和五分钟内已反馈的同一错误除外。

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

首次源码交付前确认根目录存在 schema v4 的 `.opscli/app.json`，binding 中 `app_id` 严格匹配 `^[0-9A-Za-z]{5}$`，`default_branch` 固定为 `master`，且 `.opscli/app.json.slug == app.yaml.name`。`app_id`、仓库、Owner 和 Git 信息只保留在本地 binding，不写入 `app.yaml`；`.gitignore` 必须忽略 `.opscli/`。

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

简要报告修改文件、实际验证、交付状态和阻塞项。未执行的测试、构建、浏览器验收或线上部署不得写成通过。
