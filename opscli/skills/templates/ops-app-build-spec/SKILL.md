---
name: ops-app-build-spec
description: 用于按模板先行流程创建全新 opscli app 站点，或盘点和规范化已有 Web 项目，并生成 Vite + React/Vue、FastAPI + SQLite 和 Docker Compose 项目规范；遇到不支持的技术栈时停止并提示联系 IT。
---

# OPS 应用规范与部署初始化

面向不了解现有代码结构的业务开发者。先用仓库证据识别项目，再生成规范、迁移受支持技术栈并准备部署产物。

## Reference 路由

| 场景 | 必须读取 |
| --- | --- |
| 判断或改造前端 | `references/frontend-standard.md` |
| 空项目初始化 | `references/initialization-standard.md` |
| 新建或改造后端 | `references/backend-standard.md` |
| 页面需要真实业务数据 | `references/data-access-standard.md` |
| 现有项目不是目标结构 | `references/migration-standard.md` |
| 初始化部署或首次发布 | `references/deployment-standard.md` |

只读取当前阶段需要的文档。进入迁移时同时读取目标端规范；进入发布时读取全部与实际服务相关的规范。

## 必要输入

- 项目根目录。
- 操作意图：`检查`、`初始化/迁移` 或 `发布检查`。用户未明确时，根据动词判断；仍有歧义才询问。
- 全新项目的站点显示名称。用户明确要求新建站点时可直接用于 `opscli app create`；无法确定时询问。
- 已绑定项目的应用身份必须读取根目录 `.opscli/app.json`，不得从目录名、包名或用户描述猜测 `app_id` 和 `slug`。

binding 的 `slug` 和 `ops-app.config.appName` 只允许小写字母、数字和连字符，且必须以字母或数字开头、结尾。
应用 ID 必须是非空 URL 安全单路径段，只允许字母、数字、连字符和下划线；禁止 `/`、`\\`、`.`、`..`、空白和 URL 编码路径分隔符。

`ops-app.config.appName` 使用 binding 中的 `slug`，`ops-app.config.appId` 使用 binding 中的 `app_id`。

## 执行流程

### 0. 新项目模板门禁

在向项目根目录写入任何文件前，先只读判断项目状态：

| 项目状态 | 处理方式 |
| --- | --- |
| 全新且未绑定 | 先执行或引导执行 `opscli app create <site_name> --path <root>`，再执行 `opscli app init <root>` |
| 已绑定但仍为空 | 先执行 `opscli app init <root>` 拉取模板 |
| 已有源码 | 进入已有项目盘点；后续 `app init` 必须跳过模板并保留源码 |

全新项目在 `opscli app init` 成功并返回 `template_applied=true` 之前，不得创建或修改 README、需求文档、`docs/ops-app/assessment.md`、`ops-app.config`、前后端、测试或部署文件。用户尚未明确授权创建远端应用时，只在会话中整理需求并请求确认，不得用本地脚手架绕过 AppHub 创建流程。

模板初始化完成后重新读取整个项目，以实际模板内容作为盘点证据。不得使用初始化前的空目录结论，也不得再运行 `create-vue`、复制本 Skill 的空项目脚手架或生成第二套基础工程。模板缺少本规范要求的关键结构时停止，记录缺失项并提示维护模板仓库。

### 1. 只读盘点

读取根目录、依赖清单、锁文件、入口、路由、静态资源、环境变量示例、API、数据库、测试、构建配置和现有部署文件。不得仅凭目录名判断技术栈，不读取或输出真实密钥。

将证据和结论写入 `docs/ops-app/assessment.md`，至少包含：

- 当前前端、后端、数据库和包管理器。
- 关键入口、构建命令与运行方式。
- 页面真实数据用途、现有数据源、调用路径和前端直连或凭证风险。
- 支持结论、迁移风险和未识别项。
- 预计新增、修改、保留的文件。

### 2. 技术栈路由

| 当前项目 | 处理方式 |
| --- | --- |
| 全新 opscli app | 先执行 `app create → app init` 拉取模板，再按模板实际技术栈处理 |
| Vite + React | 保留 React，按前端规范补齐 |
| Vite + Vue 3 | 保留 Vue 3，按前端规范补齐 |
| Next.js + React | 按迁移规范转换为 Vite + React |
| 普通 HTML/CSS/JS | 转换为 Vite + Vue 3 + Element Plus |
| 无后端 | 只初始化前端，等待后端人员交付 |
| FastAPI + SQLite | 按后端规范补齐 |

