---
name: ops-app-build-spec
description: 用于盘点未知 Web 项目、生成项目规范，并将受支持项目规范化为 Vite + React/Vue、FastAPI + SQLite 和 Docker Compose 部署结构；遇到不支持的技术栈时停止并提示联系 IT。
version: 0.0.1
---

# OPS 应用规范与部署初始化

面向不了解现有代码结构的业务开发者。先用仓库证据识别项目，再生成规范、迁移受支持技术栈并准备部署产物。

## Reference 路由

| 场景 | 必须读取 |
| --- | --- |
| 判断或改造前端 | `references/frontend-standard.md` |
| 新建或改造后端 | `references/backend-standard.md` |
| 现有项目不是目标结构 | `references/migration-standard.md` |
| 初始化部署或首次发布 | `references/deployment-standard.md` |

只读取当前阶段需要的文档。进入迁移时同时读取目标端规范；进入发布时读取全部与实际服务相关的规范。

## 必要输入

- 项目根目录。
- 操作意图：`检查`、`初始化/迁移` 或 `发布检查`。用户未明确时，根据动词判断；仍有歧义才询问。
- 应用名称。优先读取现有包名或仓库名；无法得到唯一 URL 安全名称时询问。
- 项目 ID 仅在第一次发布时必需，初始化阶段允许为空。

应用名称只允许小写字母、数字和连字符，且必须以字母或数字开头、结尾。
项目 ID 必须是非空 URL 安全单路径段，只允许字母、数字、连字符和下划线；禁止 `/`、`\\`、`.`、`..`、空白和 URL 编码路径分隔符。

## 执行流程

### 1. 只读盘点

读取根目录、依赖清单、锁文件、入口、路由、静态资源、环境变量示例、API、数据库、测试、构建配置和现有部署文件。不得仅凭目录名判断技术栈，不读取或输出真实密钥。

将证据和结论写入 `docs/ops-app/assessment.md`，至少包含：

- 当前前端、后端、数据库和包管理器。
- 关键入口、构建命令与运行方式。
- 支持结论、迁移风险和未识别项。
- 预计新增、修改、保留的文件。

### 2. 技术栈路由

| 当前项目 | 处理方式 |
| --- | --- |
| Vite + React | 保留 React，按前端规范补齐 |
| Vite + Vue 3 | 保留 Vue 3，按前端规范补齐 |
| Next.js + React | 按迁移规范转换为 Vite + React |
| 普通 HTML/CSS/JS | 转换为 Vite + Vue 3 + Element Plus |
| 无后端 | 初始化 FastAPI + SQLite |
| FastAPI + SQLite | 按后端规范补齐 |

Vue 2、其他前端框架、非 FastAPI 后端和任何非 SQLite 数据库，均停止自动改造。列出识别证据、保留现状并告诉用户：`当前技术栈不在自动迁移范围，请联系 IT 人员处理。`

Next.js 仅自动迁移能保持客户端行为的项目。发现 SSR、RSC、ISR、Server Actions、Edge Runtime 或 Middleware 等服务端语义时，按迁移规范停止，不做表面替换。

### 3. 生成迁移计划

`检查`模式到此停止并返回评估文件。`初始化/迁移`模式继续生成 `docs/ops-app/migration-plan.md`，列出页面、路由、接口、数据和部署映射。大范围移动、覆盖或删除文件前必须取得用户明确确认。

### 4. 规范化项目

按实际需要创建以下结构，不创建空目录或占位服务：

```text
frontend/
backend/
deployment/
docs/ops-app/
ops-app.config
```

初始化部署时必须将 Skill 的 `assets/nginx.conf.template` 复制为项目的 `deployment/nginx.conf.template`。项目内 Nginx 必须使用该模板，不得另写会削弱部署路径、SPA 回退或缓存规则的配置。

生成或更新：

- `docs/ops-app/project-spec.md`：当前技术栈、目录、命令、路由、接口、数据和约束。
- `docs/ops-app/development.md`：本地开发、环境变量和联调方式。
- `docs/ops-app/deployment.md`：构建、路径、持久化、发布检查和回滚说明。
- 根目录 `AGENTS.md`：只写简短受管区块，引用上述规范；已有文件时保留其他内容。