Vue 2、其他前端框架、非 FastAPI 后端和任何非 SQLite 数据库，均停止自动改造。列出识别证据、保留现状并告诉用户：`当前技术栈不在自动迁移范围，请联系 IT 人员处理。`

Next.js 仅自动迁移能保持客户端行为的项目。发现 SSR、RSC、ISR、Server Actions、Edge Runtime 或 Middleware 等服务端语义时，按迁移规范停止，不做表面替换。

### 3. 生成迁移计划

`检查`模式到此停止并返回评估文件。`初始化/迁移`模式继续生成 `docs/ops-app/migration-plan.md`，列出页面、路由、接口、数据、加工、存储和部署映射。大范围移动、覆盖或删除文件前必须取得用户明确确认。

### 3.1 真实数据层路由

发现页面需要 OPS、Keepa、SellerSprite 或组合数据时，读取 `references/data-access-standard.md` 并使用 `$ops-app-data-builder`。向其传递项目根目录、页面业务需求和已确认范围，由它验证真实合同并生成或改造站点数据层。

本 Skill 只负责识别和委托，不选择或猜测数据集、字段、聚合、筛选、第三方场景、SDK 导入路径或运行时方法签名。`检查`模式只记录需求和风险，不执行数据层改造。

### 4. 规范化项目

按实际需要创建以下结构，不创建空目录或占位服务：

```text
frontend/
docs/ops-app/
ops-app.config
```

全新 opscli app 必须在模板项目上改造，不自行创建另一套前端或后端脚手架。已有项目缺少后端且后端尚未交付时，只补齐前端、文档和共享配置；不创建 `backend/`、生产 Dockerfile 或 Compose 占位服务。后端交付并提供启动、健康检查和构建契约后，才按部署规范生成后端与生产部署文件。

初始化部署时必须将 Skill 的 `assets/nginx.conf.template` 复制为项目的 `deployment/nginx.conf.template`。项目内 Nginx 必须使用该模板，不得另写会削弱部署路径、SPA 回退或缓存规则的配置。

生成或更新：

- `docs/ops-app/project-spec.md`：当前技术栈、目录、命令、路由、接口、数据和约束。
- 有真实数据需求时生成 `docs/ops-app/data-spec.md`：数据产品、真实合同、执行模式、站点 API、加工、SQLite、安全、测试和阻塞项。
- `docs/ops-app/development.md`：本地开发、环境变量和联调方式。
- 后端交付后生成 `docs/ops-app/deployment.md`：构建、路径、持久化、发布检查和回滚说明。
- 根目录 `AGENTS.md`：只写简短受管区块，引用上述规范；已有文件时保留其他内容。

保留现有包管理器及唯一锁文件。依赖安装、服务启动和数据迁移仍遵守当前宿主的授权要求。

根目录 `.dockerignore` 必须复制 Skill 的 `assets/.dockerignore`，再按实际构建输入补充；不得删掉密钥、本地数据库和依赖缓存排除项。

### 5. 项目配置

根目录 `ops-app.config` 是构建和部署阶段的应用身份配置源，使用 JSON 内容。模板初始化项目必须保留模板中的该文件并从 `.opscli/app.json` 同步实际字段；已有项目迁移缺少该文件时才复制 Skill 的 `assets/ops-app.config`：

```json
{
  "schemaVersion": 1,
  "appId": null,
  "appName": "example-app"
}
```

同步规则固定为：`.opscli/app.json.app_id` 写入 `ops-app.config.appId`，`.opscli/app.json.slug` 写入 `ops-app.config.appName`。写入前校验 binding 和配置格式，使用临时文件原子替换；配置已有非占位值但与 binding 不一致时停止，不得覆盖冲突身份。不得在第一次发布时再次注册应用，也不得调用未定义的应用 ID 工具。

同时复制以下共享资产到项目 `deployment/`：

- `assets/ops-app-config.mjs` → `deployment/ops-app-config.mjs`
- `assets/ops-app-config.d.mts` → `deployment/ops-app-config.d.mts`
- `assets/render-nginx-config.mjs` → `deployment/render-nginx-config.mjs`

Vite 和 Nginx 渲染脚本必须调用同一个 `ops-app-config.mjs` 完成校验和部署前缀派生。禁止在 `.env`、Compose、Dockerfile、Vite 或 Nginx 中重复维护应用 ID、应用名称或完整部署路径。

### 6. 构建路径

部署前缀固定为：

```text
/ops-app/{appId}/{appName}/
```

Vite 本地开发使用 `/`；`vite build` 调用 `loadOpsAppConfig(..., { requireAppId: true })` 和 `getOpsAppDeployBase()` 设置 `base`。缺少应用 ID 时构建必须失败并给出可操作错误。前端镜像将 `dist` 内容复制到 Nginx 静态根目录，并在 Node 构建阶段调用 `render-nginx-config.mjs` 读取同一配置文件生成最终 Nginx 配置；不得使用另一组环境变量或 build args。默认模板剥离请求中的部署前缀后查找文件，不得再把 `dist` 放入同名 `/ops-app/...` 子目录。路由基路径、动态静态资源和 Nginx SPA 回退按前端、部署规范同步修改；API 地址不得拼入静态资源前缀。

### 7. 部署与验收

发布前必须确认：

- `.opscli/app.json` 存在，`ops-app.config.appId/appName` 分别与 binding 的 `app_id/slug` 一致。

- `deployment/Dockerfile`、`deployment/compose.yaml`、`deployment/nginx.conf.template`、`deployment/ops-app-config.mjs`、`deployment/ops-app-config.d.mts`、`deployment/render-nginx-config.mjs` 存在；Dockerfile 同时提供前端、后端构建 target，并通过共享配置模块和渲染脚本生成项目内 Nginx 配置。
- 部署构建基线为 Linux 服务器：Compose 必须显式使用 `context: ..` 与 `dockerfile: deployment/Dockerfile`；本地宿主机兼容性问题只记录，不改变项目产物规范。
- 根目录 `.dockerignore` 存在，且没有排除构建必需的源码、锁文件、`ops-app.config` 或 deployment 资产。
- Vite 配置已导入 `deployment/ops-app-config.mjs`，Compose、Dockerfile 和环境变量中没有重复的应用 ID、应用名称或部署路径。
- Compose 同时声明前端、后端服务；SQLite 使用持久卷。
- Dockerfile 使用精确 `COPY` 分层和 BuildKit 缓存；禁止无边界 `COPY . .`，但必须复制依赖清单、锁文件、源码和部署模板。
- 后端依赖统一使用 `uv`、`pyproject.toml`、`uv.lock`；Nginx 以非 root 用户监听 `8080`；Dockerfile 不声明 `VOLUME`，持久卷只由 Compose 管理。
- 根目录 `.dockerignore` 排除依赖目录、构建缓存、本地数据库、环境文件和密钥，同时保留锁文件、配置和部署资产。
- Compose 使用最新 Compose Specification；前后端镜像名由 `ops-app.config` 派生为 `<appId>-<appName>-frontend|backend`，同时发布 `:sha-<git-sha>` 和 `:latest`，线上始终拉取 `:latest`。
- 空项目初始化只要求 Node.js 主版本大于 22；补丁版本 engine 警告允许记录到评估文档，不作为初始化、构建或测试的阻断条件。
- 前后端构建、测试、健康检查及 `docker compose config` 通过。
- 构建产物引用部署前缀，本地开发仍使用根路径。
- SPA 嵌套路由刷新、API 访问和容器重启后的数据持久化通过。
- 前端只调用当前站点 `/api`，没有直连 OPS、opscli REST、Keepa 或 SellerSprite。
- `VITE_*`、源码、镜像、Compose、日志和 SQLite 中没有 API Key、JWT、Cookie 或完整鉴权头。
- OPS 使用实际项目中经过批准的应用运行时身份适配器，未隔离的 viewer 数据没有写入共享 SQLite。
- Keepa 只使用正式 opscli REST 端点和后端 Secret；SellerSprite Mock 没有被当作真实线上接入。
- `docs/ops-app/data-spec.md` 与实际 Pydantic Schema、前端类型、迁移和运行时能力一致。

未获得启动服务许可时，只执行静态检查、测试、构建和 Compose 配置校验，不启动容器。

## 错误处理

- 识别证据冲突：列出冲突并询问，不猜测。
- 迁移后行为不一致：停止后续迁移，保留失败证据，不删除旧实现。
- 项目注册工具或 `opscli`/MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。
- 数据合同无法验证、OPS 运行时适配器缺失或 SellerSprite 没有正式入口：保留已验证部分，在 data-spec 标记阻塞，不伪造调用代码。
- 部分写入或发布状态不确定：重新读取本地状态后停止，不重复创建项目或重复发布。

## 输出规范

最终回复只包含：识别结果、支持结论、完成的规范/迁移/部署文件、验证结果、阻塞项和需要用户执行的下一步。不得把未运行的构建、容器或浏览器检查写成已通过。