保留现有包管理器及唯一锁文件。依赖安装、服务启动和数据迁移仍遵守当前宿主的授权要求。

### 5. 项目配置

根目录 `ops-app.config` 是项目 ID、应用名称和部署前缀的唯一配置源，使用 JSON 内容。初始化时复制 Skill 的 `assets/ops-app.config`，只修改实际字段值：

```json
{
  "schemaVersion": 1,
  "projectId": null,
  "appName": "example-app"
}
```

初始化时不得伪造项目 ID。第一次发布时调用当前宿主提供的项目注册工具，验证返回值为 URL 安全单路径段后原子写回 `projectId`。后续发布复用已有 ID；工具未提供、返回空值、格式非法或本地与远端归属冲突时停止。

项目 ID 工具确定后，应在本 Skill 中补充真实工具名称、完整参数和示例。当前不得猜测命令或直接请求未定义接口。

同时复制以下共享资产到项目 `deployment/`：

- `assets/ops-app-config.mjs` → `deployment/ops-app-config.mjs`
- `assets/ops-app-config.d.mts` → `deployment/ops-app-config.d.mts`
- `assets/render-nginx-config.mjs` → `deployment/render-nginx-config.mjs`

Vite 和 Nginx 渲染脚本必须调用同一个 `ops-app-config.mjs` 完成校验和部署前缀派生。禁止在 `.env`、Compose、Dockerfile、Vite 或 Nginx 中重复维护项目 ID、应用名称或完整部署路径。

### 6. 构建路径

部署前缀固定为：

```text
/ops-app/{projectId}/{appName}/
```

Vite 本地开发使用 `/`；`vite build` 调用 `loadOpsAppConfig(..., { requireProjectId: true })` 和 `getOpsAppDeployBase()` 设置 `base`。缺少项目 ID 时构建必须失败并给出可操作错误。前端镜像将 `dist` 内容复制到 Nginx 静态根目录，并在 Node 构建阶段调用 `render-nginx-config.mjs` 读取同一配置文件生成最终 Nginx 配置；不得使用另一组环境变量或 build args。默认模板剥离请求中的部署前缀后查找文件，不得再把 `dist` 放入同名 `/ops-app/...` 子目录。路由基路径、动态静态资源和 Nginx SPA 回退按前端、部署规范同步修改；API 地址不得拼入静态资源前缀。

### 7. 部署与验收

发布前必须确认：

- `deployment/Dockerfile`、`deployment/compose.yaml`、`deployment/nginx.conf.template`、`deployment/ops-app-config.mjs`、`deployment/ops-app-config.d.mts`、`deployment/render-nginx-config.mjs` 存在；Dockerfile 同时提供前端、后端构建 target，并通过共享配置模块和渲染脚本生成项目内 Nginx 配置。
- Vite 配置已导入 `deployment/ops-app-config.mjs`，Compose、Dockerfile 和环境变量中没有重复的项目 ID、应用名称或部署路径。
- Compose 同时声明前端、后端服务；SQLite 使用持久卷。
- 前后端构建、测试、健康检查及 `docker compose config` 通过。
- 构建产物引用部署前缀，本地开发仍使用根路径。
- SPA 嵌套路由刷新、API 访问和容器重启后的数据持久化通过。

未获得启动服务许可时，只执行静态检查、测试、构建和 Compose 配置校验，不启动容器。

## 错误处理

- 识别证据冲突：列出冲突并询问，不猜测。
- 迁移后行为不一致：停止后续迁移，保留失败证据，不删除旧实现。
- 项目注册工具或 `opscli`/MCP 工具失败：按 `ops-feedback` 规范立即提交结构化反馈；认证未授权和用户取消除外。
- 部分写入或发布状态不确定：重新读取本地状态后停止，不重复创建项目或重复发布。

## 输出规范

最终回复只包含：识别结果、支持结论、完成的规范/迁移/部署文件、验证结果、阻塞项和需要用户执行的下一步。不得把未运行的构建、容器或浏览器检查写成已通过。
